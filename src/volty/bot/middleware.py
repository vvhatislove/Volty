from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from volty.bot.i18n import Translator, resolve_language
from volty.storage.repository import get_or_create_user


class ContextMiddleware(BaseMiddleware):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user: TelegramUser | None = data.get("event_from_user")
        if telegram_user is None:
            return None
        async with self._sessions() as session:
            user = await get_or_create_user(
                session, telegram_user.id, resolve_language(telegram_user.language_code)
            )
            data["db"] = session
            data["user"] = user
            data["t"] = Translator(user.language)
            result = await handler(event, data)
            await session.commit()
            return result
