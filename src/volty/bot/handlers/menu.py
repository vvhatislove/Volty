import contextlib

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from volty.bot.i18n import Translator
from volty.bot.keyboards import connect_keyboard, main_keyboard
from volty.storage.models import User
from volty.storage.repository import list_user_inverters

router = Router()
fallback_router = Router()


@router.message(CommandStart())
async def start(
    message: Message, state: FSMContext, db: AsyncSession, user: User, t: Translator
) -> None:
    await state.clear()
    if await list_user_inverters(db, user.telegram_id):
        await message.answer(t("start.ready"), reply_markup=main_keyboard(t))
        return
    await message.answer(t("start.welcome"), reply_markup=main_keyboard(t))
    await message.answer(t("battery.none"), reply_markup=connect_keyboard(t))


@fallback_router.message(F.text)
async def restore_keyboard(message: Message, state: FSMContext, t: Translator) -> None:
    await state.clear()
    # The bot only uses buttons, so stray text may be a password sent after a restart lost the
    # connect flow's state.
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()
    await message.answer(t("start.ready"), reply_markup=main_keyboard(t))


@fallback_router.callback_query()
async def expire_stale_button(callback: CallbackQuery) -> None:
    await callback.answer()
