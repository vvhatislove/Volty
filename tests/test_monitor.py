from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramNetworkError,
    TelegramUnauthorizedError,
)
from aiogram.methods import SendMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import FakeClient
from volty.crypto import CredentialCipher
from volty.inverters import Brand
from volty.inverters.base import (
    AuthenticationError,
    Credentials,
    GridState,
    InverterInfo,
    InverterState,
    InverterUnavailableError,
)
from volty.inverters.pool import ClientPool
from volty.monitoring.monitor import InverterMonitor
from volty.storage import repository
from volty.storage.models import Inverter

GROUP_ID = -100
NEW_GROUP_ID = -1000000000100
ON_GRID = InverterState(online=True, grid=GridState.ON_GRID, soc=71, battery_voltage=53.0)
CHARGING = InverterState(
    online=True, grid=GridState.ON_GRID, soc=71, battery_voltage=53.0, charge_power=500
)
OFF_GRID = InverterState(
    online=True, grid=GridState.OFF_GRID, soc=64, battery_voltage=51.2, discharge_power=800
)
OFFLINE = InverterState(online=False, grid=GridState.UNKNOWN)


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def bot() -> AsyncMock:
    return AsyncMock(spec=Bot)


@pytest.fixture
async def monitor(
    sessions: async_sessionmaker[AsyncSession],
    cipher: CredentialCipher,
    client: FakeClient,
    bot: AsyncMock,
) -> InverterMonitor:
    async with sessions() as session:
        await repository.get_or_create_user(session, 1, "ru")
        await repository.save_account(
            session,
            1,
            Brand.LUXPOWER,
            "eu",
            cipher.encrypt(Credentials(login="user", password="secret")),
            [InverterInfo(serial="0000000001", model="LXP")],
        )
        await session.commit()
    pool = ClientPool(cipher, lambda brand, region, credentials: client)
    return InverterMonitor(bot, sessions, pool, interval_seconds=60)


async def poll(monitor: InverterMonitor, client: FakeClient, *states: InverterState) -> None:
    client.states.extend(states)
    for _ in states:
        await monitor.poll_once()


async def test_outage_and_return_send_alerts_in_user_language(
    monitor: InverterMonitor, client: FakeClient, bot: AsyncMock
) -> None:
    await poll(monitor, client, ON_GRID, OFF_GRID)
    bot.send_message.assert_not_called()

    await poll(monitor, client, OFF_GRID)
    bot.send_message.assert_awaited_once()
    assert "Свет пропал" in bot.send_message.await_args.args[1]
    assert "64%" in bot.send_message.await_args.args[1]
    bot.send_message.reset_mock()

    await poll(monitor, client, CHARGING, CHARGING)
    bot.send_message.assert_awaited_once()
    assert "Заряжаем аккумуляторы" in bot.send_message.await_args.args[1]


async def test_return_without_charging_does_not_claim_charging(
    monitor: InverterMonitor, client: FakeClient, bot: AsyncMock
) -> None:
    await poll(monitor, client, OFF_GRID, ON_GRID, ON_GRID)

    assert "Свет появился" in bot.send_message.await_args.args[1]
    assert "Заряжаем" not in bot.send_message.await_args.args[1]


async def test_cloud_offline_never_alerts(
    monitor: InverterMonitor, client: FakeClient, bot: AsyncMock
) -> None:
    await poll(monitor, client, ON_GRID, OFFLINE, OFFLINE, OFFLINE, ON_GRID)

    bot.send_message.assert_not_called()


async def test_disabled_notifications_track_state_silently(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await poll(monitor, client, ON_GRID)
    async with sessions() as session:
        inverter = (await repository.list_user_inverters(session, 1))[0]
        inverter.notifications_enabled = False
        await session.commit()

    await poll(monitor, client, OFF_GRID, OFF_GRID)
    bot.send_message.assert_not_called()

    async with sessions() as session:
        inverter = (await repository.list_user_inverters(session, 1))[0]
        assert inverter.grid_state is GridState.OFF_GRID


async def link_group(sessions: async_sessionmaker[AsyncSession], chat_id: int) -> None:
    async with sessions() as session:
        inverter = (await repository.list_user_inverters(session, 1))[0]
        inverter.group_chat_id = chat_id
        inverter.group_chat_title = "Family"
        await session.commit()


async def test_alert_goes_to_private_chat_and_group(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await link_group(sessions, GROUP_ID)

    await poll(monitor, client, ON_GRID, OFF_GRID, OFF_GRID)

    assert [call.args[0] for call in bot.send_message.await_args_list] == [1, GROUP_ID]
    group_buttons = bot.send_message.await_args_list[1].kwargs["reply_markup"].inline_keyboard
    assert group_buttons[0][0].callback_data.startswith("view:")


async def test_group_gets_alert_when_direct_messages_are_off(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await link_group(sessions, GROUP_ID)
    async with sessions() as session:
        inverter = (await repository.list_user_inverters(session, 1))[0]
        inverter.notifications_enabled = False
        await session.commit()

    await poll(monitor, client, ON_GRID, OFF_GRID, OFF_GRID)

    assert [call.args[0] for call in bot.send_message.await_args_list] == [GROUP_ID]


async def test_group_failure_does_not_repeat_the_private_alert(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await link_group(sessions, GROUP_ID)
    failure = TelegramNetworkError(SendMessage(chat_id=GROUP_ID, text="x"), "no rights")
    bot.send_message.side_effect = [None, failure]

    await poll(monitor, client, ON_GRID, OFF_GRID, OFF_GRID, OFF_GRID)

    assert bot.send_message.await_count == 2


async def test_upgraded_group_is_followed_to_its_new_id(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await link_group(sessions, GROUP_ID)
    migrated = TelegramMigrateToChat(
        SendMessage(chat_id=GROUP_ID, text="x"), "migrated", migrate_to_chat_id=NEW_GROUP_ID
    )
    bot.send_message.side_effect = [None, migrated, None]

    await poll(monitor, client, ON_GRID, OFF_GRID, OFF_GRID)

    assert bot.send_message.await_args_list[-1].args[0] == NEW_GROUP_ID
    async with sessions() as session:
        inverter = (await repository.list_user_inverters(session, 1))[0]
    assert inverter.group_chat_id == NEW_GROUP_ID


async def test_failed_delivery_is_retried_on_next_poll(
    monitor: InverterMonitor, client: FakeClient, bot: AsyncMock
) -> None:
    await poll(monitor, client, ON_GRID, OFF_GRID)
    bot.send_message.side_effect = TelegramNetworkError(
        SendMessage(chat_id=1, text="x"), "network down"
    )
    await poll(monitor, client, OFF_GRID)
    bot.send_message.side_effect = None
    bot.send_message.reset_mock()

    await poll(monitor, client, OFF_GRID)

    bot.send_message.assert_awaited_once()


async def test_user_who_blocked_the_bot_is_not_retried(
    monitor: InverterMonitor, client: FakeClient, bot: AsyncMock
) -> None:
    bot.send_message.side_effect = TelegramForbiddenError(
        SendMessage(chat_id=1, text="x"), "blocked"
    )

    await poll(monitor, client, ON_GRID, OFF_GRID, OFF_GRID, OFF_GRID)

    bot.send_message.assert_awaited_once()


async def test_rejected_password_stops_polling_and_tells_user_once(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    client.states.extend([AuthenticationError(), AuthenticationError()])
    for _ in range(3):
        await monitor.poll_once()

    bot.send_message.assert_awaited_once()
    assert "пароль" in bot.send_message.await_args.args[1]
    async with sessions() as session:
        assert not await repository.list_monitored_accounts(session)


async def test_single_rejection_keeps_monitoring(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    client.states.extend([AuthenticationError(), ON_GRID, AuthenticationError(), ON_GRID])
    for _ in range(4):
        await monitor.poll_once()

    bot.send_message.assert_not_called()
    async with sessions() as session:
        assert await repository.list_monitored_accounts(session)


async def test_cloud_outage_keeps_polling_without_alerts(
    monitor: InverterMonitor, client: FakeClient, bot: AsyncMock
) -> None:
    client.states.extend([ON_GRID, InverterUnavailableError("down"), OFF_GRID, OFF_GRID])
    for _ in range(4):
        await monitor.poll_once()

    bot.send_message.assert_awaited_once()


async def set_scale(sessions: async_sessionmaker[AsyncSession], threshold: int) -> None:
    async with sessions() as session:
        inverter = (await repository.list_user_inverters(session, 1))[0]
        inverter.battery_full_voltage = 54.0
        inverter.battery_empty_voltage = 46.0
        inverter.low_charge_percent = threshold
        await session.commit()


async def test_return_alert_says_how_long_the_power_was_out(
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
    monitor: InverterMonitor,
) -> None:
    now = [datetime(2026, 11, 4, 12, 0, tzinfo=UTC)]
    monitor = InverterMonitor(bot, sessions, monitor._pool, 60, clock=lambda: now[0])
    await poll(monitor, client, ON_GRID, OFF_GRID, OFF_GRID)
    now[0] += timedelta(hours=3, minutes=20)

    await poll(monitor, client, ON_GRID, ON_GRID)

    assert "Света не было 3 ч 20 мин" in bot.send_message.await_args.args[1]
    async with sessions() as session:
        inverter = (await repository.list_user_inverters(session, 1))[0]
        assert await repository.open_outage_start(session, inverter.id) is None


async def test_return_alert_without_known_start_omits_duration(
    monitor: InverterMonitor, client: FakeClient, bot: AsyncMock
) -> None:
    await poll(monitor, client, OFF_GRID, ON_GRID, ON_GRID)

    assert "Света не было" not in bot.send_message.await_args.args[1]


async def test_low_charge_alert_shows_voltage_and_reaches_group(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await set_scale(sessions, 30)
    await link_group(sessions, GROUP_ID)
    low = InverterState(
        online=True, grid=GridState.OFF_GRID, soc=64, battery_voltage=47.6, discharge_power=800
    )

    await poll(monitor, client, low, low, low)

    chats = [call.args[0] for call in bot.send_message.await_args_list]
    assert chats == [1, GROUP_ID]
    text = bot.send_message.await_args.args[1]
    assert "Низкий заряд" in text
    assert "20% · 47.6 В" in text  # noqa: RUF001


async def test_scale_percent_replaces_cloud_percent_in_alerts(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await set_scale(sessions, 10)

    await poll(monitor, client, ON_GRID, OFF_GRID, OFF_GRID)

    assert "65% · 51.2 В" in bot.send_message.await_args.args[1]  # noqa: RUF001


async def test_long_offline_alerts_owner_and_group_then_reports_return(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await link_group(sessions, GROUP_ID)

    await poll(monitor, client, *[OFFLINE] * 5)

    assert [call.args[0] for call in bot.send_message.await_args_list] == [1, GROUP_ID]
    assert "несколько минут" in bot.send_message.await_args.args[1]
    bot.send_message.reset_mock()

    await poll(monitor, client, ON_GRID)

    assert "снова на связи" in bot.send_message.await_args.args[1]


async def add_second_inverter(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session:
        account = (await repository.list_user_accounts(session, 1))[0]
        account.inverters.append(Inverter(serial="0000000002", model="LXP"))
        await session.commit()


async def test_unavailable_inverter_does_not_silence_the_others(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await add_second_inverter(sessions)
    down = InverterUnavailableError("gone")
    client.states_by_serial = {
        "0000000001": [down, down, down],
        "0000000002": [ON_GRID, OFF_GRID, OFF_GRID],
    }

    for _ in range(3):
        await monitor.poll_once()

    bot.send_message.assert_awaited_once()
    assert "···0002" in bot.send_message.await_args.args[1]


async def test_crash_in_one_inverter_does_not_escape_the_poll(
    monitor: InverterMonitor, client: FakeClient, bot: AsyncMock
) -> None:
    client.states.append(RuntimeError("boom"))

    await monitor.poll_once()

    bot.send_message.assert_not_called()


async def test_group_that_refuses_is_unlinked_and_owner_told(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await link_group(sessions, GROUP_ID)
    async with sessions() as session:
        inverter = (await repository.list_user_inverters(session, 1))[0]
        inverter.notifications_enabled = False
        await session.commit()
    refused = TelegramBadRequest(SendMessage(chat_id=GROUP_ID, text="x"), "chat not found")
    bot.send_message.side_effect = [refused, None]

    await poll(monitor, client, ON_GRID, OFF_GRID, OFF_GRID)

    assert "Family" in bot.send_message.await_args.args[1]
    assert bot.send_message.await_args.args[0] == 1
    async with sessions() as session:
        inverter = (await repository.list_user_inverters(session, 1))[0]
        assert inverter.group_chat_id is None
        assert inverter.grid_state is GridState.OFF_GRID
        assert await repository.open_outage_start(session, inverter.id) is not None


async def test_outage_record_and_grid_state_are_saved_together(
    monitor: InverterMonitor,
    client: FakeClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await poll(monitor, client, ON_GRID, OFF_GRID, OFF_GRID, OFF_GRID)

    async with sessions() as session:
        inverter = (await repository.list_user_inverters(session, 1))[0]
        outages = await repository.outages_since(
            session, inverter.id, datetime(2000, 1, 1, tzinfo=UTC)
        )
    assert len(outages) == 1
    assert inverter.grid_state is GridState.OFF_GRID


async def test_undecryptable_credentials_ask_the_user_to_reconnect(
    monitor: InverterMonitor,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        account = (await repository.list_user_accounts(session, 1))[0]
        account.encrypted_credentials = b"written with an old key"
        await session.commit()

    await monitor.poll_once()
    await monitor.poll_once()

    bot.send_message.assert_awaited_once()
    assert "пароль" in bot.send_message.await_args.args[1]
    async with sessions() as session:
        assert not await repository.list_monitored_accounts(session)


async def test_revoked_bot_token_does_not_unlink_groups(
    monitor: InverterMonitor,
    client: FakeClient,
    bot: AsyncMock,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await link_group(sessions, GROUP_ID)
    bot.send_message.side_effect = TelegramUnauthorizedError(
        SendMessage(chat_id=GROUP_ID, text="x"), "Unauthorized"
    )

    await poll(monitor, client, ON_GRID, OFF_GRID, OFF_GRID)

    async with sessions() as session:
        inverter = (await repository.list_user_inverters(session, 1))[0]
    assert inverter.group_chat_id == GROUP_ID
    assert inverter.grid_state is GridState.ON_GRID
