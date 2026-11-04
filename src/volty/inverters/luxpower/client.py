import asyncio
from typing import Any

import httpx
from pydantic import ValidationError

from volty.inverters.base import (
    AuthenticationError,
    Credentials,
    InverterInfo,
    InverterState,
    InverterUnavailableError,
)
from volty.inverters.luxpower.models import LoginPayload, RuntimePayload

REGION_URLS = {
    "eu": "https://eu.luxpowertek.com",
    "us": "https://us.luxpowertek.com",
    "na": "https://na.luxpowertek.com",
    "sea": "https://sea.luxpowertek.com",
    "af": "https://af.luxpowertek.com",
    "cn": "https://server.luxpowertek.com",
}

LOGIN_PATH = "/WManage/api/login"
RUNTIME_PATH = "/WManage/api/inverter/getInverterRuntime"
HTTP_TIMEOUT_SECONDS = 20.0
TRANSIENT_ERROR_MARKERS = ("TIMEOUT", "BUSY", "COMMUNICATION_ERROR")


class _SessionExpiredError(Exception):
    pass


class LuxpowerClient:
    def __init__(self, region: str, credentials: Credentials) -> None:
        self._credentials = credentials
        self._http = httpx.AsyncClient(base_url=REGION_URLS[region], timeout=HTTP_TIMEOUT_SECONDS)
        self._login_lock = asyncio.Lock()
        self._session_generation = 0
        self._inverters: list[InverterInfo] = []

    async def list_inverters(self) -> list[InverterInfo]:
        await self._login(self._session_generation)
        return self._inverters

    async def read_state(self, serial: str) -> InverterState:
        payload = await self._post_authorized(RUNTIME_PATH, {"serialNum": serial})
        if not payload.get("success"):
            raise InverterUnavailableError("LuxPower refused the runtime request")
        try:
            return RuntimePayload.model_validate(payload).to_state()
        except ValidationError:
            # The validation error embeds the payload, which holds the serial number.
            raise InverterUnavailableError("Unexpected LuxPower runtime payload") from None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post_authorized(self, path: str, data: dict[str, str]) -> dict[str, Any]:
        if self._session_generation == 0:
            await self._login(0)
        generation = self._session_generation
        try:
            return await self._post_json(path, data)
        except _SessionExpiredError:
            await self._login(generation)
        try:
            return await self._post_json(path, data)
        except _SessionExpiredError:
            raise InverterUnavailableError("LuxPower session expired after login") from None

    async def _post_json(self, path: str, data: dict[str, str]) -> dict[str, Any]:
        response = await self._post(path, data)
        if response.status_code == httpx.codes.UNAUTHORIZED or response.is_redirect:
            raise _SessionExpiredError
        if response.is_error:
            raise InverterUnavailableError(f"LuxPower returned HTTP {response.status_code}")
        payload = _parse_json(response)
        if payload is None:
            # An expired session answers with the HTML login page and status 200.
            raise _SessionExpiredError
        return payload

    async def _login(self, seen_generation: int) -> None:
        async with self._login_lock:
            if self._session_generation != seen_generation:
                return
            response = await self._post(
                LOGIN_PATH,
                {
                    "account": self._credentials.login,
                    "password": self._credentials.password,
                },
            )
            if response.status_code == httpx.codes.UNAUTHORIZED:
                raise AuthenticationError("LuxPower rejected the credentials")
            payload = None if response.is_error else _parse_json(response)
            if payload is None:
                raise InverterUnavailableError("LuxPower login is unavailable")
            if not payload.get("success"):
                if _is_transient_refusal(payload):
                    raise InverterUnavailableError("LuxPower login is temporarily unavailable")
                raise AuthenticationError("LuxPower rejected the credentials")
            try:
                self._inverters = LoginPayload.model_validate(payload).inverters()
            except ValidationError:
                raise InverterUnavailableError("Unexpected LuxPower login payload") from None
            self._session_generation += 1

    async def _post(self, path: str, data: dict[str, str]) -> httpx.Response:
        try:
            return await self._http.post(path, data=data)
        except httpx.HTTPError as error:
            raise InverterUnavailableError(type(error).__name__) from None


def _is_transient_refusal(payload: dict[str, Any]) -> bool:
    message = str(payload.get("message") or payload.get("msg") or "").upper()
    return any(marker in message for marker in TRANSIENT_ERROR_MARKERS)


def _parse_json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None
