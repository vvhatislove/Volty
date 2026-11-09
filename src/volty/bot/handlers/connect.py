import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from volty.bot import callbacks
from volty.bot.callbacks import BrandCallback, RegionCallback
from volty.bot.handlers.common import edit_callback_message
from volty.bot.i18n import Translator
from volty.bot.keyboards import (
    brand_keyboard,
    cancel_keyboard,
    connect_keyboard,
    region_keyboard,
)
from volty.crypto import CredentialCipher
from volty.inverters import Brand, brand_regions
from volty.inverters.base import AuthenticationError, Credentials, InverterUnavailableError
from volty.inverters.pool import ClientFactory
from volty.storage.models import User
from volty.storage.repository import save_account

logger = logging.getLogger(__name__)

router = Router()


class ConnectStates(StatesGroup):
    brand = State()
    region = State()
    login = State()
    password = State()


async def _delete_secret_message(message: Message, t: Translator) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        await message.answer(t("connect.delete_failed"))


async def _finish(status: Message, text: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    try:
        await status.edit_text(text, reply_markup=keyboard)
    except TelegramAPIError as error:
        logger.warning("Could not update the connect status: %s", type(error).__name__)


@router.callback_query(F.data == callbacks.CONNECT)
async def begin(callback: CallbackQuery, state: FSMContext, t: Translator) -> None:
    await state.set_state(ConnectStates.brand)
    await edit_callback_message(callback, t("connect.choose_brand"), brand_keyboard(t))


@router.callback_query(F.data == callbacks.CANCEL)
async def cancel(callback: CallbackQuery, state: FSMContext, t: Translator) -> None:
    await state.clear()
    await edit_callback_message(callback, t("connect.cancelled"))


@router.callback_query(ConnectStates.brand, BrandCallback.filter())
async def choose_brand(
    callback: CallbackQuery, callback_data: BrandCallback, state: FSMContext, t: Translator
) -> None:
    brand = callback_data.brand
    await state.set_state(ConnectStates.region)
    await edit_callback_message(
        callback, t(f"connect.choose_region.{brand}"), region_keyboard(t, brand)
    )


@router.callback_query(ConnectStates.region, RegionCallback.filter())
async def choose_region(
    callback: CallbackQuery, callback_data: RegionCallback, state: FSMContext, t: Translator
) -> None:
    brand = callback_data.brand
    if callback_data.region not in brand_regions(brand):
        await callback.answer()
        return
    # Every button press clears the state, so the brand travels in the region button itself.
    await state.update_data(brand=brand.value, region=callback_data.region)
    await state.set_state(ConnectStates.login)
    await edit_callback_message(
        callback, t("connect.ask_login", brand=t(f"brand.{brand}")), cancel_keyboard(t)
    )


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

    brand = Brand(data["brand"])
    brand_name = t(f"brand.{brand}")
    credentials = Credentials(login=data["login"], password=password)
    client = client_factory(brand, data["region"], credentials)
    try:
        inverters = await client.list_inverters()
    except AuthenticationError:
        await _finish(status, t("connect.bad_credentials", brand=brand_name), connect_keyboard(t))
        return
    except InverterUnavailableError:
        await _finish(status, t("connect.unavailable", brand=brand_name), connect_keyboard(t))
        return
    finally:
        await client.aclose()

    if not inverters:
        await _finish(status, t("connect.no_inverters", brand=brand_name))
        return
    await save_account(
        db,
        user.telegram_id,
        brand,
        data["region"],
        cipher.encrypt(credentials),
        inverters,
    )
    await db.commit()
    names = ", ".join(inverter.model for inverter in inverters)
    await _finish(status, t("connect.success", inverters=names))
