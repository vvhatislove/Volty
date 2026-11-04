import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramMigrateToChat
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from volty.bot.formatting import grid_change_text
from volty.bot.i18n import Translator
from volty.bot.keyboards import battery_shortcut_keyboard, connect_keyboard
from volty.inverters.base import (
    AuthenticationError,
    GridState,
    InverterState,
    InverterUnavailableError,
)
from volty.inverters.pool import ClientPool
from volty.monitoring.grid import GridTracker, advance
from volty.storage import repository
from volty.storage.models import Account, Inverter

logger = logging.getLogger(__name__)

MAX_CONCURRENT_ACCOUNTS = 10
REJECTIONS_BEFORE_REAUTH = 2


class GridMonitor:
    def __init__(
        self,
        bot: Bot,
        sessions: async_sessionmaker[AsyncSession],
        pool: ClientPool,
        interval_seconds: int,
    ) -> None:
        self._bot = bot
        self._sessions = sessions
        self._pool = pool
        self._interval_seconds = interval_seconds
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_ACCOUNTS)
        self._rejections: dict[int, int] = {}

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:
                logger.exception("Grid monitor poll failed")
            await asyncio.sleep(self._interval_seconds)

    async def poll_once(self) -> None:
        async with self._sessions() as session:
            accounts = await repository.list_monitored_accounts(session)
        await asyncio.gather(*(self._poll_account(account) for account in accounts))

    async def _poll_account(self, account: Account) -> None:
        async with self._semaphore:
            client = await self._pool.get(account)
            for inverter in account.inverters:
                try:
                    state = await client.read_state(inverter.serial)
                except AuthenticationError:
                    await self._handle_rejected_credentials(account)
                    return
                except InverterUnavailableError as error:
                    logger.warning("Account %s is unavailable: %s", account.id, error)
                    return
                await self._apply_state(account, inverter, state)
            self._rejections.pop(account.id, None)

    async def _apply_state(
        self, account: Account, inverter: Inverter, state: InverterState
    ) -> None:
        tracker = GridTracker(inverter.grid_state, inverter.pending_grid_state)
        next_tracker, change = advance(tracker, state.grid)
        if next_tracker == tracker:
            return
        if change is not None and not await self._notify(account, inverter, state, change):
            # Nothing was delivered, so the state stays unsaved and the next poll retries.
            return
        async with self._sessions() as session:
            await repository.save_grid_tracker(session, inverter.id, next_tracker)
            await session.commit()

    async def _notify(
        self, account: Account, inverter: Inverter, state: InverterState, change: GridState
    ) -> bool:
        t = Translator(account.user.language)
        text = grid_change_text(t, inverter, state, change)
        deliveries: list[bool] = []
        if inverter.notifications_enabled:
            keyboard = battery_shortcut_keyboard(t, inverter.id)
            deliveries.append(await self._send(account.user_id, text, keyboard))
        if inverter.group_chat_id is not None:
            deliveries.append(await self._send(inverter.group_chat_id, text))
        # Retrying after a partial delivery would repeat the alert in the chat that got it.
        return not deliveries or any(deliveries)

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
    ) -> bool:
        try:
            await self._bot.send_message(chat_id, text, reply_markup=keyboard)
        except TelegramMigrateToChat as error:
            # A group gets a new id when Telegram upgrades it to a supergroup.
            async with self._sessions() as session:
                await repository.move_group(session, chat_id, error.migrate_to_chat_id)
                await session.commit()
            return await self._send(error.migrate_to_chat_id, text, keyboard)
        except TelegramForbiddenError:
            logger.info("User %s has blocked the bot", chat_id)
        except TelegramAPIError as error:
            logger.warning("Could not notify user %s: %s", chat_id, type(error).__name__)
            return False
        return True
