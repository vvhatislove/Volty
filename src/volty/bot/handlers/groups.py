import logging
import time
from collections.abc import Sequence

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import LEAVE_TRANSITION, ChatMemberUpdatedFilter, CommandObject, CommandStart
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from volty.bot.callbacks import GroupView, GroupViewCallback
from volty.bot.handlers.common import answer_callback, edit_callback_message
from volty.bot.i18n import DEFAULT_LANGUAGE, Translator
from volty.bot.keyboards import group_view_keyboard
from volty.bot.views import read_battery_text, read_summary_text
from volty.inverters.pool import ClientPool
from volty.storage.models import Inverter, User
from volty.storage.repository import (
    clear_group,
    get_group_inverter,
    get_user_inverter,
    list_group_inverters,
)

logger = logging.getLogger(__name__)

router = Router()
GROUP_CHATS = {ChatType.GROUP, ChatType.SUPERGROUP}
router.message.filter(F.chat.type.in_(GROUP_CHATS))
router.callback_query.filter(F.message.chat.type.in_(GROUP_CHATS))


class ViewCooldown:
    """Every member can press these buttons, and each press uses the owner's cloud account."""

    SECONDS = 30

    def __init__(self) -> None:
        self._last_shown: dict[tuple[int, GroupView], float] = {}

    def seconds_left(self, inverter_id: int, view: GroupView) -> int:
        elapsed = time.monotonic() - self._last_shown.get((inverter_id, view), -self.SECONDS)
        return max(0, round(self.SECONDS - elapsed))

    def mark_shown(self, inverter_id: int, view: GroupView) -> None:
        self._last_shown[(inverter_id, view)] = time.monotonic()


def _owner_translator(inverters: Sequence[Inverter]) -> Translator:
    language = inverters[0].account.user.language if inverters else DEFAULT_LANGUAGE
    return Translator(language)


@router.message(CommandStart(deep_link=True))
async def link_group(
    message: Message,
    command: CommandObject,
    bot: Bot,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Anyone in a group can type this command, so only the inverter's owner may link it.
    args = command.args or ""
    if message.from_user is None or not args.isdecimal():
        return
    owner_id = message.from_user.id
    async with sessions() as session:
        owner = await session.get(User, owner_id)
        inverter = await get_user_inverter(session, owner_id, int(args))
        if owner is None or inverter is None:
            return
        t = Translator(owner.language)
        title = message.chat.title or ""
        try:
            await message.answer(
                t("group.linked", name=inverter.label),
                reply_markup=group_view_keyboard(t, [inverter]),
            )
        except TelegramAPIError as error:
            logger.warning("Could not post to group %s: %s", message.chat.id, type(error).__name__)
            await bot.send_message(owner_id, t("group.cannot_post", title=title))
            return
        inverter.group_chat_id = message.chat.id
        inverter.group_chat_title = title
        await session.commit()


@router.message(CommandStart())
async def show_panel(message: Message, sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session:
        inverters = await list_group_inverters(session, message.chat.id)
    if inverters:
        t = _owner_translator(inverters)
        await message.answer(t("group.panel"), reply_markup=group_view_keyboard(t, inverters))


@router.callback_query(GroupViewCallback.filter())
async def show_view(
    callback: CallbackQuery,
    callback_data: GroupViewCallback,
    bot: Bot,
    sessions: async_sessionmaker[AsyncSession],
    pool: ClientPool,
    cooldown: ViewCooldown,
) -> None:
    assert callback.message is not None
    chat_id = callback.message.chat.id
    inverter_id = callback_data.inverter_id
    view = callback_data.view
    async with sessions() as session:
        # The button only works in the group the owner linked, whoever presses it.
        inverter = await get_group_inverter(session, chat_id, inverter_id)
        if inverter is None:
            await answer_callback(callback, Translator(DEFAULT_LANGUAGE)("common.inverter_gone"))
            return
        t = Translator(inverter.account.user.language)
        seconds = cooldown.seconds_left(inverter_id, view)
        if seconds:
            await answer_callback(callback, t("group.cooldown", seconds=seconds))
            return
        cooldown.mark_shown(inverter_id, view)
    if view is GroupView.BATTERY:
        text = await read_battery_text(inverter, pool, t)
    else:
        text = await read_summary_text(inverter, sessions, pool, t) or t("battery.unavailable")
    keyboard = group_view_keyboard(t, [inverter], edit=True)
    if callback_data.edit:
        await edit_callback_message(callback, text, keyboard)
        return
    # An alert must stay readable, so pressing its button posts a new message instead.
    try:
        await bot.send_message(chat_id, text, reply_markup=keyboard)
    except TelegramAPIError as error:
        logger.warning("Could not post to group %s: %s", chat_id, type(error).__name__)
    await answer_callback(callback)


@router.callback_query()
async def expire_stale_button(callback: CallbackQuery) -> None:
    await answer_callback(callback)


@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION))
async def forget_group(
    event: ChatMemberUpdated, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with sessions() as session:
        await clear_group(session, event.chat.id)
        await session.commit()
