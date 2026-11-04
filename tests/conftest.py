import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from volty.crypto import CredentialCipher
from volty.inverters.base import InverterInfo, InverterState
from volty.storage.models import Base

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return payload


class FakeClient:
    def __init__(self) -> None:
        self.inverters: list[InverterInfo] = []
        self.states: list[InverterState | Exception] = []
        self.closed = False

    async def list_inverters(self) -> list[InverterInfo]:
        return self.inverters

    async def read_state(self, serial: str) -> InverterState:
        result = self.states.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def cipher() -> CredentialCipher:
    return CredentialCipher(Fernet.generate_key().decode())
