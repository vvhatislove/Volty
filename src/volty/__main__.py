import asyncio
import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from volty.bot.dispatcher import build_dispatcher
from volty.config import Settings
from volty.crypto import CredentialCipher
from volty.inverters.pool import ClientPool
from volty.monitoring.monitor import GridMonitor


async def run(settings: Settings) -> None:
    engine = create_async_engine(settings.database_url.get_secret_value())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    cipher = CredentialCipher(settings.encryption_key.get_secret_value())
    pool = ClientPool(cipher)
    bot = Bot(settings.bot_token.get_secret_value())
    dispatcher = build_dispatcher(sessions, pool, cipher)
    monitor = GridMonitor(bot, sessions, pool, settings.poll_interval_seconds)

    monitor_task = asyncio.create_task(monitor.run())
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        monitor_task.cancel()
        await pool.aclose()
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    settings = Settings()
    logging.basicConfig(level=logging.INFO)
    # Only Volty's own logger follows LOG_LEVEL: httpcore logs session cookies at DEBUG.
    logging.getLogger("volty").setLevel(settings.log_level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
