from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from tests.conftest import load_fixture
from volty.inverters.base import (
    AuthenticationError,
    Credentials,
    GridState,
    InverterInfo,
    InverterUnavailableError,
)
from volty.inverters.luxpower.client import ENERGY_PATH, LOGIN_PATH, RUNTIME_PATH, LuxpowerClient

BASE_URL = "https://eu.luxpowertek.com"
SERIAL = "0000000001"


@pytest.fixture
async def client() -> AsyncIterator[LuxpowerClient]:
    instance = LuxpowerClient("eu", Credentials(login="user", password="secret"))
    yield instance
    await instance.aclose()


def mock_login() -> respx.Route:
    return respx.post(f"{BASE_URL}{LOGIN_PATH}").mock(
        return_value=httpx.Response(200, json=load_fixture("login"))
    )


@respx.mock
async def test_login_sends_credentials_and_lists_inverters(client: LuxpowerClient) -> None:
    route = mock_login()

    inverters = await client.list_inverters()

    assert inverters == [InverterInfo(serial=SERIAL, model="LXP-EU 12K")]
    assert route.calls.last.request.content == b"account=user&password=secret"


@respx.mock
async def test_on_grid_state_is_scaled(client: LuxpowerClient) -> None:
    mock_login()
    respx.post(f"{BASE_URL}{RUNTIME_PATH}").mock(
        return_value=httpx.Response(200, json=load_fixture("runtime_on_grid"))
    )

    state = await client.read_state(SERIAL)

    assert state.online
    assert state.grid is GridState.ON_GRID
    assert state.soc == 71
    assert state.battery_voltage == 53.0
    assert state.is_charging


@respx.mock
async def test_off_grid_status_means_no_grid(client: LuxpowerClient) -> None:
    mock_login()
    respx.post(f"{BASE_URL}{RUNTIME_PATH}").mock(
        return_value=httpx.Response(200, json=load_fixture("runtime_off_grid"))
    )

    state = await client.read_state(SERIAL)

    assert state.grid is GridState.OFF_GRID
    assert state.is_discharging


@respx.mock
async def test_lost_inverter_with_partial_payload_is_unknown(client: LuxpowerClient) -> None:
    mock_login()
    respx.post(f"{BASE_URL}{RUNTIME_PATH}").mock(
        return_value=httpx.Response(200, json=load_fixture("runtime_lost"))
    )

    state = await client.read_state(SERIAL)

    assert not state.online
    assert state.grid is GridState.UNKNOWN
    assert state.soc is None


@pytest.mark.parametrize(
    ("status", "voltage"),
    [(9999, 2300), (16, 0)],
    ids=["unmapped status", "grid status without grid voltage"],
)
@respx.mock
async def test_unreliable_readings_are_unknown(
    client: LuxpowerClient, status: int, voltage: int
) -> None:
    mock_login()
    payload = load_fixture("runtime_on_grid") | {"status": status, "vacr": voltage}
    respx.post(f"{BASE_URL}{RUNTIME_PATH}").mock(return_value=httpx.Response(200, json=payload))

    state = await client.read_state(SERIAL)

    assert state.grid is GridState.UNKNOWN


@pytest.mark.parametrize(
    "expired",
    [
        httpx.Response(200, text="<html>login</html>", headers={"content-type": "text/html"}),
        httpx.Response(401),
        httpx.Response(302, headers={"location": "/WManage/web/login"}),
    ],
    ids=["html login page", "unauthorized", "redirect"],
)
@respx.mock
async def test_expired_session_logs_in_again(
    client: LuxpowerClient, expired: httpx.Response
) -> None:
    login = mock_login()
    respx.post(f"{BASE_URL}{RUNTIME_PATH}").mock(
        side_effect=[expired, httpx.Response(200, json=load_fixture("runtime_on_grid"))]
    )

    state = await client.read_state(SERIAL)

    assert state.soc == 71
    assert login.call_count == 2


@respx.mock
async def test_session_is_reused_between_reads(client: LuxpowerClient) -> None:
    login = mock_login()
    respx.post(f"{BASE_URL}{RUNTIME_PATH}").mock(
        return_value=httpx.Response(200, json=load_fixture("runtime_on_grid"))
    )

    await client.read_state(SERIAL)
    await client.read_state(SERIAL)

    assert login.call_count == 1


@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, json={"success": False, "msg": "bad"}), httpx.Response(401)],
    ids=["success false", "unauthorized"],
)
@respx.mock
async def test_rejected_login_raises_authentication_error(
    client: LuxpowerClient, response: httpx.Response
) -> None:
    respx.post(f"{BASE_URL}{LOGIN_PATH}").mock(return_value=response)

    with pytest.raises(AuthenticationError):
        await client.list_inverters()


@respx.mock
async def test_transient_login_refusal_is_not_a_wrong_password(client: LuxpowerClient) -> None:
    respx.post(f"{BASE_URL}{LOGIN_PATH}").mock(
        return_value=httpx.Response(200, json={"success": False, "msg": "DEVICE_BUSY"})
    )

    with pytest.raises(InverterUnavailableError):
        await client.list_inverters()


@pytest.mark.parametrize(
    "outcome",
    [httpx.ConnectTimeout("timeout"), httpx.Response(503)],
    ids=["timeout", "server error"],
)
@respx.mock
async def test_cloud_failure_during_read_is_unavailable(
    client: LuxpowerClient, outcome: httpx.ConnectTimeout | httpx.Response
) -> None:
    mock_login()
    route = respx.post(f"{BASE_URL}{RUNTIME_PATH}")
    if isinstance(outcome, httpx.Response):
        route.mock(return_value=outcome)
    else:
        route.mock(side_effect=outcome)

    with pytest.raises(InverterUnavailableError):
        await client.read_state(SERIAL)


@respx.mock
async def test_malformed_runtime_error_does_not_leak_payload(client: LuxpowerClient) -> None:
    mock_login()
    respx.post(f"{BASE_URL}{RUNTIME_PATH}").mock(
        return_value=httpx.Response(200, json={"success": True, "soc": SERIAL + "x"})
    )

    with pytest.raises(InverterUnavailableError) as error:
        await client.read_state(SERIAL)

    assert SERIAL not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    ("fields", "load"),
    [
        ({"consumptionPower": 700, "peps": 900}, 700),
        ({"consumptionPower": 0, "peps": 921}, 921),
        ({"ppv": 500, "pDisCharge": 800, "pCharge": 0, "pToUser": 100, "pToGrid": 50}, 1350),
    ],
    ids=["consumption field", "backup output", "energy balance"],
)
@respx.mock
async def test_load_power_uses_best_available_field(
    client: LuxpowerClient, fields: dict[str, int], load: int
) -> None:
    mock_login()
    payload = load_fixture("runtime_off_grid") | {"pDisCharge": 0} | fields
    respx.post(f"{BASE_URL}{RUNTIME_PATH}").mock(return_value=httpx.Response(200, json=payload))

    assert (await client.read_state(SERIAL)).load_power == load


@respx.mock
async def test_energy_is_scaled_to_kilowatt_hours(client: LuxpowerClient) -> None:
    mock_login()
    respx.post(f"{BASE_URL}{ENERGY_PATH}").mock(
        return_value=httpx.Response(200, json=load_fixture("energy"))
    )

    energy = await client.read_energy(SERIAL)

    assert energy.produced == 5.2
    assert energy.discharged == 2.4
    assert energy.consumed == 7.0
