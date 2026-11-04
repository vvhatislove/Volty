import contextlib

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

NOT_MODIFIED = "message is not modified"


async def answer_callback(
    callback: CallbackQuery, text: str | None = None, *, alert: bool = False
) -> None:
    # Telegram refuses to answer a query that waited too long on a slow cloud request.
    with contextlib.suppress(TelegramBadRequest):
        await callback.answer(text, show_alert=alert)


async def edit_callback_message(
    callback: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
    unchanged_text: str | None = None,
) -> None:
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest as error:
            if NOT_MODIFIED in error.message:
                await answer_callback(callback, unchanged_text)
                return
            await callback.message.answer(text, reply_markup=keyboard)
    await answer_callback(callback)
