import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from tion_btle.operator import Operator, DeviceStatus
from tion_btle.device_manager import DeviceInfo
from tion_btle.scenarist import Scenario
from tion_btle import TionS3, TionLite, TionS4


@pytest.fixture
def mock_device_manager():
    manager = MagicMock()
    manager._init_db = MagicMock()
    manager.get_devices.return_value = [
        DeviceInfo(
            id="device1",
            name="Test Device 1",
            type="TionS3",
            mac_address="00:11:22:33:44:55",
            model="S3",
            is_active=True,
            is_paired=True,
        )
    ]
    manager.get_device.return_value = DeviceInfo(
        id="device1",
        name="Test Device 1",
        type="TionS3",
        mac_address="00:11:22:33:44:55",
        model="S3",
        is_active=True,
        is_paired=True,
    )
    manager.get_connected_devices.return_value = {
        "device1": DeviceInfo(
            id="device1",
            name="Test Device 1",
            type="TionS3",
            mac_address="00:11:22:33:44:55",
            model="S3",
            is_active=True,
            is_paired=True,
        )
    }
    manager.get_device_capabilities.return_value = {
        "fan_control": True,
        "heater_control": True,
        "temperature_control": True,
        "light_control": False,
        "mode_control": False,
    }
    return manager


@pytest.fixture
def mock_scenarist():
    scenarist = MagicMock()
    scenarist._init_db = MagicMock()
    scenarist.get_scenario.return_value = Scenario(
        id=1,
        name="Test Scenario",
        trigger_type="time",
        trigger_params={"start": "08:00", "end": "18:00"},
        action_params={"device_id": "device1", "command": "turn_on"},
        is_active=True,
    )
    scenarist.get_scenarios.return_value = [
        Scenario(
            id=1,
            name="Test Scenario",
            trigger_type="time",
            trigger_params={"start": "08:00", "end": "18:00"},
            action_params={"device_id": "device1", "command": "turn_on"},
            is_active=True,
        )
    ]
    scenarist.validate_action_params.return_value = True
    return scenarist


@pytest.fixture
def operator(mock_device_manager, mock_scenarist):
    with patch(
        "tion_btle.operator.DeviceManager", return_value=mock_device_manager
    ), patch("tion_btle.operator.Scenarist", return_value=mock_scenarist):
        op = Operator(db_path=":memory:")
        op._devices = {"device1": AsyncMock()}
        op._status_cache = {}
        yield op


@pytest.mark.asyncio
async def test_operator_initialization(operator, mock_device_manager):
    """Test operator initialization loads devices correctly."""
    # Setup mock device
    mock_device = AsyncMock()
    mock_device.connect = AsyncMock()
    
    # Patch TionS3 to return our mock device
    with patch('tion_btle.operator.TionS3', return_value=mock_device):
        operator._retries = 1  # Reduce retries for test speed
        await operator.initialize(is_testing=True)
        
        mock_device_manager.get_devices.assert_called_once()
        mock_device.connect.assert_called_once()
        assert len(operator._devices) == 1
        assert "device1" in operator._devices


@pytest.mark.asyncio
async def test_device_loading(operator, mock_device_manager):
    """Test device loading with retry logic."""
    mock_device = AsyncMock()
    mock_device.connect.side_effect = [Exception("Failed"), None]

    with patch("tion_btle.operator.TionS3", return_value=mock_device):
        device = await operator._load_device(mock_device_manager.get_device("device1"))
        assert device is not None
        assert mock_device.connect.call_count == 2


@pytest.mark.asyncio
async def test_device_polling(operator, mock_device_manager):
    """Test device polling updates status cache."""
    mock_device = operator._devices["device1"]
    mock_device.get.return_value = {"state": "on", "fan_speed": 3, "heater": "on"}
    mock_device.connection_status = True

    # Mock get_connected_devices to return our test device
    mock_device_manager.get_connected_devices.return_value = {
        "device1": DeviceInfo(
            id="device1",
            name="Test Device 1",
            type="TionS3",
            mac_address="00:11:22:33:44:55",
            model="S3",
            is_active=True,
            is_paired=True,
        )
    }

    # Test single poll iteration
    await operator._poll_devices(0.1, run_once=True)

    assert "device1" in operator._status_cache
    status = operator._status_cache["device1"]
    assert status.state == "on"
    assert status.fan_speed == 3
    assert status.heater_status == "on"


@pytest.mark.asyncio
async def test_device_reconnection(operator):
    """Test automatic device reconnection."""
    mock_device = operator._devices["device1"]
    mock_device.get.side_effect = [Exception("Disconnected"), {"state": "on"}]
    mock_device.connection_status = False

    await operator._poll_devices(0.1)

    assert mock_device.connect.called
    assert "device1" in operator._status_cache


@pytest.mark.asyncio
async def test_execute_scenario_success(operator, mock_scenarist):
    """Test successful scenario execution."""
    mock_device = AsyncMock()
    mock_device.set.return_value = True
    operator._devices["device1"] = mock_device

    result = await operator.execute_scenario(1)
    assert result is True
    assert mock_scenarist.get_scenario().last_executed is not None
    assert mock_scenarist.get_scenario().last_status is True


@pytest.mark.asyncio
async def test_execute_scenario_failure(operator, mock_scenarist):
    """Test failed scenario execution."""
    mock_device = AsyncMock()
    mock_device.set.side_effect = Exception("Failed")
    operator._devices["device1"] = mock_device

    result = await operator.execute_scenario(1)
    assert result is False
    assert mock_scenarist.get_scenario().last_executed is not None
    assert mock_scenarist.get_scenario().last_status is False


@pytest.mark.asyncio
async def test_scenario_validation(operator, mock_scenarist):
    """Test scenario validation before execution."""
    mock_scenarist.validate_action_params.return_value = False
    result = await operator.execute_scenario(1)
    assert result is False


@pytest.mark.asyncio
async def test_capability_checking(operator, mock_scenarist, mock_device_manager):
    """Test device capability checking before scenario execution."""
    mock_scenarist.get_scenario().action_params = {
        "device_id": "device1",
        "command": "set_mode",  # Not supported by S3
    }
    mock_device_manager.get_device_capabilities.return_value = {
        "fan_control": True,
        "heater_control": True,
        "temperature_control": True,
        "light_control": False,
        "mode_control": False,
    }

    result = await operator.execute_scenario(1)
    assert result is False


@pytest.mark.asyncio
async def test_time_based_trigger(operator):
    """Test time-based scenario triggers."""
    scenario = Scenario(
        id=1,
        name="Test Scenario",
        trigger_type="time",
        trigger_params={"start": "00:00", "end": "23:59"},  # Always active
        action_params={"device_id": "device1", "command": "turn_on"},
        is_active=True,
    )

    assert await operator._should_execute_scenario(scenario) is True


@pytest.mark.asyncio
async def test_sensor_based_trigger(operator):
    """Test sensor-based scenario triggers."""
    scenario = Scenario(
        id=1,
        name="Test Scenario",
        trigger_type="sensor",
        trigger_params={
            "device_id": "device1",
            "sensor": "fan_speed",
            "threshold": 3,
            "comparison": "gt",
        },
        action_params={"device_id": "device1", "command": "turn_on"},
        is_active=True,
    )

    operator._status_cache["device1"] = DeviceStatus(
        device_id="device1",
        state="on",
        fan_speed=4,  # Above threshold
        heater_status="on",
        last_updated=datetime.now(),
    )

    assert await operator._should_execute_scenario(scenario) is True


@pytest.mark.asyncio
async def test_operator_shutdown(operator):
    """Test proper resource cleanup during shutdown."""
    mock_device = AsyncMock()
    operator._devices["device1"] = mock_device
    operator._polling_task = asyncio.create_task(asyncio.sleep(3600))
    operator._scenario_task = asyncio.create_task(asyncio.sleep(3600))

    await operator.shutdown()
    assert mock_device.disconnect.called
    assert operator._polling_task.cancelled()
    assert operator._scenario_task.cancelled()
