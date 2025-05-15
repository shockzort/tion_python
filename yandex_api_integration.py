from flask import Flask, request, jsonify, abort
from tion_btle.domain.device_manager.models import DeviceInfo
from tion_btle.domain.device_manager.sqlite_storage import SQLiteDeviceStorage
from tion_btle.domain.device_manager.device_manager import DeviceManager
import requests
import asyncio
from datetime import datetime, timedelta
from tion_btle.scenarist import Scenarist
from tion_btle.operator import Operator
from typing import List, Dict, Any, Optional

import logging

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

app = Flask(__name__)

DB_PATH = "devices.db"

# Initialize storage
device_storage = SQLiteDeviceStorage(DB_PATH)
group_storage = SQLiteDeviceStorage(DB_PATH)

# Initialize managers
device_manager = DeviceManager(device_storage, group_storage)
scenarist = Scenarist(DB_PATH)
operator = Operator(DB_PATH)

# Initialize operator in background
loop = asyncio.new_event_loop()

def init_operator():
    asyncio.set_event_loop(loop)
    loop.run_until_complete(operator.initialize())
    loop.run_until_complete(operator.start_polling(interval=60))
    loop.run_until_complete(operator.run_scenarios())
    _LOGGER.info("Operator initialized and polling started")

import threading
threading.Thread(target=init_operator, daemon=True).start()

# Кэш для токенов
token_cache = {}

# Конфигурация
YANDEX_OAUTH_INFO_URL = "https://login.yandex.ru/info"
CACHE_EXPIRATION = timedelta(hours=1)  # Время жизни токена в кэше

# Маппинг режимов для Яндекс Алисы
MODE_MAPPING = {
    "auto": "auto",
    "manual": "outside",
    "recirculation": "recirculation",
    "mixed": "mixed",
    "тихий": {"fan_speed": 1},
    "турбо": {"fan_speed": 6},
    "ночной": {"fan_speed": 1, "sound": "off"},
    "проветривание": {"fan_speed": 4, "mode": "outside"}
}


# Функция для валидации токена через API Яндекса
def validate_token_with_yandex(token):
    try:
        response = requests.get(
            YANDEX_OAUTH_INFO_URL, headers={"Authorization": f"OAuth {token}"}
        )
        if response.status_code == 200:
            return True, response.json().get("id")  # Возвращаем ID пользователя
        else:
            return False, None
    except Exception as e:
        print(f"Error validating token: {e}")
        return False, None


# Middleware для проверки авторизации
@app.before_request
def check_authorization():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        abort(401, description="Missing or invalid Authorization header")

    token = auth_header.split(" ")[1]

    # Проверяем кэш
    if token in token_cache:
        cache_entry = token_cache[token]
        if datetime.now() < cache_entry["expires_at"]:
            return  # Токен валиден и находится в кэше

    # Если токен отсутствует в кэше или истек, проверяем его через API Яндекса
    is_valid, user_id = validate_token_with_yandex(token)
    if not is_valid:
        abort(403, description="Invalid token")

    # Сохраняем токен в кэше
    token_cache[token] = {
        "user_id": user_id,
        "expires_at": datetime.now() + CACHE_EXPIRATION,
    }


# Получить список возможностей устройства в формате Yandex Smart Home
def get_device_capabilities(device: DeviceInfo) -> List[Dict]:
    """Generate Yandex Smart Home capabilities based on device model"""
    base_caps = [
        {
            "type": "devices.capabilities.on_off",
            "retrievable": True,
            "reportable": True,
        },
        {
            "type": "devices.capabilities.range",
            "parameters": {
                "instance": "fan_speed",
                "unit": "unit.percent",
                "range": {"min": 1, "max": 6, "precision": 1},
            },
            "retrievable": True,
            "reportable": True,
        },
    ]

    # Add temperature control for devices with heaters
    if "S3" in device.model or "S4" in device.model:
        base_caps.append(
            {
                "type": "devices.capabilities.range",
                "parameters": {
                    "instance": "temperature",
                    "unit": "unit.temperature.celsius",
                    "range": {"min": 10, "max": 30, "precision": 1},
                },
                "retrievable": True,
                "reportable": True,
            }
        )

    # Add mode control for devices with recirculation
    if "S3" in device.model:
        base_caps.append(
            {
                "type": "devices.capabilities.mode",
                "parameters": {
                    "instance": "work_mode",
                    "modes": [
                        {"value": "auto"},
                        {"value": "manual"},
                        {"value": "recirculation"},
                    ],
                },
                "retrievable": True,
                "reportable": True,
            }
        )

    return base_caps


# Получить список зарегистрированных устройств и их возможностей
@app.route("/devices", methods=["GET"])
def get_devices():
    """Return all registered devices with their capabilities"""
    devices = []
    for device in device_manager.get_devices():
        devices.append(
            {
                "id": device.id,
                "name": device.name,
                "type": "devices.types.ventilation",
                "capabilities": get_device_capabilities(device),
                "room": getattr(device, "room", "Unknown"),
            }
        )
    return jsonify({"devices": devices})


# Преобразование состояния устройства в формат Яндекс Умного дома
def device_status_to_yandex(device_id: str, status: dict) -> Dict[str, Any]:
    """Convert device status to Yandex Smart Home format"""
    capabilities = []

    # On/Off capability
    capabilities.append({
        "type": "devices.capabilities.on_off",
        "state": {
            "instance": "on",
            "value": status.get("state", "off") == "on"
        }
    })

    # Fan speed capability
    capabilities.append({
        "type": "devices.capabilities.range",
        "state": {
            "instance": "fan_speed",
            "value": status.get("fan_speed", 0) * 100 / 6  # Convert to percentage (0-100)
        }
    })

    # Temperature capability (if supported)
    if "heater_temp" in status:
        capabilities.append({
            "type": "devices.capabilities.range",
            "state": {
                "instance": "temperature",
                "value": status.get("heater_temp", 0)
            }
        })

    # Mode capability (if supported)
    if "mode" in status:
        mode_value = "manual"
        if status["mode"] == "recirculation":
            mode_value = "recirculation"
        elif status["mode"] == "mixed":
            mode_value = "mixed"

        capabilities.append({
            "type": "devices.capabilities.mode",
            "state": {
                "instance": "work_mode",
                "value": mode_value
            }
        })

    return {
        "id": device_id,
        "capabilities": capabilities
    }

# Асинхронный вызов методов оператора
def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, loop).result()

# Маршрут для получения состояния устройств
@app.route("/state", methods=["POST"])
def get_state():
    """Get current state of devices in Yandex Smart Home format"""
    try:
        request_data = request.get_json()
        _LOGGER.debug(f"State request: {request_data}")

        if not request_data or "devices" not in request_data:
            return jsonify({"error": "Invalid request format"}), 400

        device_ids = [device["id"] for device in request_data["devices"]]
        response_devices = []

        for device_id in device_ids:
            try:
                # Get device status from operator
                status = run_async(operator.get_device_status(device_id))

                if status:
                    # Convert to dict for easier handling
                    status_dict = {
                        "state": status.state,
                        "fan_speed": status.fan_speed,
                        "heater": status.heater_status,
                        "heater_temp": status.heater_temp,
                        "mode": status.mode,
                        "in_temp": status.in_temp,
                        "out_temp": status.out_temp,
                        "filter_remain": status.filter_remain,
                        "sound": status.sound,
                        "light": status.light
                    }

                    response_devices.append(device_status_to_yandex(device_id, status_dict))
                else:
                    _LOGGER.warning(f"Device {device_id} not found or not connected")
                    response_devices.append({
                        "id": device_id,
                        "error_code": "DEVICE_UNREACHABLE"
                    })
            except Exception as e:
                _LOGGER.error(f"Error getting state for device {device_id}: {str(e)}")
                response_devices.append({
                    "id": device_id,
                    "error_code": "INTERNAL_ERROR"
                })

        return jsonify({
            "devices": response_devices
        })
    except Exception as e:
        _LOGGER.error(f"Error processing state request: {str(e)}")
        return jsonify({"error": str(e)}), 500


# Маршрут для выполнения команд
@app.route("/action", methods=["POST"])
def action():
    """Execute commands on devices"""
    try:
        request_data = request.get_json()
        _LOGGER.debug(f"Action request: {request_data}")

        if not request_data or "payload" not in request_data:
            return jsonify({"error": "Invalid request format"}), 400

        payload = request_data["payload"]
        if "devices" not in payload:
            return jsonify({"error": "No devices specified"}), 400

        response_devices = []

        for device in payload["devices"]:
            device_id = device["id"]
            capabilities = device.get("capabilities", [])

            device_response = {"id": device_id, "capabilities": []}

            for capability in capabilities:
                capability_type = capability.get("type")
                capability_response = {
                    "type": capability_type,
                    "state": {"status": "ERROR"}
                }

                try:
                    if capability_type == "devices.capabilities.on_off":
                        # Handle on/off commands
                        value = capability["state"]["value"]
                        state = "on" if value else "off"
                        success = run_async(operator.set_device_state(device_id, state))
                        capability_response["state"]["status"] = "DONE" if success else "ERROR"

                    elif capability_type == "devices.capabilities.range":
                        # Handle range commands (fan speed, temperature)
                        instance = capability["state"]["instance"]
                        value = capability["state"]["value"]

                        if instance == "fan_speed":
                            # Convert percentage to fan speed (1-6)
                            fan_speed = max(1, min(6, round(value * 6 / 100)))
                            success = run_async(operator.set_fan_speed(device_id, fan_speed))
                        elif instance == "temperature":
                            # Set heater temperature
                            temp = max(10, min(30, int(value)))
                            success = run_async(operator.set_heater_temp(device_id, temp))
                            # Also ensure heater is on
                            run_async(operator.set_heater_state(device_id, "on"))
                        else:
                            success = False

                        capability_response["state"]["status"] = "DONE" if success else "ERROR"

                    elif capability_type == "devices.capabilities.mode":
                        # Handle mode commands
                        instance = capability["state"]["instance"]
                        value = capability["state"]["value"]

                        if instance == "work_mode":
                            if value in MODE_MAPPING:
                                mode_config = MODE_MAPPING[value]
                                success = True

                                if isinstance(mode_config, dict):
                                    # Handle complex modes like "тихий", "турбо", etc.
                                    for param, param_value in mode_config.items():
                                        if param == "fan_speed":
                                            success = success and run_async(operator.set_fan_speed(device_id, param_value))
                                        elif param == "mode":
                                            success = success and run_async(operator.set_mode(device_id, param_value))
                                        elif param == "sound":
                                            success = success and run_async(operator.set_sound(device_id, param_value))
                                else:
                                    # Handle simple modes like "manual", "recirculation", etc.
                                    success = run_async(operator.set_mode(device_id, mode_config))
                            else:
                                success = False

                            capability_response["state"]["status"] = "DONE" if success else "ERROR"

                    device_response["capabilities"].append(capability_response)

                except Exception as e:
                    _LOGGER.error(f"Error executing capability {capability_type} for device {device_id}: {str(e)}")
                    capability_response["state"]["status"] = "ERROR"
                    capability_response["state"]["error_code"] = "INTERNAL_ERROR"
                    device_response["capabilities"].append(capability_response)

            response_devices.append(device_response)

        return jsonify({
            "devices": response_devices
        })
    except Exception as e:
        _LOGGER.error(f"Error processing action request: {str(e)}")
        return jsonify({"error": str(e)}), 500


# Маршрут для выполнения сценариев
@app.route("/scenarios", methods=["POST"])
def execute_scenario():
    """Execute a scenario by ID"""
    try:
        request_data = request.get_json()
        scenario_id = request_data.get("scenario_id")

        if not scenario_id:
            return jsonify({"error": "No scenario ID provided"}), 400

        success = run_async(operator.execute_scenario(scenario_id))

        return jsonify({
            "success": success,
            "scenario_id": scenario_id
        })
    except Exception as e:
        _LOGGER.error(f"Error executing scenario: {str(e)}")
        return jsonify({"error": str(e)}), 500


# Маршрут для получения списка сценариев
@app.route("/scenarios", methods=["GET"])
def get_scenarios():
    """Get list of available scenarios"""
    try:
        scenarios = scenarist.get_scenarios()
        result = []

        for scenario in scenarios:
            result.append({
                "id": scenario.id,
                "name": scenario.name,
                "trigger_type": scenario.trigger_type,
                "trigger_params": scenario.trigger_params,
                "action_params": scenario.action_params,
                "is_active": scenario.is_active,
                "last_executed": scenario.last_executed.isoformat() if scenario.last_executed else None,
                "execution_count": scenario.execution_count,
                "last_status": scenario.last_status
            })

        return jsonify({"scenarios": result})
    except Exception as e:
        _LOGGER.error(f"Error getting scenarios: {str(e)}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
