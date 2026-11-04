from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from volty.bot.callbacks import BatteryAction, BatteryCallback
from volty.bot.formatting import battery_text
from volty.bot.i18n import Translator, all_translations
from volty.bot.keyboards import (
    battery_choice_keyboard,
    battery_refresh_keyboard,
    connect_keyboard,
)
from volty.inverters.base import AuthenticationError, InverterUnavailableError
from volty.inverters.pool import ClientPool
from volty.storage.models import Inverter, User
from volty.storage.repository import get_user_inverter, list_user_inverters

router = Router()


async def _render(
    inverter: Inverter, pool: ClientPool, t: Translator
) -> tuple[str, InlineKeyboardMarkup]:
    if inverter.account.needs_reauth:
        return t("error.reauth"), connect_keyboard(t)
    refresh = battery_refresh_keyboard(t, inverter.id)
    client = await pool.get(inverter.account)
    try:
        state = await client.read_state(inverter.serial)
    except AuthenticationError, InverterUnavailableError:
        return t("battery.unavailable"), refresh
    if not state.online:
        return t("battery.offline", name=inverter.label), refresh
    return battery_text(t, inverter, state), refresh


@router.message(F.text.in_(all_translations("menu.battery")))
async def show_battery(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user: User,
    t: Translator,
    pool: ClientPool,
) -> None:
    await state.clear()
    inverters = await list_user_inverters(db, user.telegram_id)
    if not inverters:
        await message.answer(t("battery.none"), reply_markup=connect_keyboard(t))
    elif len(inverters) > 1:
        await message.answer(t("battery.choose"), reply_markup=battery_choice_keyboard(inverters))
    else:
        text, keyboard = await _render(inverters[0], pool, t)
        await message.answer(text, reply_markup=keyboard)


@router.callback_query(BatteryCallback.filter())
async def battery_button(
    callback: CallbackQuery,
    callback_data: BatteryCallback,
    bot: Bot,
    db: AsyncSession,
    user: User,
    t: Translator,
    pool: ClientPool,
) -> None:
    inverter = await get_user_inverter(db, user.telegram_id, callback_data.inverter_id)
    if inverter is None:
        await callback.answer()
        return
    text, keyboard = await _render(inverter, pool, t)
    if callback_data.action is BatteryAction.OPEN or not isinstance(callback.message, Message):
        # Opening from an alert sends a new message so the alert stays in the chat history.
        await bot.send_message(user.telegram_id, text, reply_markup=keyboard)
        await callback.answer()
        return
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as error:
        if "message is not modified" not in error.message:
            raise
        await callback.answer(t("battery.up_to_date"))
        return
    await callback.answer()
