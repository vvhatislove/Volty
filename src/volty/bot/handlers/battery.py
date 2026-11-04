from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from volty.bot.callbacks import BatteryAction, BatteryCallback
from volty.bot.handlers.common import answer_callback, edit_callback_message
from volty.bot.i18n import Translator, all_translations
from volty.bot.keyboards import (
    battery_choice_keyboard,
    battery_refresh_keyboard,
    connect_keyboard,
)
from volty.bot.views import read_battery_text
from volty.inverters.pool import ClientPool
from volty.storage.models import Inverter, User
from volty.storage.repository import get_user_inverter, list_user_inverters

router = Router()


async def _render(
    inverter: Inverter, pool: ClientPool, t: Translator
) -> tuple[str, InlineKeyboardMarkup]:
    if inverter.account.needs_reauth:
        return t("error.reauth"), connect_keyboard(t)
    return await read_battery_text(inverter, pool, t), battery_refresh_keyboard(t, inverter.id)


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
        await answer_callback(callback, t("common.inverter_gone"))
        return
    text, keyboard = await _render(inverter, pool, t)
    if callback_data.action is BatteryAction.OPEN:
        # Opening from an alert sends a new message so the alert stays in the chat history.
        await bot.send_message(user.telegram_id, text, reply_markup=keyboard)
        await answer_callback(callback)
        return
    await edit_callback_message(callback, text, keyboard, t("battery.up_to_date"))
