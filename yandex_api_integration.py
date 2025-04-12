from flask import Flask, request, jsonify, abort
from tion_btle.device_manager import DeviceInfo, DeviceManager
import requests
from datetime import datetime, timedelta
from tion_btle.scenarist import Scenarist
from typing import List, Dict

import logging

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

app = Flask(__name__)
device_manager = DeviceManager()

DB_PATH = "devices.db"


# Initialize managers
device_manager = DeviceManager()
scenarist = Scenarist(device_manager.db_path)

# Словарь для хранения состояний устройств
device_states = {}

# Кэш для токенов
token_cache = {}

# Конфигурация
YANDEX_OAUTH_INFO_URL = "https://login.yandex.ru/info"
CACHE_EXPIRATION = timedelta(hours=1)  # Время жизни токена в кэше


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


# Маршрут для получения состояния устройств
@app.route("/state", methods=["POST"])
def get_state():
    # TODO: Получить актуальное состояние известных устройств (из кеша)
    return


# Маршрут для выполнения команд
@app.route("/action", methods=["POST"])
def action():
    # TODO: Выполнить действие над устройтом
    return
