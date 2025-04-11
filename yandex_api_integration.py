from flask import Flask, request, jsonify, abort
from tion_btle import TionS4 as Breezer
import requests
from datetime import datetime, timedelta
from time import sleep
import sqlite3
import asyncio
import logging

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

app = Flask(__name__)

# Подключение к SQLite базе данных
DB_PATH = "devices.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            name TEXT,
            type TEXT,
            is_registered INTEGER
        )
    """
    )
    conn.commit()
    conn.close()


# Функция для сохранения устройства в базе данных
def save_device(device_id, device_name, device_type):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO devices (id, name, type, is_registered)
        VALUES (?, ?, ?, 1)
    """,
        (device_id, device_name, device_type),
    )
    conn.commit()
    conn.close()


def get_current_devices():
    return []


# Функция для загрузки устройств из базы данных
def load_devices():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, type FROM devices WHERE is_registered = 1")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": row[0], "name": row[1], "type": row[2]} for row in rows]


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


# Автоматический поиск устройств
def discover_devices():
    discovered_devices = []
    for device in get_current_devices():
        discovered_devices.append(
            {
                "id": device.id,
                "name": f"Tion {device.id}",
                "type": "devices.types.ventilation",
            }
        )
    return discovered_devices


# Маршрут для поиска и регистрации устройств
@app.route("/register", methods=["POST"])
def register_devices():
    discovered_devices = discover_devices()
    for device in discovered_devices:
        save_device(device["id"], device["name"], device["type"])
    return jsonify({"status": "success", "registered_devices": discovered_devices})


# Маршрут для получения списка зарегистрированных устройств
@app.route("/devices", methods=["GET"])
def get_devices():
    registered_devices = load_devices()
    discovered_devices = []
    for device in registered_devices:
        discovered_devices.append(
            {
                "id": device["id"],
                "name": device["name"],
                "type": device["type"],
                "capabilities": [
                    {
                        "type": "devices.capabilities.on_off",
                        "retrievable": True,
                        "reportable": True,
                    },
                    {
                        "type": "devices.capabilities.range",
                        "parameters": {
                            "instance": "temperature",
                            "unit": "unit.temperature.celsius",
                            "range": {"min": 10, "max": 30, "precision": 1},
                        },
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
                    {
                        "type": "devices.capabilities.mode",
                        "parameters": {
                            "instance": "work_mode",
                            "modes": [{"value": "auto"}, {"value": "manual"}],
                        },
                        "retrievable": True,
                        "reportable": True,
                    },
                    {
                        "type": "devices.capabilities.timer",
                        "parameters": {
                            "instance": "off_timer",
                            "unit": "unit.seconds",
                            "range": {"min": 0, "max": 3600},
                        },
                        "retrievable": True,
                        "reportable": True,
                    },
                ],
            }
        )
    return jsonify({"devices": discovered_devices})


# Функция для обновления состояния устройств
def update_device_state(device_id):
    device = next((d for d in get_current_devices() if d.id == device_id), None)
    if device:
        state = {
            "id": device_id,
            "is_on": device.is_on,
            "temperature": device.temperature,
            "speed": device.speed,
            "mode": device.mode,  # Режим работы (например, "auto", "manual")
            "timer": device.timer,  # Таймер (если есть)
        }
        device_states[device_id] = state
        return state
    return None


# Маршрут для получения состояния устройств
@app.route("/state", methods=["POST"])
def get_state():
    states = []
    for device_id in device_states:
        state = update_device_state(device_id)
        if state:
            states.append(
                {
                    "id": device_id,
                    "capabilities": [
                        {
                            "type": "devices.capabilities.on_off",
                            "state": {"instance": "on", "value": state["is_on"]},
                        },
                        {
                            "type": "devices.capabilities.range",
                            "state": {
                                "instance": "temperature",
                                "value": state["temperature"],
                            },
                        },
                        {
                            "type": "devices.capabilities.range",
                            "state": {"instance": "fan_speed", "value": state["speed"]},
                        },
                        {
                            "type": "devices.capabilities.mode",
                            "state": {"instance": "work_mode", "value": state["mode"]},
                        },
                        {
                            "type": "devices.capabilities.timer",
                            "state": {"instance": "off_timer", "value": state["timer"]},
                        },
                    ],
                }
            )
    return jsonify({"devices": states})


# Маршрут для выполнения команд
@app.route("/action", methods=["POST"])
def action():
    data = request.json
    device_id = data["payload"]["devices"][0]["id"]
    device = next((d for d in get_current_devices() if d.id == device_id), None)

    if not device:
        return jsonify({"error_code": "DEVICE_NOT_FOUND"}), 404

    for capability in data["payload"]["devices"][0]["capabilities"]:
        instance = capability["state"]["instance"]
        value = capability["state"]["value"]

        if instance == "on":
            device.turn_on() if value else device.turn_off()
        elif instance == "temperature":
            device.set_temperature(value)
        elif instance == "fan_speed":
            device.set_speed(value)
        elif instance == "work_mode":
            device.set_mode(value)  # Установка режима ("auto", "manual")
        elif instance == "off_timer":
            device.set_timer(value)  # Установка таймера

    update_device_state(device_id)
    return jsonify({"status": "success"})


def mac_list() -> list:
    return ["14:90:A4:9F:82:EC", "D4:EA:F7:0E:60:D0", "B5:31:13:4E:B5:EB"]


async def main_loop():
    while True:

        # Инициализация API Tion
        for mac in mac_list():
            api = Breezer(mac)

            results = await asyncio.gather(api.pair())
            for res in results:
                for line in res:
                    _LOGGER.info(line)

            sleep(1.0)


if __name__ == "__main__":
    # init_db()  # Инициализация базы данных при запуске
    # app.run(host="0.0.0.0", port=5000)
    asyncio.run(main_loop())

