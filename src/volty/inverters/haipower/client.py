import asyncio
import hashlib
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from volty.inverters.base import (
    AuthenticationError,
    Credentials,
    EnergySummary,
    InverterInfo,
    InverterState,
    InverterUnavailableError,
)
from volty.inverters.haipower.models import DeviceListPayload, EnergyPayload, StatePayload

REGION_URLS = {
    "eu": "https://eu.aohaidigitalpower.com",
    "cloud": "https://cloud.aohaidigitalpower.com",
}

LOGIN_PATH = "/auth/doWebLogin1"
DEVICES_PATH = "/view/device/list"
STATE_PATH = "/view/data/deviceInfo"
DEVICES_PAGE_SIZE = 20
MAX_DEVICE_PAGES = 10
TOKEN_COOKIE = "AUTH_USER_TOKEN"
TOKEN_PATTERN = re.compile(rf"\s*{TOKEN_COOKIE}=([^;]+)")
SUCCESS_CODE = 200
BAD_CREDENTIALS_CODE = 400
SESSION_EXPIRED_CODES = frozenset({401, 501})
HTTP_TIMEOUT_SECONDS = 20.0
# The cloud has no reliable offline flag, and its timestamps carry no time zone, so an
# inverter counts as offline once its last upload time stops changing for this long.
STALE_AFTER_SECONDS = 900.0


class _SessionExpiredError(Exception):
    pass


class HaipowerClient:
    def __init__(
        self,
        region: str,
        credentials: Credentials,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._credentials = credentials
        self._clock = clock
        self._uploads: dict[str, tuple[str, float]] = {}
        self._http = httpx.AsyncClient(
            base_url=REGION_URLS[region],
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"Accept-Language": "en"},
        )
        self._login_lock = asyncio.Lock()
        self._session_generation = 0
        self._session_headers: dict[str, str] = {}

    async def list_inverters(self) -> list[InverterInfo]:
        inverters: dict[str, InverterInfo] = {}
        for page in range(1, MAX_DEVICE_PAGES + 1):
            payload = await self._read(DEVICES_PATH, _devices_query(page), DeviceListPayload)
            known = len(inverters)
            inverters.update((inverter.serial, inverter) for inverter in payload.inverters())
            if len(inverters) == known or len(inverters) >= payload.total:
                break
        return list(inverters.values())

    async def read_state(self, serial: str) -> InverterState:
        payload = await self._read(STATE_PATH, {"dsn": serial}, StatePayload)
        return payload.to_state(stale=self._is_stale(serial, payload.last_time))

    async def read_energy(self, serial: str) -> EnergySummary:
        return (await self._read(STATE_PATH, {"dsn": serial}, EnergyPayload)).to_summary()

    async def aclose(self) -> None:
        await self._http.aclose()

    def _is_stale(self, serial: str, last_time: str | None) -> bool:
        if last_time is None:
            return False
        now = self._clock()
        upload = self._uploads.get(serial)
        if upload is None or upload[0] != last_time:
            self._uploads[serial] = (last_time, now)
            return False
        return now - upload[1] > STALE_AFTER_SECONDS

    async def _read[ModelT: BaseModel](
        self, path: str, params: dict[str, str], model: type[ModelT]
    ) -> ModelT:
        data = await self._get_authorized(path, params)
        try:
            return model.model_validate(data)
        except ValidationError:
            # The validation error embeds the payload, which holds the serial number.
            raise InverterUnavailableError("Unexpected HaiPower payload") from None

    async def _get_authorized(self, path: str, params: dict[str, str]) -> Any:
        if self._session_generation == 0:
            await self._login(0)
        generation = self._session_generation
        try:
            return await self._get_data(path, params)
        except _SessionExpiredError:
            await self._login(generation)
        try:
            return await self._get_data(path, params)
        except _SessionExpiredError:
            raise InverterUnavailableError("HaiPower session expired after login") from None

    async def _get_data(self, path: str, params: dict[str, str]) -> Any:
        try:
            response = await self._http.get(path, params=params, headers=self._session_headers)
        except httpx.HTTPError as error:
            raise InverterUnavailableError(type(error).__name__) from None
        payload = _parse(response)
        if payload.get("code") in SESSION_EXPIRED_CODES:
            raise _SessionExpiredError
        if payload.get("code") != SUCCESS_CODE:
            raise InverterUnavailableError("HaiPower refused the request")
        return payload.get("data")

    async def _login(self, seen_generation: int) -> None:
        async with self._login_lock:
            if self._session_generation != seen_generation:
                return
            try:
                response = await self._http.post(
                    LOGIN_PATH,
                    data={
                        "code": "1",
                        "userName": self._credentials.login,
                        "password": _password_digest(self._credentials.password),
                    },
                )
            except httpx.HTTPError as error:
                raise InverterUnavailableError(type(error).__name__) from None
            payload = _parse(response)
            code = payload.get("code")
            if code == BAD_CREDENTIALS_CODE:
                raise AuthenticationError("HaiPower rejected the credentials")
            if code != SUCCESS_CODE:
                raise InverterUnavailableError("HaiPower login is unavailable")
            token = _session_token(response)
            data = payload.get("data")
            account_id = data.get("id") if isinstance(data, dict) else None
            if not token or account_id is None:
                raise InverterUnavailableError("Unexpected HaiPower login payload")
            # The cloud answered "Auth is error!" when a cookie jar sent the token, so the raw
            # value goes out by hand.
            self._http.cookies.clear()
            self._session_headers = {
                "Cookie": f"{TOKEN_COOKIE}={token}",
                "system_hid": str(account_id),
            }
            self._session_generation += 1


def _devices_query(page: int) -> dict[str, str]:
    return {
        "csn": "",
        "dsn": "",
        "type": "0",
        "id": "0",
        "offset": str((page - 1) * DEVICES_PAGE_SIZE),
        "pageNum": str(page),
        "pageSize": str(DEVICES_PAGE_SIZE),
    }


def _session_token(response: httpx.Response) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        match = TOKEN_PATTERN.match(header)
        if match:
            return match.group(1)
    return None


def _password_digest(password: str) -> str:
    # The cloud accepts only the MD5 digest that its own apps send.
    return hashlib.md5(password.encode(), usedforsecurity=False).hexdigest()


def _parse(response: httpx.Response) -> dict[str, Any]:
    if response.is_error:
        raise InverterUnavailableError(f"HaiPower returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise InverterUnavailableError("HaiPower returned a malformed answer")
    return payload
