from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from volty.bot import callbacks
from volty.bot.callbacks import RegionCallback
from volty.bot.handlers.common import edit_callback_message
from volty.bot.i18n import Translator
from volty.bot.keyboards import cancel_keyboard, connect_keyboard, region_keyboard
from volty.crypto import CredentialCipher
from volty.inverters import Brand, brand_regions
from volty.inverters.base import AuthenticationError, Credentials, InverterUnavailableError
from volty.inverters.pool import ClientFactory
from volty.storage.models import User
from volty.storage.repository import save_account

router = Router()


class ConnectStates(StatesGroup):
    region = State()
    login = State()
    password = State()


async def _delete_secret_message(message: Message, t: Translator) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        await message.answer(t("connect.delete_failed"))


@router.callback_query(F.data == callbacks.CONNECT)
async def begin(callback: CallbackQuery, state: FSMContext, t: Translator) -> None:
    await state.set_state(ConnectStates.region)
    await edit_callback_message(
        callback,
        t("connect.choose_region"),
        region_keyboard(t, brand_regions(Brand.LUXPOWER)),
    )


@router.callback_query(F.data == callbacks.CANCEL)
async def cancel(callback: CallbackQuery, state: FSMContext, t: Translator) -> None:
    await state.clear()
    await edit_callback_message(callback, t("connect.cancelled"))


@router.callback_query(ConnectStates.region, RegionCallback.filter())
async def choose_region(
    callback: CallbackQuery, callback_data: RegionCallback, state: FSMContext, t: Translator
) -> None:
    if callback_data.region not in brand_regions(Brand.LUXPOWER):
        await callback.answer()
        return
    await state.update_data(region=callback_data.region)
    await state.set_state(ConnectStates.login)
    await edit_callback_message(callback, t("connect.ask_login"), cancel_keyboard(t))


@router.message(ConnectStates.login, F.text)
async def receive_login(message: Message, state: FSMContext, t: Translator) -> None:
    await state.update_data(login=message.text)
    await state.set_state(ConnectStates.password)
    await _delete_secret_message(message, t)
    await message.answer(t("connect.ask_password"), reply_markup=cancel_keyboard(t))


@router.message(ConnectStates.password, F.text)
async def receive_password(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user: User,
    t: Translator,
    cipher: CredentialCipher,
    client_factory: ClientFactory,
) -> None:
    password = message.text or ""
    data = await state.get_data()
    await state.clear()
    await _delete_secret_message(message, t)
    status = await message.answer(t("connect.checking"))

    credentials = Credentials(login=data["login"], password=password)
    client = client_factory(Brand.LUXPOWER, data["region"], credentials)
    try:
        inverters = await client.list_inverters()
    except AuthenticationError:
        await status.edit_text(t("connect.bad_credentials"), reply_markup=connect_keyboard(t))
        return
    except InverterUnavailableError:
        await status.edit_text(t("connect.unavailable"), reply_markup=connect_keyboard(t))
        return
    finally:
        await client.aclose()

    if not inverters:
        await status.edit_text(t("connect.no_inverters"))
        return
    await save_account(
        db,
        user.telegram_id,
        Brand.LUXPOWER,
        data["region"],
        cipher.encrypt(credentials),
        inverters,
    )
    names = ", ".join(inverter.model for inverter in inverters)
    await status.edit_text(t("connect.success", inverters=names))
