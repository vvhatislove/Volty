from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from volty.inverters import Brand
from volty.inverters.base import GridState, InverterInfo
from volty.storage import repository


async def test_reconnecting_updates_credentials_and_keeps_inverter_settings(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    info = InverterInfo(serial="0000000001", model="LXP")
    async with sessions() as session:
        await repository.get_or_create_user(session, 1, "en")
        account = await repository.save_account(session, 1, Brand.LUXPOWER, "eu", b"old", [info])
        account.needs_reauth = True
        account.inverters[0].notifications_enabled = False
        account.inverters[0].grid_state = GridState.OFF_GRID
        await session.commit()

    async with sessions() as session:
        again = await repository.save_account(session, 1, Brand.LUXPOWER, "eu", b"new", [info])
        await session.commit()

    async with sessions() as session:
        accounts = await repository.list_user_accounts(session, 1)
    assert [a.id for a in accounts] == [again.id]
    assert accounts[0].encrypted_credentials == b"new"
    assert not accounts[0].needs_reauth
    assert not accounts[0].inverters[0].notifications_enabled
    assert accounts[0].inverters[0].grid_state is GridState.OFF_GRID


async def test_users_cannot_reach_each_others_inverters_or_accounts(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    info = InverterInfo(serial="0000000001", model="LXP")
    async with sessions() as session:
        await repository.get_or_create_user(session, 1, "en")
        await repository.get_or_create_user(session, 2, "en")
        account = await repository.save_account(session, 1, Brand.LUXPOWER, "eu", b"key", [info])
        await session.commit()
        inverter_id = account.inverters[0].id
        account_id = account.id

    async with sessions() as session:
        assert await repository.get_user_inverter(session, 2, inverter_id) is None
        assert not await repository.delete_user_account(session, 2, account_id)
        assert await repository.get_user_inverter(session, 1, inverter_id) is not None
