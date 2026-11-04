import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from volty.config import DatabaseSettings
from volty.storage.models import Base


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(DatabaseSettings().database_url.get_secret_value())
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


asyncio.run(_run_online())
