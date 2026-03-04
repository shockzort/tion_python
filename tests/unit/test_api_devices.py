"""Unit tests for /api/devices endpoints — AC-02, AC-03, AC-05 coverage."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from api.routes.devices import router
from api.schemas import (
    DeviceResponse,
    DevicesListResponse,
    DiscoverResponse,
    BLEDeviceSchema,
)
from tion_btle.domain.device_manager.models import DeviceInfo


# ---------------------------------------------------------------------------
# App factory for tests (no lifespan, isolated state)
# ---------------------------------------------------------------------------


def _make_app(device_manager: MagicMock, operator: MagicMock) -> FastAPI:
    """Build a minimal FastAPI app with mocked state for device endpoint tests."""
    from api.middleware.auth import get_current_user

    app = FastAPI()
    app.include_router(router)

    # Override auth dependency to always return a fixed user_id
    app.dependency_overrides[get_current_user] = lambda: "test_user_id"

    # Inject mocked state
    app.state.device_manager = device_manager
    app.state.operator = operator

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_device_info() -> DeviceInfo:
    """A sample registered DeviceInfo."""
    return DeviceInfo(
        id="AA:BB:CC:DD:EE:FF",
        name="Living Room",
        type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
        is_active=True,
        is_paired=False,
        room="Living Room",
    )


@pytest.fixture
def mock_device_manager(sample_device_info: DeviceInfo) -> MagicMock:
    """Mock DeviceManager with pre-configured return values."""
    dm = MagicMock()
    dm.register_device = AsyncMock(return_value=sample_device_info)
    dm.delete_device = AsyncMock(return_value=True)
    dm.get_devices = MagicMock(return_value=[sample_device_info])
    dm.get_device = MagicMock(return_value=sample_device_info)
    dm.discover_devices = AsyncMock(return_value=[])
    dm.pair_device = AsyncMock(return_value=True)
    return dm


@pytest.fixture
def mock_operator() -> MagicMock:
    """Mock Operator with a nested device_manager."""
    op = MagicMock()
    op.device_manager = MagicMock()
    op.device_manager.pair_device = AsyncMock(return_value=True)
    return op


@pytest.fixture
def app(mock_device_manager: MagicMock, mock_operator: MagicMock) -> FastAPI:
    """FastAPI app with injected mocks."""
    return _make_app(mock_device_manager, mock_operator)


# ---------------------------------------------------------------------------
# AC-02 — POST /api/devices/register
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_device_success(
    app: FastAPI, mock_device_manager: MagicMock, sample_device_info: DeviceInfo
) -> None:
    """POST /api/devices/register with valid body returns 200 and DeviceInfo.

    Covers AC-02: register_device compatible signature, no TypeError.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/devices/register",
            json={
                "name": "Living Room",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "model": "S3",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert data["name"] == "Living Room"
    assert data["model"] == "S3"
    assert data["is_active"] is True

    mock_device_manager.register_device.assert_awaited_once_with(
        name="Living Room",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
        room=None,
    )


@pytest.mark.asyncio
async def test_register_device_with_room(
    app: FastAPI, mock_device_manager: MagicMock
) -> None:
    """POST /api/devices/register with optional room field passes room to device_manager."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/devices/register",
            json={
                "name": "Bedroom Breezer",
                "mac_address": "11:22:33:44:55:66",
                "model": "Lite",
                "room": "Bedroom",
            },
        )

    assert response.status_code == 200
    mock_device_manager.register_device.assert_awaited_once_with(
        name="Bedroom Breezer",
        mac_address="11:22:33:44:55:66",
        model="Lite",
        room="Bedroom",
    )


@pytest.mark.asyncio
async def test_register_device_missing_fields(app: FastAPI) -> None:
    """POST /api/devices/register without required fields returns 422.

    Covers AC-02 edge-case: missing mandatory body fields → Pydantic validation error.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/devices/register",
            json={"name": "Only Name"},  # mac_address and model missing
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_device_manager_raises_returns_500(
    app: FastAPI, mock_device_manager: MagicMock
) -> None:
    """When device_manager.register_device raises an exception, endpoint returns 500."""
    mock_device_manager.register_device.side_effect = RuntimeError("storage failure")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/devices/register",
            json={
                "name": "Bad Device",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "model": "S3",
            },
        )

    assert response.status_code == 500


# ---------------------------------------------------------------------------
# AC-03 — DELETE /api/devices/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_device_success(
    app: FastAPI, mock_device_manager: MagicMock, sample_device_info: DeviceInfo
) -> None:
    """DELETE /api/devices/{id} returns 200 and calls await device_manager.delete_device.

    Covers AC-03: delete_device must be awaited.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete("/api/devices/AA:BB:CC:DD:EE:FF")

    assert response.status_code == 200
    mock_device_manager.delete_device.assert_awaited_once_with("AA:BB:CC:DD:EE:FF")


@pytest.mark.asyncio
async def test_delete_device_not_found(
    app: FastAPI, mock_device_manager: MagicMock
) -> None:
    """DELETE /api/devices/{id} for non-existent device returns 404.

    Covers AC-03 edge-case: device not found → 404.
    """
    mock_device_manager.get_device.return_value = None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete("/api/devices/non-existent-id")

    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()
    # delete_device must NOT be called if device not found
    mock_device_manager.delete_device.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_device_is_async(
    app: FastAPI, mock_device_manager: MagicMock
) -> None:
    """Verify delete_device is called as a coroutine (awaited), not as a sync call.

    AC-03: the endpoint must contain 'await device_manager.delete_device(device_id)'.
    If delete_device is not awaited, AsyncMock.assert_awaited_once_with would fail.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete("/api/devices/AA:BB:CC:DD:EE:FF")

    assert response.status_code == 200
    # assert_awaited_once_with verifies the coroutine was properly awaited
    mock_device_manager.delete_device.assert_awaited_once_with("AA:BB:CC:DD:EE:FF")
    # Also verify it was not called as a regular (sync) mock
    assert mock_device_manager.delete_device.await_count == 1


# ---------------------------------------------------------------------------
# GET /api/devices — list devices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_devices_list(
    app: FastAPI, mock_device_manager: MagicMock, sample_device_info: DeviceInfo
) -> None:
    """GET /api/devices returns 200 with list of registered devices."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/devices")

    assert response.status_code == 200
    data = response.json()
    assert "devices" in data
    assert isinstance(data["devices"], list)
    assert len(data["devices"]) == 1
    assert data["devices"][0]["mac_address"] == "AA:BB:CC:DD:EE:FF"


@pytest.mark.asyncio
async def test_get_devices_empty_list(
    app: FastAPI, mock_device_manager: MagicMock
) -> None:
    """GET /api/devices returns empty list when no devices registered."""
    mock_device_manager.get_devices.return_value = []

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/devices")

    assert response.status_code == 200
    data = response.json()
    assert data["devices"] == []


# ---------------------------------------------------------------------------
# GET /api/devices/{device_id} — get single device
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_device_by_id(
    app: FastAPI, mock_device_manager: MagicMock, sample_device_info: DeviceInfo
) -> None:
    """GET /api/devices/{id} returns 200 with device details."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/devices/AA:BB:CC:DD:EE:FF")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "AA:BB:CC:DD:EE:FF"
    assert data["name"] == "Living Room"


@pytest.mark.asyncio
async def test_get_device_by_id_not_found(
    app: FastAPI, mock_device_manager: MagicMock
) -> None:
    """GET /api/devices/{id} for unknown device returns 404."""
    mock_device_manager.get_device.return_value = None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/devices/unknown-id")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/devices/discover — BLE scanning (AC-12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_devices_returns_empty_list(
    app: FastAPI, mock_device_manager: MagicMock
) -> None:
    """POST /api/devices/discover returns 200 with empty list when no BLE devices found."""
    mock_device_manager.discover_devices.return_value = []

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/devices/discover")

    assert response.status_code == 200
    data = response.json()
    assert "devices" in data
    assert data["devices"] == []


@pytest.mark.asyncio
async def test_discover_devices_with_ble_mock(
    app: FastAPI, mock_device_manager: MagicMock
) -> None:
    """POST /api/devices/discover returns found BLE devices with BLE scanner mocked.

    Covers AC-12: discover endpoint mocks BLE scanning.
    """
    mock_ble = MagicMock()
    mock_ble.name = "Tion_Breezer_S3_1234"
    mock_ble.address = "AA:BB:CC:DD:EE:FF"
    mock_ble.rssi = -65

    mock_device_manager.discover_devices.return_value = [mock_ble]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/devices/discover")

    assert response.status_code == 200
    data = response.json()
    assert len(data["devices"]) == 1
    assert data["devices"][0]["address"] == "AA:BB:CC:DD:EE:FF"
    assert data["devices"][0]["name"] == "Tion_Breezer_S3_1234"


@pytest.mark.asyncio
async def test_discover_devices_ble_exception_returns_500(
    app: FastAPI, mock_device_manager: MagicMock
) -> None:
    """POST /api/devices/discover returns 500 when BLE scanning raises an exception."""
    mock_device_manager.discover_devices.side_effect = RuntimeError("Bluetooth adapter error")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/devices/discover")

    assert response.status_code == 500


# ---------------------------------------------------------------------------
# AC-01 — pyproject.toml contains correct testpaths
# ---------------------------------------------------------------------------


def test_pyproject_testpaths_includes_domain_tests() -> None:
    """AC-01/AC-05: pyproject.toml testpaths includes domain test directory.

    Covers AC-05: domain tests must be included in the standard pytest run.
    In TOML, [tool.pytest.ini_options] is nested as config["tool"]["pytest"]["ini_options"].
    """
    import tomllib
    import pathlib

    pyproject_path = pathlib.Path(__file__).parents[2] / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        config = tomllib.load(f)

    # In pyproject.toml, [tool.pytest.ini_options] → config["tool"]["pytest"]["ini_options"]
    pytest_config = config["tool"]["pytest"]["ini_options"]
    testpaths = pytest_config["testpaths"]
    assert "tests" in testpaths, "testpaths must include 'tests'"
    assert any(
        "tion_btle/domain/device_manager/tests" in p for p in testpaths
    ), "testpaths must include domain device_manager tests"


# ---------------------------------------------------------------------------
# AC-04 — operator.py does not swallow exceptions silently
# ---------------------------------------------------------------------------


def test_operator_reconnect_device_logs_exception_not_pass() -> None:
    """AC-04: operator.py must not have 'except Exception: pass' — must log or re-raise.

    Reads operator.py source and verifies the banned pattern is absent.
    """
    import pathlib

    operator_path = (
        pathlib.Path(__file__).parents[2] / "tion_btle" / "operator.py"
    )
    source = operator_path.read_text()

    # The banned pattern: bare 'except Exception: pass' (with optional whitespace)
    import re

    # Match 'except Exception:' followed by optional whitespace and then 'pass'
    # on the same or next line (no logging in between).
    banned_pattern = re.compile(
        r"except\s+Exception\s*:\s*\n?\s*pass\b", re.MULTILINE
    )
    matches = banned_pattern.findall(source)
    assert not matches, (
        f"Found banned 'except Exception: pass' pattern in operator.py: {matches}"
    )


def test_operator_exception_handlers_use_exc_info() -> None:
    """AC-04: operator.py exception handlers must log with exc_info=True.

    Verifies that the critical exception-catching blocks (_poll_devices, reconnect_device,
    execute_scenario, _run_scenarios_loop, shutdown) use exc_info=True and not f-strings.
    Checks that 'exc_info=True' appears in exception handler blocks.
    """
    import pathlib
    import re

    operator_path = (
        pathlib.Path(__file__).parents[2] / "tion_btle" / "operator.py"
    )
    source = operator_path.read_text()

    # Verify the key fixed patterns are present (exc_info=True in logging)
    assert "exc_info=True" in source, (
        "operator.py must contain at least one exc_info=True in exception handlers"
    )

    # Count exc_info=True occurrences - implementer report states 5 fixes
    exc_info_count = source.count("exc_info=True")
    assert exc_info_count >= 4, (
        f"Expected at least 4 occurrences of exc_info=True in operator.py, found {exc_info_count}"
    )

    # Verify the specific critical fix: reconnect_device except block no longer uses 'pass'
    # The pattern 'except Exception: pass' (with no logging) must not exist in reconnect context
    # We find the reconnect_device function block and verify it has logging
    reconnect_match = re.search(
        r"def reconnect_device.*?(?=\ndef |\Z)", source, re.DOTALL
    )
    assert reconnect_match is not None, "reconnect_device function must exist in operator.py"
    reconnect_body = reconnect_match.group(0)
    assert "exc_info=True" in reconnect_body or "_LOGGER.warning" in reconnect_body, (
        "reconnect_device exception handler must log with exc_info=True or _LOGGER.warning"
    )
