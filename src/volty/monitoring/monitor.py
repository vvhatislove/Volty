import asyncio
import logging
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramConflictError,
    TelegramMigrateToChat,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from volty.bot.formatting import connection_text, grid_change_text, low_charge_text
from volty.bot.i18n import Translator
from volty.bot.keyboards import (
    battery_shortcut_keyboard,
    connect_keyboard,
    group_view_keyboard,
)
from volty.inverters.base import (
    AuthenticationError,
    GridState,
    InverterState,
    InverterUnavailableError,
)
from volty.inverters.pool import ClientPool
from volty.monitoring.alerts import (
    ConnectionTracker,
    LowChargeTracker,
    advance_connection,
    advance_low_charge,
)
from volty.monitoring.grid import GridTracker, advance
from volty.storage import repository
from volty.storage.models import Account, Inverter

logger = logging.getLogger(__name__)

MAX_CONCURRENT_ACCOUNTS = 10
REJECTIONS_BEFORE_REAUTH = 2
OFFLINE_ALERT_SECONDS = 300


class Delivery(Enum):
    SENT = auto()
    RETRY = auto()
    REFUSED = auto()


class InverterMonitor:
    def __init__(
        self,
        bot: Bot,
        sessions: async_sessionmaker[AsyncSession],
        pool: ClientPool,
        interval_seconds: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._bot = bot
        self._sessions = sessions
        self._pool = pool
        self._interval_seconds = interval_seconds
        self._clock = clock
        self._offline_readings_before_alert = max(
            1, math.ceil(OFFLINE_ALERT_SECONDS / interval_seconds)
        )
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_ACCOUNTS)
        self._rejections: dict[int, int] = {}

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:
                logger.exception("Monitor poll failed")
            await asyncio.sleep(self._interval_seconds)

    async def poll_once(self) -> None:
        async with self._sessions() as session:
            accounts = await repository.list_monitored_accounts(session)
        await asyncio.gather(*(self._poll_account(account) for account in accounts))

    async def _poll_account(self, account: Account) -> None:
        # One broken account must never stop alerts for everyone else.
        async with self._semaphore:
            try:
                await self._poll_inverters(account)
            except Exception:
                logger.exception("Polling account %s failed", account.id)

    async def _poll_inverters(self, account: Account) -> None:
        try:
            client = await self._pool.get(account)
            for inverter in account.inverters:
                try:
                    state = await client.read_state(inverter.serial)
                except InverterUnavailableError as error:
                    logger.warning("Inverter %s is unavailable: %s", inverter.id, error)
                    continue
                await self._apply_state(account, inverter, state)
        except AuthenticationError:
            await self._handle_rejected_credentials(account)
            return
        self._rejections.pop(account.id, None)

    async def _apply_state(
        self, account: Account, inverter: Inverter, state: InverterState
    ) -> None:
        # Each tracker saves its state only after its alert is delivered, so that the next
        # poll confirms the change again and retries.
        await self._track_grid(account, inverter, state)
        await self._track_low_charge(account, inverter, state)
        await self._track_connection(account, inverter, state)

    async def _track_grid(self, account: Account, inverter: Inverter, state: InverterState) -> None:
        tracker = GridTracker(inverter.grid_state, inverter.pending_grid_state)
        next_tracker, change = advance(tracker, state.grid)
        if next_tracker == tracker:
            return
        now = self._clock()
        if change is not None:
            async with self._sessions() as session:
                started_at = await repository.open_outage_start(session, inverter.id)
            duration = None
            if change is GridState.ON_GRID and started_at is not None:
                duration = now - started_at
            t = Translator(account.user.language)
            text = grid_change_text(t, inverter, state, change, duration)
            if not await self._notify(account, inverter, text):
                return
        async with self._sessions() as session:
            if change is GridState.OFF_GRID:
                await repository.open_outage(session, inverter.id, now)
            elif change is GridState.ON_GRID:
                await repository.close_outage(session, inverter.id, now)
            await repository.update_inverter(
                session,
                inverter.id,
                {"grid_state": next_tracker.confirmed, "pending_grid_state": next_tracker.pending},
            )
            await session.commit()

    async def _track_low_charge(
        self, account: Account, inverter: Inverter, state: InverterState
    ) -> None:
        scale = inverter.battery_scale
        threshold = inverter.low_charge_percent
        voltage = state.battery_voltage
        if scale is None or threshold is None or voltage is None or not state.online:
            return
        tracker = LowChargeTracker(inverter.low_charge_alerted, inverter.low_charge_pending)
        percent = scale.percent(voltage)
        next_tracker, fired = advance_low_charge(tracker, percent, threshold, state.is_charging)
        if next_tracker == tracker:
            return
        if fired:
            t = Translator(account.user.language)
            text = low_charge_text(t, inverter, percent, voltage)
            if not await self._notify(account, inverter, text):
                return
        await self._save(
            inverter,
            {
                "low_charge_alerted": next_tracker.alerted,
                "low_charge_pending": next_tracker.pending,
            },
        )

    async def _track_connection(
        self, account: Account, inverter: Inverter, state: InverterState
    ) -> None:
        tracker = ConnectionTracker(inverter.offline_readings, inverter.offline_alerted)
        next_tracker, change = advance_connection(
            tracker, state.online, self._offline_readings_before_alert
        )
        if next_tracker == tracker:
            return
        if change is not None:
            t = Translator(account.user.language)
            if not await self._notify(account, inverter, connection_text(t, inverter, change)):
                return
        await self._save(
            inverter,
            {
                "offline_readings": next_tracker.offline_readings,
                "offline_alerted": next_tracker.alerted,
            },
        )

    async def _save(self, inverter: Inverter, values: Mapping[str, Any]) -> None:
        async with self._sessions() as session:
            await repository.update_inverter(session, inverter.id, values)
            await session.commit()

    async def _notify(self, account: Account, inverter: Inverter, text: str) -> bool:
        """Returns False only when nothing got through and a later retry could help."""
        t = Translator(account.user.language)
        deliveries: list[Delivery] = []
        if inverter.notifications_enabled:
            keyboard = battery_shortcut_keyboard(t, inverter.id)
            deliveries.append(await self._send(account.user_id, text, keyboard))
        if inverter.group_chat_id is not None:
            delivery = await self._send(
                inverter.group_chat_id, text, group_view_keyboard(t, [inverter])
            )
            deliveries.append(delivery)
            if delivery is Delivery.REFUSED:
                await self._unlink_refusing_group(account, inverter, t)
        # Retrying after a partial delivery would repeat the alert in the chat that got it.
        return not deliveries or any(d is not Delivery.RETRY for d in deliveries)

    async def _unlink_refusing_group(
        self, account: Account, inverter: Inverter, t: Translator
    ) -> None:
        title = inverter.group_chat_title or ""
        await self._save(inverter, {"group_chat_id": None, "group_chat_title": None})
        inverter.group_chat_id = None
        inverter.group_chat_title = None
        await self._send(account.user_id, t("group.removed", title=title, name=inverter.label))

    async def _handle_rejected_credentials(self, account: Account) -> None:
        # One refusal may be a cloud hiccup, but retrying a really wrong password every poll
        # could get the cloud account locked.
        rejections = self._rejections.get(account.id, 0) + 1
        if rejections < REJECTIONS_BEFORE_REAUTH:
            self._rejections[account.id] = rejections
            return
        self._rejections.pop(account.id, None)
        async with self._sessions() as session:
            await repository.mark_needs_reauth(session, account.id)
            await session.commit()
        t = Translator(account.user.language)
        await self._send(account.user_id, t("error.reauth"), connect_keyboard(t))

    async def _send(
        self, chat_id: int, text: str, keyboard: InlineKeyboardMarkup | None = None
    ) -> Delivery:
        try:
            await self._bot.send_message(chat_id, text, reply_markup=keyboard)
        except TelegramMigrateToChat as error:
            # A group gets a new id when Telegram upgrades it to a supergroup.
            async with self._sessions() as session:
                await repository.move_group(session, chat_id, error.migrate_to_chat_id)
                await session.commit()
            return await self._send(error.migrate_to_chat_id, text, keyboard)
        except (
            TelegramConflictError,
            TelegramNetworkError,
            TelegramRetryAfter,
            TelegramServerError,
            TelegramUnauthorizedError,
        ) as error:
            logger.warning("Could not reach chat %s: %s", chat_id, type(error).__name__)
            return Delivery.RETRY
        except TelegramAPIError as error:
            # A blocked bot or a lost group never recovers on retry.
            logger.warning("Chat %s refused a message: %s", chat_id, type(error).__name__)
            return Delivery.REFUSED
        return Delivery.SENT
