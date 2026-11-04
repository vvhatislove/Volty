from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from volty.inverters import Brand
from volty.inverters.base import InverterInfo
from volty.monitoring.grid import GridTracker
from volty.storage.models import Account, Inverter, User


async def get_or_create_user(session: AsyncSession, telegram_id: int, language: str) -> User:
    user = await session.get(User, telegram_id)
    if user is None:
        user = User(telegram_id=telegram_id, language=language)
        session.add(user)
        await session.flush()
    return user


async def save_account(
    session: AsyncSession,
    user_id: int,
    brand: Brand,
    region: str,
    encrypted_credentials: bytes,
    inverters: Sequence[InverterInfo],
) -> Account:
    """Reconnecting a known account keeps each inverter's settings and grid state."""
    serials = {inverter.serial for inverter in inverters}
    accounts = await session.scalars(
        select(Account)
        .where(Account.user_id == user_id, Account.brand == brand, Account.region == region)
        .options(selectinload(Account.inverters))
    )
    account = next(
        (a for a in accounts if serials & {inverter.serial for inverter in a.inverters}),
        None,
    )
    if account is None:
        account = Account(user_id=user_id, brand=brand, region=region, inverters=[])
        session.add(account)
    account.encrypted_credentials = encrypted_credentials
    account.needs_reauth = False

    account.inverters[:] = [i for i in account.inverters if i.serial in serials]
    known = {inverter.serial: inverter for inverter in account.inverters}
    for info in inverters:
        if info.serial in known:
            known[info.serial].model = info.model
        else:
            account.inverters.append(Inverter(serial=info.serial, model=info.model))
    await session.flush()
    return account


async def list_user_inverters(session: AsyncSession, user_id: int) -> Sequence[Inverter]:
    result = await session.scalars(
        select(Inverter)
        .join(Account)
        .where(Account.user_id == user_id)
        .options(selectinload(Inverter.account))
        .order_by(Inverter.id)
    )
    return result.all()


async def get_user_inverter(
    session: AsyncSession, user_id: int, inverter_id: int
) -> Inverter | None:
    return await session.scalar(
        select(Inverter)
        .join(Account)
        .where(Inverter.id == inverter_id, Account.user_id == user_id)
        .options(selectinload(Inverter.account))
    )


async def list_user_accounts(session: AsyncSession, user_id: int) -> Sequence[Account]:
    result = await session.scalars(
        select(Account)
        .where(Account.user_id == user_id)
        .options(selectinload(Account.inverters))
        .order_by(Account.id)
    )
    return result.all()


async def delete_user_account(session: AsyncSession, user_id: int, account_id: int) -> bool:
    account = await session.scalar(
        select(Account).where(Account.id == account_id, Account.user_id == user_id)
    )
    if account is None:
        return False
    await session.delete(account)
    return True


async def list_monitored_accounts(session: AsyncSession) -> Sequence[Account]:
    result = await session.scalars(
        select(Account)
        .where(Account.needs_reauth.is_(False))
        .options(selectinload(Account.inverters), selectinload(Account.user))
    )
    return result.all()


async def mark_needs_reauth(session: AsyncSession, account_id: int) -> None:
    account = await session.get(Account, account_id)
    if account is not None:
        account.needs_reauth = True


async def save_grid_tracker(session: AsyncSession, inverter_id: int, tracker: GridTracker) -> None:
    inverter = await session.get(Inverter, inverter_id)
    if inverter is not None:
        inverter.grid_state = tracker.confirmed
        inverter.pending_grid_state = tracker.pending


async def clear_group(session: AsyncSession, chat_id: int) -> None:
    await session.execute(
        update(Inverter)
        .where(Inverter.group_chat_id == chat_id)
        .values(group_chat_id=None, group_chat_title=None)
    )


async def move_group(session: AsyncSession, chat_id: int, new_chat_id: int) -> None:
    await session.execute(
        update(Inverter).where(Inverter.group_chat_id == chat_id).values(group_chat_id=new_chat_id)
    )
