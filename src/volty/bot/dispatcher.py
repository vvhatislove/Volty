from aiogram import Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from volty.bot.handlers import (
    battery,
    connect,
    groups,
    low_charge,
    menu,
    notifications,
    settings,
    summary,
)
from volty.bot.middleware import ContextMiddleware
from volty.crypto import CredentialCipher
from volty.inverters import create_client
from volty.inverters.pool import ClientFactory, ClientPool


def build_dispatcher(
    sessions: async_sessionmaker[AsyncSession],
    pool: ClientPool,
    cipher: CredentialCipher,
    client_factory: ClientFactory = create_client,
) -> Dispatcher:
    dispatcher = Dispatcher(
        storage=MemoryStorage(),
        pool=pool,
        cipher=cipher,
        client_factory=client_factory,
        sessions=sessions,
        cooldown=groups.ViewCooldown(),
    )
    # Credentials are entered as messages, so everything except posting alerts stays private.
    private = Router()
    private.message.filter(F.chat.type == ChatType.PRIVATE)
    private.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
    # Inner middleware only runs for handled private events, so group members never become users.
    middleware = ContextMiddleware(sessions)
    private.message.middleware(middleware)
    private.callback_query.middleware(middleware)
    # Menu routers go before the connect flow so a menu button is never read as a login.
    private.include_routers(
        menu.router,
        battery.router,
        summary.router,
        notifications.router,
        settings.router,
        low_charge.router,
        connect.router,
        menu.fallback_router,
    )
    dispatcher.include_routers(private, groups.router)
    return dispatcher
