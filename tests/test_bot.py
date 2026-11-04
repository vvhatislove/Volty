from collections.abc import AsyncGenerator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageText,
    GetMe,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberUpdated,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import FakeClient
from volty.bot.callbacks import CONNECT, RENAME_LIST, RegionCallback
from volty.bot.dispatcher import build_dispatcher
from volty.bot.handlers import battery, connect, groups, menu, notifications, settings
from volty.crypto import CredentialCipher
from volty.inverters import Brand
from volty.inverters.base import (
    AuthenticationError,
    Credentials,
    GridState,
    InverterInfo,
    InverterState,
)
from volty.inverters.pool import ClientPool
from volty.storage import repository
from volty.storage.models import User as VoltyUser

USER_ID = 42
GROUP_ID = -100
OTHER_USER_ID = 77


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []

    async def close(self) -> None:
        pass

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109
    ) -> Any:
        self.requests.append(method)
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="Volty", username="volty_bot")
        if isinstance(method, SendMessage | EditMessageText):
            return Message(
                message_id=len(self.requests) + 1000,
                date=datetime.now(UTC),
                chat=Chat(id=USER_ID, type="private"),
                text=method.text,
            ).as_(bot)
        return True

    def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes]:
        raise NotImplementedError

    def sent_texts(self) -> list[str]:
        return [
            method.text or ""
            for method in self.requests
            if isinstance(method, SendMessage | EditMessageText)
        ]

    def deleted_ids(self) -> list[int]:
        return [m.message_id for m in self.requests if isinstance(m, DeleteMessage)]


@dataclass
class Harness:
    dispatcher: Dispatcher
    bot: Bot
    session: RecordingSession
    client: FakeClient
    sessions: async_sessionmaker[AsyncSession]
    cipher: CredentialCipher
    updates: int = field(default=0)

    def _user(self, user_id: int = USER_ID) -> User:
        return User(id=user_id, is_bot=False, first_name="Test", language_code="en")

    def _message(self, text: str, chat_type: str, user_id: int) -> Message:
        self.updates += 1
        chat_id = user_id if chat_type == "private" else GROUP_ID
        return Message(
            message_id=self.updates,
            date=datetime.now(UTC),
            chat=Chat(id=chat_id, type=chat_type, title="Family"),
            from_user=self._user(user_id),
            text=text,
        )

    async def send(self, text: str, chat_type: str = "private", user_id: int = USER_ID) -> int:
        message = self._message(text, chat_type, user_id).as_(self.bot)
        await self.dispatcher.feed_update(self.bot, Update(update_id=self.updates, message=message))
        return message.message_id

    async def press(self, data: str) -> None:
        message = self._message("menu", "private", USER_ID)
        callback = CallbackQuery(
            id="1", from_user=self._user(), chat_instance="x", data=data, message=message
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=self.updates, callback_query=callback)
        )

    async def connect(self, password: str = "secret") -> tuple[int, int]:
        await self.press(CONNECT)
        await self.press(RegionCallback(region="eu").pack())
        login_id = await self.send("user@example.com")
        password_id = await self.send(password)
        return login_id, password_id

    def keyboards(self) -> list[InlineKeyboardMarkup]:
        return [
            method.reply_markup
            for method in self.session.requests
            if isinstance(method, SendMessage | EditMessageText)
            and isinstance(method.reply_markup, InlineKeyboardMarkup)
        ]


@pytest.fixture(autouse=True)
def detach_routers() -> Iterator[None]:
    # Routers are module-level and refuse a second parent, but each test builds a dispatcher.
    yield
    for router in (
        menu.router,
        menu.fallback_router,
        battery.router,
        notifications.router,
        settings.router,
        connect.router,
        groups.router,
    ):
        router._parent_router = None


@pytest.fixture
def harness(sessions: async_sessionmaker[AsyncSession], cipher: CredentialCipher) -> Harness:
    client = FakeClient()
    client.inverters = [InverterInfo(serial="0000000001", model="LXP-EU 12K")]
    session = RecordingSession()
    bot = Bot("42:TEST", session=session)

    def factory(brand: Brand, region: str, credentials: Credentials) -> FakeClient:
        return client

    pool = ClientPool(cipher, factory)
    dispatcher = build_dispatcher(sessions, pool, cipher, factory)
    return Harness(dispatcher, bot, session, client, sessions, cipher)


async def test_connect_deletes_secret_messages_and_stores_encrypted_credentials(
    harness: Harness,
) -> None:
    login_id, password_id = await harness.connect("hunter2")

    assert harness.session.deleted_ids() == [login_id, password_id]
    assert "✅ Connected: LXP-EU 12K" in harness.session.sent_texts()[-1]
    assert not any("hunter2" in text for text in harness.session.sent_texts())

    async with harness.sessions() as session:
        account = (await repository.list_user_accounts(session, USER_ID))[0]
    assert account.region == "eu"
    assert b"hunter2" not in account.encrypted_credentials
    assert harness.cipher.decrypt(account.encrypted_credentials) == Credentials(
        login="user@example.com", password="hunter2"
    )


async def test_rejected_password_saves_nothing(harness: Harness) -> None:
    async def reject() -> list[InverterInfo]:
        raise AuthenticationError

    harness.client.list_inverters = reject  # type: ignore[method-assign]

    _, password_id = await harness.connect()

    assert password_id in harness.session.deleted_ids()
    assert "rejected" in harness.session.sent_texts()[-1]
    async with harness.sessions() as session:
        assert not await repository.list_user_accounts(session, USER_ID)


async def test_menu_button_during_connect_is_not_taken_as_login(harness: Harness) -> None:
    await harness.press(CONNECT)
    await harness.press(RegionCallback(region="eu").pack())

    message_id = await harness.send("🔋 Battery")

    assert message_id not in harness.session.deleted_ids()
    assert harness.session.sent_texts()[-1] == "No inverters connected yet."


async def test_group_messages_are_ignored(harness: Harness) -> None:
    await harness.press(CONNECT)
    await harness.press(RegionCallback(region="eu").pack())
    before = len(harness.session.requests)

    await harness.send("my password", chat_type="group")

    assert len(harness.session.requests) == before


async def test_battery_button_shows_charge_and_voltage(harness: Harness) -> None:
    await harness.connect()
    harness.client.states.append(
        InverterState(
            online=True, grid=GridState.OFF_GRID, soc=64, battery_voltage=51.2, discharge_power=820
        )
    )

    await harness.send("🔋 Battery")

    text = harness.session.sent_texts()[-1]
    assert "Charge: 64%" in text
    assert "Voltage: 51.2 V" in text
    assert "running on batteries" in text
    assert "Discharging: 820 W" in text


async def test_notifications_button_toggles_setting(harness: Harness) -> None:
    await harness.connect()
    await harness.send("🔔 Notifications")
    button = harness.keyboards()[-1].inline_keyboard[0][0]
    assert button.text.startswith("🔔")
    assert button.callback_data is not None

    await harness.press(button.callback_data)

    assert harness.keyboards()[-1].inline_keyboard[0][0].text.startswith("🔕")
    async with harness.sessions() as session:
        inverter = (await repository.list_user_inverters(session, USER_ID))[0]
    assert not inverter.notifications_enabled


async def test_callbacks_are_answered(harness: Harness) -> None:
    await harness.press(CONNECT)

    assert any(isinstance(m, AnswerCallbackQuery) for m in harness.session.requests)


async def _inverter_id(harness: Harness) -> int:
    async with harness.sessions() as session:
        return (await repository.list_user_inverters(session, USER_ID))[0].id


async def _group_chat(harness: Harness) -> int | None:
    async with harness.sessions() as session:
        return (await repository.list_user_inverters(session, USER_ID))[0].group_chat_id


async def test_rename_changes_the_name_everywhere(harness: Harness) -> None:
    await harness.connect()
    await harness.press(RENAME_LIST)

    await harness.send("Home")

    assert "“Home”" in harness.session.sent_texts()[-1]
    await harness.send("🔔 Notifications")
    assert harness.keyboards()[-1].inline_keyboard[0][0].text.startswith("🔔 Home:")


@pytest.mark.parametrize("name", ["   ", "x" * 65], ids=["blank", "too long"])
async def test_invalid_name_is_refused_and_can_be_retried(harness: Harness, name: str) -> None:
    await harness.connect()
    await harness.press(RENAME_LIST)

    await harness.send(name)
    assert "1 to 64" in harness.session.sent_texts()[-1]

    await harness.send("Home")
    assert "“Home”" in harness.session.sent_texts()[-1]


async def test_notifications_screen_offers_a_group_link(harness: Harness) -> None:
    await harness.connect()
    inverter_id = await _inverter_id(harness)

    await harness.send("🔔 Notifications")

    button = harness.keyboards()[-1].inline_keyboard[1][0]
    assert button.url == f"https://t.me/volty_bot?startgroup={inverter_id}"


async def test_owner_links_group_and_can_unlink_it(harness: Harness) -> None:
    await harness.connect()
    inverter_id = await _inverter_id(harness)

    await harness.send(f"/start@volty_bot {inverter_id}", chat_type="group")

    assert await _group_chat(harness) == GROUP_ID
    assert "this group" in harness.session.sent_texts()[-1]

    await harness.send("🔔 Notifications")
    button = harness.keyboards()[-1].inline_keyboard[1][0]
    assert button.text.endswith("Family ✖️")
    assert button.callback_data is not None
    await harness.press(button.callback_data)
    assert await _group_chat(harness) is None


async def test_stranger_cannot_link_someone_elses_inverter(harness: Harness) -> None:
    await harness.connect()
    inverter_id = await _inverter_id(harness)

    await harness.send(f"/start@volty_bot {inverter_id}", chat_type="group", user_id=OTHER_USER_ID)

    assert await _group_chat(harness) is None


async def test_group_members_are_not_stored_as_users(harness: Harness) -> None:
    await harness.send("/start@volty_bot 1", chat_type="group", user_id=OTHER_USER_ID)
    await harness.send("hello", chat_type="group", user_id=OTHER_USER_ID)

    async with harness.sessions() as session:
        assert await session.get(VoltyUser, OTHER_USER_ID) is None


async def test_removing_the_bot_from_a_group_unlinks_it(harness: Harness) -> None:
    await harness.connect()
    await harness.send(f"/start@volty_bot {await _inverter_id(harness)}", chat_type="group")
    bot_user = User(id=1, is_bot=True, first_name="Volty")

    await harness.dispatcher.feed_update(
        harness.bot,
        Update(
            update_id=9000,
            my_chat_member=ChatMemberUpdated(
                chat=Chat(id=GROUP_ID, type="group", title="Family"),
                from_user=harness._user(),
                date=datetime.now(UTC),
                old_chat_member=ChatMemberMember(user=bot_user),
                new_chat_member=ChatMemberLeft(user=bot_user),
            ),
        ),
    )

    assert await _group_chat(harness) is None
