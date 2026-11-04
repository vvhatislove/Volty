import contextlib

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from volty.bot import callbacks
from volty.bot.callbacks import DisconnectCallback, LanguageCallback, RenameCallback
from volty.bot.handlers.common import edit_callback_message
from volty.bot.i18n import LANGUAGE_NAMES, Translator, all_translations
from volty.bot.keyboards import (
    cancel_keyboard,
    connect_keyboard,
    disconnect_confirm_keyboard,
    disconnect_list_keyboard,
    language_keyboard,
    main_keyboard,
    rename_choice_keyboard,
    settings_keyboard,
)
from volty.inverters.pool import ClientPool
from volty.storage.models import MAX_DISPLAY_NAME_LENGTH, Inverter, User
from volty.storage.repository import (
    delete_user_account,
    get_user_inverter,
    list_user_accounts,
    list_user_inverters,
)

router = Router()


class RenameStates(StatesGroup):
    name = State()


@router.message(F.text.in_(all_translations("menu.settings")))
async def show_settings(message: Message, state: FSMContext, t: Translator) -> None:
    await state.clear()
    await message.answer(t("settings.title"), reply_markup=settings_keyboard(t))


@router.callback_query(F.data == callbacks.LANGUAGES)
async def choose_language(callback: CallbackQuery, t: Translator) -> None:
    await edit_callback_message(callback, t("settings.language_choose"), language_keyboard())


@router.callback_query(LanguageCallback.filter())
async def save_language(
    callback: CallbackQuery, callback_data: LanguageCallback, user: User
) -> None:
    if callback_data.language not in LANGUAGE_NAMES:
        await callback.answer()
        return
    user.language = callback_data.language
    t = Translator(user.language)
    if isinstance(callback.message, Message):
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.delete()
        await callback.message.answer(t("settings.language_saved"), reply_markup=main_keyboard(t))
    await callback.answer()


async def _ask_new_name(
    callback: CallbackQuery, inverter: Inverter, state: FSMContext, t: Translator
) -> None:
    await state.set_state(RenameStates.name)
    await state.update_data(inverter_id=inverter.id)
    await edit_callback_message(callback, t("rename.ask", name=inverter.label), cancel_keyboard(t))


@router.callback_query(F.data == callbacks.RENAME_LIST)
async def choose_inverter_to_rename(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user: User, t: Translator
) -> None:
    inverters = await list_user_inverters(db, user.telegram_id)
    if not inverters:
        await edit_callback_message(callback, t("battery.none"), connect_keyboard(t))
    elif len(inverters) == 1:
        await _ask_new_name(callback, inverters[0], state, t)
    else:
        await edit_callback_message(
            callback, t("rename.choose"), rename_choice_keyboard(t, inverters)
        )


@router.callback_query(RenameCallback.filter())
async def start_rename(
    callback: CallbackQuery,
    callback_data: RenameCallback,
    state: FSMContext,
    db: AsyncSession,
    user: User,
    t: Translator,
) -> None:
    inverter = await get_user_inverter(db, user.telegram_id, callback_data.inverter_id)
    if inverter is None:
        await callback.answer(t("common.inverter_gone"))
        return
    await _ask_new_name(callback, inverter, state, t)


@router.message(RenameStates.name, F.text)
async def save_name(
    message: Message, state: FSMContext, db: AsyncSession, user: User, t: Translator
) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > MAX_DISPLAY_NAME_LENGTH:
        await message.answer(
            t("rename.invalid", limit=MAX_DISPLAY_NAME_LENGTH), reply_markup=cancel_keyboard(t)
        )
        return
    data = await state.get_data()
    await state.clear()
    inverter = await get_user_inverter(db, user.telegram_id, data["inverter_id"])
    if inverter is None:
        await message.answer(t("common.inverter_gone"))
        return
    inverter.display_name = name
    await message.answer(t("rename.done", name=name))


@router.callback_query(F.data == callbacks.DISCONNECT_LIST)
async def choose_account(
    callback: CallbackQuery, db: AsyncSession, user: User, t: Translator
) -> None:
    accounts = await list_user_accounts(db, user.telegram_id)
    if not accounts:
        await edit_callback_message(callback, t("disconnect.none"))
        return
    await edit_callback_message(
        callback, t("disconnect.choose"), disconnect_list_keyboard(t, accounts)
    )


@router.callback_query(DisconnectCallback.filter(F.confirmed.is_(False)))
async def confirm_disconnect(
    callback: CallbackQuery, callback_data: DisconnectCallback, t: Translator
) -> None:
    await edit_callback_message(
        callback,
        t("disconnect.confirm"),
        disconnect_confirm_keyboard(t, callback_data.account_id),
    )


@router.callback_query(DisconnectCallback.filter(F.confirmed.is_(True)))
async def disconnect(
    callback: CallbackQuery,
    callback_data: DisconnectCallback,
    db: AsyncSession,
    user: User,
    t: Translator,
    pool: ClientPool,
) -> None:
    if await delete_user_account(db, user.telegram_id, callback_data.account_id):
        await pool.discard(callback_data.account_id)
    await edit_callback_message(callback, t("disconnect.done"))
