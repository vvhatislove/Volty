from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from volty.bot import callbacks
from volty.bot.callbacks import (
    LowChargeCallback,
    LowChargeThresholdCallback,
    VoltageScaleCallback,
)
from volty.bot.handlers.common import edit_callback_message
from volty.bot.i18n import Translator
from volty.bot.keyboards import (
    LOW_CHARGE_THRESHOLDS,
    cancel_keyboard,
    connect_keyboard,
    low_charge_choice_keyboard,
    low_charge_keyboard,
)
from volty.storage.models import Inverter, User
from volty.storage.repository import get_user_inverter, list_user_inverters

router = Router()

MAX_VOLTAGE = 1000.0


class ScaleStates(StatesGroup):
    full = State()
    empty = State()


def _parse_voltage(text: str | None) -> float | None:
    try:
        voltage = float((text or "").strip().replace(",", "."))
    except ValueError:
        return None
    return voltage if 0 < voltage <= MAX_VOLTAGE else None


def _screen(t: Translator, inverter: Inverter) -> tuple[str, InlineKeyboardMarkup]:
    scale = inverter.battery_scale
    keyboard = low_charge_keyboard(t, inverter)
    if scale is None:
        return t("low_charge.no_scale", name=inverter.label), keyboard
    threshold = (
        t("low_charge.off")
        if inverter.low_charge_percent is None
        else f"{inverter.low_charge_percent}%"
    )
    text = t(
        "low_charge.screen",
        name=inverter.label,
        full=f"{scale.full_voltage:.1f}",
        empty=f"{scale.empty_voltage:.1f}",
        threshold=threshold,
    )
    return text, keyboard


def _reset_tracker(inverter: Inverter) -> None:
    inverter.low_charge_alerted = False
    inverter.low_charge_pending = False


@router.callback_query(F.data == callbacks.LOW_CHARGE_LIST)
async def open_low_charge(
    callback: CallbackQuery, db: AsyncSession, user: User, t: Translator
) -> None:
    inverters = await list_user_inverters(db, user.telegram_id)
    if not inverters:
        await edit_callback_message(callback, t("battery.none"), connect_keyboard(t))
    elif len(inverters) == 1:
        await edit_callback_message(callback, *_screen(t, inverters[0]))
    else:
        await edit_callback_message(
            callback, t("battery.choose"), low_charge_choice_keyboard(inverters)
        )


@router.callback_query(LowChargeCallback.filter())
async def open_inverter_low_charge(
    callback: CallbackQuery,
    callback_data: LowChargeCallback,
    db: AsyncSession,
    user: User,
    t: Translator,
) -> None:
    inverter = await get_user_inverter(db, user.telegram_id, callback_data.inverter_id)
    if inverter is None:
        await callback.answer(t("common.inverter_gone"))
        return
    await edit_callback_message(callback, *_screen(t, inverter))


@router.callback_query(LowChargeThresholdCallback.filter())
async def set_threshold(
    callback: CallbackQuery,
    callback_data: LowChargeThresholdCallback,
    db: AsyncSession,
    user: User,
    t: Translator,
) -> None:
    inverter = await get_user_inverter(db, user.telegram_id, callback_data.inverter_id)
    valid = callback_data.percent in {0, *LOW_CHARGE_THRESHOLDS}
    if inverter is None or not valid or inverter.battery_scale is None:
        await callback.answer()
        return
    inverter.low_charge_percent = callback_data.percent or None
    _reset_tracker(inverter)
    await db.flush()
    await edit_callback_message(callback, *_screen(t, inverter))


@router.callback_query(VoltageScaleCallback.filter())
async def ask_full_voltage(
    callback: CallbackQuery,
    callback_data: VoltageScaleCallback,
    state: FSMContext,
    db: AsyncSession,
    user: User,
    t: Translator,
) -> None:
    inverter = await get_user_inverter(db, user.telegram_id, callback_data.inverter_id)
    if inverter is None:
        await callback.answer(t("common.inverter_gone"))
        return
    await state.set_state(ScaleStates.full)
    await state.update_data(inverter_id=inverter.id)
    await edit_callback_message(callback, t("low_charge.ask_full"), cancel_keyboard(t))


@router.message(ScaleStates.full, F.text)
async def receive_full_voltage(message: Message, state: FSMContext, t: Translator) -> None:
    voltage = _parse_voltage(message.text)
    if voltage is None:
        await message.answer(t("low_charge.invalid"), reply_markup=cancel_keyboard(t))
        return
    await state.update_data(full_voltage=voltage)
    await state.set_state(ScaleStates.empty)
    await message.answer(t("low_charge.ask_empty"), reply_markup=cancel_keyboard(t))


@router.message(ScaleStates.empty, F.text)
async def receive_empty_voltage(
    message: Message, state: FSMContext, db: AsyncSession, user: User, t: Translator
) -> None:
    voltage = _parse_voltage(message.text)
    data = await state.get_data()
    if voltage is None or voltage >= data["full_voltage"]:
        await message.answer(t("low_charge.invalid_empty"), reply_markup=cancel_keyboard(t))
        return
    await state.clear()
    inverter = await get_user_inverter(db, user.telegram_id, data["inverter_id"])
    if inverter is None:
        await message.answer(t("common.inverter_gone"))
        return
    inverter.battery_full_voltage = data["full_voltage"]
    inverter.battery_empty_voltage = voltage
    _reset_tracker(inverter)
    text, keyboard = _screen(t, inverter)
    await message.answer(text, reply_markup=keyboard)
