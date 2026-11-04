from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from volty.bot.formatting import battery_text, summary_text
from volty.bot.i18n import Translator
from volty.inverters.base import AuthenticationError, InverterUnavailableError
from volty.inverters.pool import ClientPool
from volty.storage.models import Inverter
from volty.storage.repository import outages_since

OUTAGE_WINDOW = timedelta(hours=24)


async def read_battery_text(inverter: Inverter, pool: ClientPool, t: Translator) -> str:
    try:
        client = await pool.get(inverter.account)
        state = await client.read_state(inverter.serial)
    except AuthenticationError, InverterUnavailableError:
        return t("battery.unavailable")
    if not state.online:
        return t("battery.offline", name=inverter.label)
    return battery_text(t, inverter, state)


async def read_summary_text(
    inverter: Inverter,
    sessions: async_sessionmaker[AsyncSession],
    pool: ClientPool,
    t: Translator,
) -> str | None:
    try:
        client = await pool.get(inverter.account)
        energy = await client.read_energy(inverter.serial)
    except AuthenticationError, InverterUnavailableError:
        return None
    now = datetime.now(UTC)
    window_start = now - OUTAGE_WINDOW
    async with sessions() as session:
        outages = await outages_since(session, inverter.id, window_start)
    total = sum(
        ((o.ended_at or now) - max(o.started_at, window_start) for o in outages),
        timedelta(),
    )
    return summary_text(t, inverter, energy, len(outages), total)
