from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from volty.bot.callbacks import SummaryAction, SummaryCallback
from volty.bot.handlers.common import answer_callback, edit_callback_message
from volty.bot.i18n import Translator, all_translations
from volty.bot.keyboards import (
    connect_keyboard,
    group_view_keyboard,
    summary_choice_keyboard,
    summary_keyboard,
)
from volty.bot.views import read_summary_text
from volty.inverters.pool import ClientPool
from volty.storage.models import Inverter, User
from volty.storage.repository import get_user_inverter, list_user_inverters

router = Router()


async def _render(
    inverter: Inverter,
    sessions: async_sessionmaker[AsyncSession],
    pool: ClientPool,
    t: Translator,
) -> tuple[str, InlineKeyboardMarkup]:
    if inverter.account.needs_reauth:
        return t("error.reauth"), connect_keyboard(t)
    text = await read_summary_text(inverter, sessions, pool, t)
    return text or t("battery.unavailable"), summary_keyboard(t, inverter)


@router.message(F.text.in_(all_translations("menu.summary")))
async def show_summary(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
    user: User,
    t: Translator,
    pool: ClientPool,
) -> None:
    await state.clear()
    inverters = await list_user_inverters(db, user.telegram_id)
    if not inverters:
        await message.answer(t("battery.none"), reply_markup=connect_keyboard(t))
    elif len(inverters) > 1:
        await message.answer(t("battery.choose"), reply_markup=summary_choice_keyboard(inverters))
    else:
        text, keyboard = await _render(inverters[0], sessions, pool, t)
        await message.answer(text, reply_markup=keyboard)


@router.callback_query(SummaryCallback.filter(F.action == SummaryAction.SEND_TO_GROUP))
async def send_to_group(
    callback: CallbackQuery,
    callback_data: SummaryCallback,
    bot: Bot,
    db: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
    user: User,
    t: Translator,
    pool: ClientPool,
) -> None:
    inverter = await get_user_inverter(db, user.telegram_id, callback_data.inverter_id)
    if inverter is None or inverter.group_chat_id is None:
        await answer_callback(callback, t("common.inverter_gone"))
        return
    text = await read_summary_text(inverter, sessions, pool, t)
    if text is None:
        await answer_callback(callback, t("battery.unavailable"), alert=True)
        return
    try:
        keyboard = group_view_keyboard(t, [inverter])
        await bot.send_message(inverter.group_chat_id, text, reply_markup=keyboard)
    except TelegramAPIError:
        await answer_callback(callback, t("summary.group_failed"), alert=True)
        return
    await answer_callback(callback, t("summary.group_sent"))


@router.callback_query(SummaryCallback.filter())
async def summary_button(
    callback: CallbackQuery,
    callback_data: SummaryCallback,
    bot: Bot,
    db: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
    user: User,
    t: Translator,
    pool: ClientPool,
) -> None:
    inverter = await get_user_inverter(db, user.telegram_id, callback_data.inverter_id)
    if inverter is None:
        await answer_callback(callback, t("common.inverter_gone"))
        return
    text, keyboard = await _render(inverter, sessions, pool, t)
    if callback_data.action is SummaryAction.OPEN:
        await bot.send_message(user.telegram_id, text, reply_markup=keyboard)
        await answer_callback(callback)
        return
    await edit_callback_message(callback, text, keyboard, t("battery.up_to_date"))
