import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from volty.crypto import CredentialCipher
from volty.inverters.base import EnergySummary, InverterInfo, InverterState
from volty.storage.models import Base

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return payload


class FakeClient:
    def __init__(self) -> None:
        self.inverters: list[InverterInfo] = []
        self.states: list[InverterState | Exception] = []
        self.states_by_serial: dict[str, list[InverterState | Exception]] = {}
        self.energy = EnergySummary(5.2, 3.1, 2.4, 7.0, 1.2, 0.0)
        self.closed = False

    async def list_inverters(self) -> list[InverterInfo]:
        return self.inverters

    async def read_state(self, serial: str) -> InverterState:
        result = (
            self.states_by_serial[serial].pop(0) if self.states_by_serial else self.states.pop(0)
        )
        if isinstance(result, Exception):
            raise result
        return result

    async def read_energy(self, serial: str) -> EnergySummary:
        return self.energy

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(
        engine.sync_engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def cipher() -> CredentialCipher:
    return CredentialCipher(Fernet.generate_key().decode())
