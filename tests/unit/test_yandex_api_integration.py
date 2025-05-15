import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timedelta

from tion_btle.domain.device_manager.models import DeviceInfo
from tion_btle.operator import DeviceStatus
from tion_btle.scenarist import Scenario


@pytest.fixture
def app():
    """Create a test Flask app with mocked dependencies"""
    with patch("yandex_api_integration.device_manager"), \
         patch("yandex_api_integration.operator"), \
         patch("yandex_api_integration.scenarist"), \
         patch("yandex_api_integration.init_operator"), \
         patch("yandex_api_integration.threading.Thread"):

        # Import the app
        from yandex_api_integration import app

        # Configure app for testing
        app.config["TESTING"] = True

        # Remove the authentication middleware for testing
        app.before_request_funcs = {None: []}

        return app


@pytest.fixture
def client(app):
    """Create a test client for the Flask app"""
    return app.test_client()


@pytest.fixture
def mock_device():
    """Create a mock device for testing"""
    return DeviceInfo(
        id="test_device_1",
        name="Test Device 1",
        type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
        is_active=True,
        is_paired=True,
        room="Living Room"
    )


@pytest.fixture
def mock_device_status():
    """Create a mock device status for testing"""
    return DeviceStatus(
        device_id="test_device_1",
        state="on",
        fan_speed=3,
        heater_status="on",
        heater_temp=22,
        mode="outside",
        in_temp=18,
        out_temp=22,
        filter_remain=90.5,
        sound="off",
        light="off",
        last_updated=datetime.now()
    )


@pytest.fixture
def mock_scenario():
    """Create a mock scenario for testing"""
    return Scenario(
        id=1,
        name="Test Scenario",
        trigger_type="time",
        trigger_params={"start": "08:00", "end": "18:00"},
        action_params={"device_id": "test_device_1", "command": "turn_on"},
        is_active=True,
        created_at=datetime.now(),
        last_executed=datetime.now() - timedelta(days=1),
        execution_count=5,
        last_status=True
    )


@pytest.fixture
def auth_headers():
    """Create authorization headers for testing"""
    # Patch the check_authorization function to skip authentication
    with patch("yandex_api_integration.check_authorization", return_value=None), \
         patch("yandex_api_integration.validate_token_with_yandex", return_value=(True, "user123")):
        return {"Authorization": "Bearer test_token"}


def test_get_devices(client, auth_headers, mock_device):
    """Test the /devices endpoint"""
    with patch("yandex_api_integration.device_manager.get_devices", return_value=[mock_device]):
        response = client.get("/devices", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "devices" in data
        assert len(data["devices"]) == 1
        assert data["devices"][0]["id"] == mock_device.id
        assert data["devices"][0]["name"] == mock_device.name
        assert data["devices"][0]["type"] == "devices.types.ventilation"
        assert data["devices"][0]["room"] == mock_device.room
        assert "capabilities" in data["devices"][0]
        assert len(data["devices"][0]["capabilities"]) >= 2  # At least on/off and fan speed


def test_get_state(client, auth_headers, mock_device_status):
    """Test the /state endpoint"""
    with patch("yandex_api_integration.run_async", return_value=mock_device_status):
        request_data = {
            "devices": [
                {"id": "test_device_1"}
            ]
        }
        response = client.post("/state",
                              headers=auth_headers,
                              json=request_data,
                              content_type="application/json")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "devices" in data
        assert len(data["devices"]) == 1
        assert data["devices"][0]["id"] == "test_device_1"
        assert "capabilities" in data["devices"][0]

        # Check capabilities
        capabilities = data["devices"][0]["capabilities"]
        on_off_cap = next((c for c in capabilities if c["type"] == "devices.capabilities.on_off"), None)
        assert on_off_cap is not None
        assert on_off_cap["state"]["value"] is True

        fan_speed_cap = next((c for c in capabilities if c["type"] == "devices.capabilities.range" and
                             c["state"]["instance"] == "fan_speed"), None)
        assert fan_speed_cap is not None
        assert fan_speed_cap["state"]["value"] == 50.0  # 3 out of 6 = 50%


def test_action_on_off(client, auth_headers):
    """Test the /action endpoint for on/off capability"""
    with patch("yandex_api_integration.run_async", return_value=True):
        request_data = {
            "payload": {
                "devices": [
                    {
                        "id": "test_device_1",
                        "capabilities": [
                            {
                                "type": "devices.capabilities.on_off",
                                "state": {
                                    "instance": "on",
                                    "value": True
                                }
                            }
                        ]
                    }
                ]
            }
        }

        response = client.post("/action",
                              headers=auth_headers,
                              json=request_data,
                              content_type="application/json")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "devices" in data
        assert len(data["devices"]) == 1
        assert data["devices"][0]["id"] == "test_device_1"
        assert "capabilities" in data["devices"][0]
        assert len(data["devices"][0]["capabilities"]) == 1
        assert data["devices"][0]["capabilities"][0]["type"] == "devices.capabilities.on_off"
        assert data["devices"][0]["capabilities"][0]["state"]["status"] == "DONE"


def test_action_fan_speed(client, auth_headers):
    """Test the /action endpoint for fan speed capability"""
    with patch("yandex_api_integration.run_async", return_value=True):
        request_data = {
            "payload": {
                "devices": [
                    {
                        "id": "test_device_1",
                        "capabilities": [
                            {
                                "type": "devices.capabilities.range",
                                "state": {
                                    "instance": "fan_speed",
                                    "value": 50.0
                                }
                            }
                        ]
                    }
                ]
            }
        }

        response = client.post("/action",
                              headers=auth_headers,
                              json=request_data,
                              content_type="application/json")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "devices" in data
        assert data["devices"][0]["capabilities"][0]["type"] == "devices.capabilities.range"
        assert data["devices"][0]["capabilities"][0]["state"]["status"] == "DONE"


def test_action_temperature(client, auth_headers):
    """Test the /action endpoint for temperature capability"""
    with patch("yandex_api_integration.run_async", return_value=True):
        request_data = {
            "payload": {
                "devices": [
                    {
                        "id": "test_device_1",
                        "capabilities": [
                            {
                                "type": "devices.capabilities.range",
                                "state": {
                                    "instance": "temperature",
                                    "value": 22
                                }
                            }
                        ]
                    }
                ]
            }
        }

        response = client.post("/action",
                              headers=auth_headers,
                              json=request_data,
                              content_type="application/json")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["devices"][0]["capabilities"][0]["state"]["status"] == "DONE"


def test_action_mode(client, auth_headers):
    """Test the /action endpoint for mode capability"""
    with patch("yandex_api_integration.run_async", return_value=True):
        request_data = {
            "payload": {
                "devices": [
                    {
                        "id": "test_device_1",
                        "capabilities": [
                            {
                                "type": "devices.capabilities.mode",
                                "state": {
                                    "instance": "work_mode",
                                    "value": "recirculation"
                                }
                            }
                        ]
                    }
                ]
            }
        }

        response = client.post("/action",
                              headers=auth_headers,
                              json=request_data,
                              content_type="application/json")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["devices"][0]["capabilities"][0]["state"]["status"] == "DONE"


def test_action_complex_mode(client, auth_headers):
    """Test the /action endpoint for complex mode capability"""
    with patch("yandex_api_integration.run_async", return_value=True):
        request_data = {
            "payload": {
                "devices": [
                    {
                        "id": "test_device_1",
                        "capabilities": [
                            {
                                "type": "devices.capabilities.mode",
                                "state": {
                                    "instance": "work_mode",
                                    "value": "тихий"
                                }
                            }
                        ]
                    }
                ]
            }
        }

        response = client.post("/action",
                              headers=auth_headers,
                              json=request_data,
                              content_type="application/json")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["devices"][0]["capabilities"][0]["state"]["status"] == "DONE"


def test_get_scenarios(client, auth_headers, mock_scenario):
    """Test the GET /scenarios endpoint"""
    with patch("yandex_api_integration.scenarist.get_scenarios", return_value=[mock_scenario]):
        response = client.get("/scenarios", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "scenarios" in data
        assert len(data["scenarios"]) == 1
        assert data["scenarios"][0]["id"] == mock_scenario.id
        assert data["scenarios"][0]["name"] == mock_scenario.name
        assert data["scenarios"][0]["trigger_type"] == mock_scenario.trigger_type
        assert data["scenarios"][0]["is_active"] == mock_scenario.is_active
        assert data["scenarios"][0]["execution_count"] == mock_scenario.execution_count
        assert data["scenarios"][0]["last_status"] == mock_scenario.last_status


def test_execute_scenario(client, auth_headers):
    """Test the POST /scenarios endpoint"""
    with patch("yandex_api_integration.run_async", return_value=True):
        request_data = {
            "scenario_id": 1
        }

        response = client.post("/scenarios",
                              headers=auth_headers,
                              json=request_data,
                              content_type="application/json")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "success" in data
        assert data["success"] is True
        assert data["scenario_id"] == 1


def test_auth_required(client):
    """Test that authentication is required for all endpoints"""
    # Temporarily restore the authentication middleware
    from yandex_api_integration import app, check_authorization

    # Save the current before_request functions
    original_before_request = app.before_request_funcs.copy()

    try:
        # Add back the check_authorization function
        if None not in app.before_request_funcs:
            app.before_request_funcs[None] = []
        app.before_request_funcs[None].append(check_authorization)

        endpoints = [
            ("/devices", "GET"),
            ("/state", "POST"),
            ("/action", "POST"),
            ("/scenarios", "GET"),
            ("/scenarios", "POST")
        ]

        for endpoint, method in endpoints:
            if method == "GET":
                response = client.get(endpoint)
            else:
                response = client.post(endpoint, json={})

            assert response.status_code == 401, f"Expected 401 for {method} {endpoint}, got {response.status_code}"
    finally:
        # Restore the original before_request functions
        app.before_request_funcs = original_before_request


def test_invalid_token(client):
    """Test that invalid tokens are rejected"""
    # Temporarily restore the authentication middleware
    from yandex_api_integration import app, check_authorization

    # Save the current before_request functions
    original_before_request = app.before_request_funcs.copy()

    try:
        # Add back the check_authorization function
        if None not in app.before_request_funcs:
            app.before_request_funcs[None] = []
        app.before_request_funcs[None].append(check_authorization)

        with patch("yandex_api_integration.validate_token_with_yandex", return_value=(False, None)):
            headers = {"Authorization": "Bearer invalid_token"}
            response = client.get("/devices", headers=headers)
            assert response.status_code == 403
    finally:
        # Restore the original before_request functions
        app.before_request_funcs = original_before_request
