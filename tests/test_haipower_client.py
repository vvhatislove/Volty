import hashlib
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from tests.conftest import load_fixture
from volty.inverters.base import (
    AuthenticationError,
    Credentials,
    EnergySummary,
    GridState,
    InverterInfo,
    InverterUnavailableError,
)
from volty.inverters.haipower.client import (
    DEVICES_PATH,
    LOGIN_PATH,
    STALE_AFTER_SECONDS,
    STATE_PATH,
    HaipowerClient,
)

BASE_URL = "https://eu.aohaidigitalpower.com"
SERIAL = "D000000001"
TOKEN = "test-token"
SESSION_EXPIRED = {"code": 501, "msg": "Auth is error!"}


@pytest.fixture
async def client() -> AsyncIterator[HaipowerClient]:
    instance = HaipowerClient("eu", Credentials(login="user", password="secret"))
    yield instance
    await instance.aclose()


def mock_login() -> respx.Route:
    return respx.post(f"{BASE_URL}{LOGIN_PATH}").mock(
        return_value=httpx.Response(
            200,
            json=load_fixture("haipower_login"),
            headers={"Set-Cookie": f"AUTH_USER_TOKEN={TOKEN}; Max-Age=21600; Path=/; Secure"},
        )
    )


def mock_state(**changes: Any) -> respx.Route:
    payload = load_fixture("haipower_state_on_grid")
    payload["data"] |= changes
    return respx.get(f"{BASE_URL}{STATE_PATH}").mock(return_value=httpx.Response(200, json=payload))


@respx.mock
async def test_login_sends_password_digest_and_lists_inverters(client: HaipowerClient) -> None:
    login = mock_login()
    devices = respx.get(f"{BASE_URL}{DEVICES_PATH}").mock(
        return_value=httpx.Response(200, json=load_fixture("haipower_devices"))
    )

    inverters = await client.list_inverters()

    assert inverters == [InverterInfo(serial=SERIAL, model="FSC-12K1P-BL-G3")]
    form = parse_qs(login.calls.last.request.content.decode())
    assert form == {
        "code": ["1"],
        "userName": ["user"],
        "password": [hashlib.md5(b"secret").hexdigest()],
    }
    request = devices.calls.last.request
    assert request.headers["Cookie"] == f"AUTH_USER_TOKEN={TOKEN}"
    assert request.headers["system_hid"] == "1001"


@respx.mock
async def test_on_grid_state_is_converted_to_watts(client: HaipowerClient) -> None:
    mock_login()
    mock_state()

    state = await client.read_state(SERIAL)

    assert state.online
    assert state.grid is GridState.ON_GRID
    assert state.soc == 59
    assert state.battery_voltage == 54.0
    assert state.charge_power == 2700
    assert state.discharge_power == 0
    assert state.load_power == 340
    assert state.pv_power == 0


@respx.mock
async def test_off_grid_status_means_no_grid(client: HaipowerClient) -> None:
    mock_login()
    mock_state(status2="OffGrid", vac1=0.0, pcharge=0.0, pdischarge=0.82)

    state = await client.read_state(SERIAL)

    assert state.grid is GridState.OFF_GRID
    assert state.discharge_power == 820


@respx.mock
async def test_bypass_with_grid_voltage_means_grid_is_on(client: HaipowerClient) -> None:
    mock_login()
    mock_state(status2="ByPass", vac1=228.0)

    state = await client.read_state(SERIAL)

    assert state.grid is GridState.ON_GRID


@pytest.mark.parametrize(
    ("status", "voltage"),
    [("Mystery", 230.0), ("Fault", 230.0), ("OnGrid", 0.0), ("OffGrid", 230.0)],
    ids=[
        "unmapped status",
        "fault",
        "grid status without grid voltage",
        "off-grid status with grid voltage",
    ],
)
@respx.mock
async def test_unreliable_readings_are_unknown(
    client: HaipowerClient, status: str, voltage: float
) -> None:
    mock_login()
    mock_state(status2=status, vac1=voltage)

    state = await client.read_state(SERIAL)

    assert state.online
    assert state.grid is GridState.UNKNOWN


@respx.mock
async def test_offline_status_hides_outdated_readings(client: HaipowerClient) -> None:
    mock_login()
    mock_state(status2="OffLine")

    state = await client.read_state(SERIAL)

    assert not state.online
    assert state.grid is GridState.UNKNOWN
    assert state.soc is None


@respx.mock
async def test_inverter_that_stops_uploading_goes_offline_and_recovers() -> None:
    now = 0.0
    client = HaipowerClient("eu", Credentials(login="user", password="secret"), lambda: now)
    mock_login()
    mock_state()

    assert (await client.read_state(SERIAL)).online
    now = STALE_AFTER_SECONDS
    assert (await client.read_state(SERIAL)).online
    now = STALE_AFTER_SECONDS + 1
    assert not (await client.read_state(SERIAL)).online

    mock_state(lastTime="2026-01-01 12:05:00")
    assert (await client.read_state(SERIAL)).online
    await client.aclose()


@respx.mock
async def test_device_list_is_read_page_by_page(client: HaipowerClient) -> None:
    mock_login()

    def page(request: httpx.Request) -> httpx.Response:
        number = int(request.url.params["pageNum"])
        assert request.url.params["offset"] == str((number - 1) * 20)
        payload = load_fixture("haipower_devices")
        payload["data"]["total"] = 2
        payload["data"]["rows"][0] |= {"dsn": f"D00000000{number}", "typeName": None}
        return httpx.Response(200, json=payload)

    devices = respx.get(f"{BASE_URL}{DEVICES_PATH}").mock(side_effect=page)

    inverters = await client.list_inverters()

    assert [inverter.serial for inverter in inverters] == ["D000000001", "D000000002"]
    assert inverters[0].model == "HaiPower"
    assert devices.call_count == 2


@respx.mock
async def test_missing_energy_counters_count_as_zero(client: HaipowerClient) -> None:
    mock_login()
    mock_state(etoGridToday=None)

    assert (await client.read_energy(SERIAL)).exported == 0.0


@respx.mock
async def test_energy_summary(client: HaipowerClient) -> None:
    mock_login()
    mock_state()

    assert await client.read_energy(SERIAL) == EnergySummary(
        produced=1.8, charged=7.2, discharged=1.2, consumed=6.1, imported=12.7, exported=2.5
    )


@respx.mock
async def test_expired_session_logs_in_again(client: HaipowerClient) -> None:
    login = mock_login()
    respx.get(f"{BASE_URL}{STATE_PATH}").mock(
        side_effect=[
            httpx.Response(200, json=SESSION_EXPIRED),
            httpx.Response(200, json=load_fixture("haipower_state_on_grid")),
        ]
    )

    summary = await client.read_energy(SERIAL)

    assert summary.produced == 1.8
    assert login.call_count == 2


@respx.mock
async def test_session_is_reused_between_reads(client: HaipowerClient) -> None:
    login = mock_login()
    mock_state()

    await client.read_energy(SERIAL)
    await client.read_energy(SERIAL)

    assert login.call_count == 1


@respx.mock
async def test_wrong_password_is_an_authentication_error(client: HaipowerClient) -> None:
    respx.post(f"{BASE_URL}{LOGIN_PATH}").mock(
        return_value=httpx.Response(200, json=load_fixture("haipower_login_rejected"))
    )

    with pytest.raises(AuthenticationError):
        await client.list_inverters()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(502),
        httpx.Response(200, text="<html></html>"),
        httpx.Response(200, json={"code": 500, "msg": "error"}),
        httpx.Response(200, json=SESSION_EXPIRED),
        httpx.Response(200, json=load_fixture("haipower_login")),
    ],
    ids=["http error", "not json", "server error", "unknown refusal", "no session cookie"],
)
@respx.mock
async def test_broken_login_is_not_an_authentication_error(
    client: HaipowerClient, response: httpx.Response
) -> None:
    respx.post(f"{BASE_URL}{LOGIN_PATH}").mock(return_value=response)

    with pytest.raises(InverterUnavailableError):
        await client.list_inverters()


@respx.mock
async def test_network_failure_is_unavailable(client: HaipowerClient) -> None:
    mock_login()
    respx.get(f"{BASE_URL}{STATE_PATH}").mock(side_effect=httpx.ConnectTimeout("slow"))

    with pytest.raises(InverterUnavailableError):
        await client.read_energy(SERIAL)


@respx.mock
async def test_unexpected_payload_does_not_leak_the_serial(client: HaipowerClient) -> None:
    mock_login()
    respx.get(f"{BASE_URL}{STATE_PATH}").mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"dsn": SERIAL, "soc": "?"}})
    )

    with pytest.raises(InverterUnavailableError) as raised:
        await client.read_state(SERIAL)

    assert SERIAL not in str(raised.value)
