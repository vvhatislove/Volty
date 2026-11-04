from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


async def edit_callback_message(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None = None
) -> None:
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()
