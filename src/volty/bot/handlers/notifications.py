from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from volty.bot.callbacks import ToggleNotificationsCallback, UnlinkGroupCallback
from volty.bot.handlers.common import edit_callback_message
from volty.bot.i18n import Translator, all_translations
from volty.bot.keyboards import connect_keyboard, notifications_keyboard
from volty.storage.models import User
from volty.storage.repository import get_user_inverter, list_user_inverters

router = Router()


async def _keyboard(bot: Bot, db: AsyncSession, user: User, t: Translator) -> InlineKeyboardMarkup:
    inverters = await list_user_inverters(db, user.telegram_id)
    me = await bot.me()
    return notifications_keyboard(t, inverters, me.username or "")


@router.message(F.text.in_(all_translations("menu.notifications")))
async def show_notifications(
    message: Message, state: FSMContext, bot: Bot, db: AsyncSession, user: User, t: Translator
) -> None:
    await state.clear()
    if not await list_user_inverters(db, user.telegram_id):
        await message.answer(t("battery.none"), reply_markup=connect_keyboard(t))
        return
    await message.answer(t("notifications.title"), reply_markup=await _keyboard(bot, db, user, t))


@router.callback_query(ToggleNotificationsCallback.filter())
async def toggle_notifications(
    callback: CallbackQuery,
    callback_data: ToggleNotificationsCallback,
    bot: Bot,
    db: AsyncSession,
    user: User,
    t: Translator,
) -> None:
    inverter = await get_user_inverter(db, user.telegram_id, callback_data.inverter_id)
    if inverter is None:
        await callback.answer()
        return
    inverter.notifications_enabled = not inverter.notifications_enabled
    await db.flush()
    await edit_callback_message(
        callback, t("notifications.title"), await _keyboard(bot, db, user, t)
    )


@router.callback_query(UnlinkGroupCallback.filter())
async def unlink_group(
    callback: CallbackQuery,
    callback_data: UnlinkGroupCallback,
    bot: Bot,
    db: AsyncSession,
    user: User,
    t: Translator,
) -> None:
    inverter = await get_user_inverter(db, user.telegram_id, callback_data.inverter_id)
    if inverter is None:
        await callback.answer()
        return
    inverter.group_chat_id = None
    inverter.group_chat_title = None
    await db.flush()
    await edit_callback_message(
        callback, t("notifications.title"), await _keyboard(bot, db, user, t)
    )
