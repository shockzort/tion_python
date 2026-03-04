# TION-001: План разработки сервиса интеграции Tion + Яндекс Алиса

Date: 2026-03-04
Status: Awaiting approval
Author: architect agent

---

## Фазы разработки

### Фаза 0: Критические исправления (Must Fix — перед любым новым кодом)

Эта фаза устраняет нарушения конвенций CLAUDE.md и блокирующие архитектурные проблемы. Ничего нового не добавляется — только исправление существующего кода.

---

#### 0.1. Заменить `requests` на `httpx` в OAuth middleware

**Файлы:**
- `yandex_api_integration.py` (modify)
- `requirements.txt` (modify)

**Что делать:**
- Удалить `import requests`
- Добавить `import httpx`
- Переписать `validate_token_with_yandex()` как `async def validate_token_with_yandex(token: str) -> tuple[bool, str | None]`
- Заменить `requests.get(...)` на `await httpx.AsyncClient().get(...)` с явным `timeout=5.0`
- Добавить `httpx` в `requirements.txt`
- Удалить `requests` из зависимостей

**Почему критично:** `requests` — синхронный HTTP-клиент. CLAUDE.md явно запрещает синхронные HTTP-запросы в asyncio-контексте. Flask middleware блокирует весь event loop при недоступности Яндекс API.

**Критерии готовности:**
- `requests` отсутствует в кодовой базе
- `validate_token_with_yandex` — корректная async-функция
- Тест `test_yandex_api_integration.py` проходит
- OAuth middleware вызывает async-функцию через `run_async()`

---

#### 0.2. Вынести секреты в `.env` + `python-dotenv`

**Файлы:**
- `yandex_api_integration.py` (modify)
- `.env.example` (create)
- `requirements.txt` (modify)
- `.gitignore` (modify)

**Что делать:**
- Добавить `python-dotenv` в `requirements.txt`
- Создать `.env.example` с переменными: `DB_PATH`, `YANDEX_OAUTH_INFO_URL`, `HOST`, `PORT`, `DEBUG`
- В `yandex_api_integration.py` добавить `from dotenv import load_dotenv` и `load_dotenv()`
- Заменить хардкод `"devices.db"`, `"https://login.yandex.ru/info"` на `os.getenv()`
- Добавить `.env` в `.gitignore`

**Критерии готовности:**
- Нет хардкода секретов и конфигурации в коде
- `.env` в `.gitignore`
- `.env.example` задокументирован

---

#### 0.3. Устранить `except Exception:` без полноценного логирования

**Файлы:**
- `yandex_api_integration.py` (modify)

**Что делать:**
- В `validate_token_with_yandex()`: заменить `print(f"Error validating token: {e}")` на `_LOGGER.error("Token validation failed: %s", e, exc_info=True)`
- Убедиться, что все `except Exception as e` в роутах логируют с `exc_info=True`
- Удалить `print()` вызовы из `automation.py`

**Критерии готовности:**
- Нет `print()` в production-коде
- Все `except Exception` логируют с `exc_info=True`
- Линтер (`ruff`) не показывает ошибок

---

#### 0.4. Создать `pyproject.toml` с конфигурацией инструментов

**Файлы:**
- `pyproject.toml` (create)

**Что делать:**
- Добавить секции `[tool.black]` (line-length = 88), `[tool.isort]` (profile = "black"), `[tool.ruff]`, `[tool.mypy]` (strict = true, python_version = "3.10")
- Добавить в `requirements_test.txt`: `black`, `isort`, `ruff`, `mypy`, `pytest-mock`, `pytest-cov`

**Критерии готовности:**
- `black --check .` проходит без ошибок
- `ruff check .` проходит без ошибок
- `isort --check .` проходит без ошибок
- `pyproject.toml` зафиксирован в репозитории

---

#### 0.5. Исправить CI: добавить domain tests в GitHub Actions

**Файлы:**
- `.github/workflows/tests.yml` (modify)

**Что делать:**
- Добавить `tion_btle/domain/device_manager/tests/` в команду `pytest`
- Итоговая команда: `pytest tests/unit tion_btle/domain/device_manager/tests/ --cov=tion_btle --cov=yandex_api_integration`

**Критерии готовности:**
- CI запускает все unit-тесты включая domain tests
- Coverage report присутствует в артефактах CI

---

### Фаза 1: Must Have — ядро интеграции с Яндекс Алисой

После завершения Фазы 0. Реализуем функциональность, без которой MVP невозможен.

---

#### 1.1. Создать `main.py` — единую точку входа

**Файлы:**
- `main.py` (create)

**Что делать:**
- Создать единую точку входа, которая:
  - Загружает `.env` через `python-dotenv`
  - Инициализирует логирование (JSON-формат, ротация по размеру)
  - Запускает `asyncio` event loop
  - Запускает Flask через `asyncio`-совместимый WSGI-сервер (см. решение 1.1.a ниже)
  - Регистрирует `signal.SIGTERM` / `SIGINT` для graceful shutdown через `operator.shutdown()`

**Техническое решение (1.1.a) — смена архитектуры Flask + asyncio:**
Текущая архитектура (Flask синхронный + asyncio в отдельном потоке через `threading.Thread`) — хрупкая. Рекомендуемый переход: **FastAPI + uvicorn**. FastAPI — нативно asyncio, устраняет проблему смешивания синхронного/асинхронного кода, позволяет напрямую вызывать `await operator.method()` из роутов без `run_coroutine_threadsafe`. Переход — в рамках этой подзадачи.

**Файлы при переходе на FastAPI:**
- `main.py` (create)
- `api/` (create directory)
- `api/__init__.py` (create)
- `api/app.py` (create) — FastAPI app, lifespan для инициализации Operator
- `api/routes/` (create directory)
- `api/routes/yandex.py` (create) — роуты Yandex Smart Home API
- `api/routes/devices.py` (create) — роуты управления устройствами
- `api/middleware/auth.py` (create) — async OAuth middleware
- `api/schemas.py` (create) — Pydantic-модели запросов/ответов
- `yandex_api_integration.py` (keep) — оставить для обратной совместимости до завершения миграции
- `requirements.txt` (modify) — добавить `fastapi`, `uvicorn[standard]`, `httpx`

**Критерии готовности:**
- `python main.py` запускает сервер
- Graceful shutdown при SIGTERM отключает BLE-устройства
- Логи в JSON-формате

---

#### 1.2. Исправить маршруты API под спецификацию Yandex Smart Home v1

**Файлы:**
- `api/routes/yandex.py` (create/modify)

**Что делать:**
Реализовать роуты в соответствии со спецификацией Яндекс Умного дома:

```
GET  /v1.0/user/devices          → список устройств с capabilities
POST /v1.0/user/devices/query    → запрос состояния устройств
POST /v1.0/user/devices/action   → выполнение команд
POST /v1.0/user/devices/unlink   → отзыв доступа (возвращает 200 OK)
HEAD /v1.0/                      → ping от Яндекса (возвращает 200 OK)
```

**Маппинг существующего кода:**
- `/devices` → `/v1.0/user/devices` (GET)
- `/state` (POST) → `/v1.0/user/devices/query` (POST)
- `/action` (POST) → `/v1.0/user/devices/action` (POST)

**Схема ответа `/v1.0/user/devices`:**
```json
{
  "request_id": "<UUID из заголовка X-Request-Id>",
  "payload": {
    "user_id": "<Yandex user ID>",
    "devices": [...]
  }
}
```

**Критерии готовности:**
- Все 5 endpoints реализованы и возвращают корректный HTTP статус
- `request_id` берётся из заголовка `X-Request-Id` Яндекса
- Формат ответов соответствует документации Yandex Smart Home API v1.0

---

#### 1.3. Добавить HTTP endpoints для управления устройствами

**Файлы:**
- `api/routes/devices.py` (create)

**Что делать:**
Реализовать REST endpoints:

```
POST /api/devices/discover        → запустить BLE-сканирование, вернуть найденные устройства
POST /api/devices/register        → зарегистрировать устройство по MAC/имени
GET  /api/devices                 → список зарегистрированных устройств
GET  /api/devices/{id}            → детали устройства
DELETE /api/devices/{id}          → мягкое удаление устройства
POST /api/devices/{id}/pair       → сопряжение устройства
```

**Что вызывать:**
- `device_manager.discover_devices()` → список `BLEDevice`
- `device_manager.register_device(name, mac, model, room)` → `DeviceInfo`
- `device_manager.delete_device(device_id)` → soft delete

**Pydantic-схемы:**
```python
class DiscoverResponse(BaseModel):
    devices: list[BLEDeviceSchema]

class RegisterRequest(BaseModel):
    name: str
    mac_address: str
    model: str
    room: str | None = None
    auto_pair: bool = False
```

**Критерии готовности:**
- Все 6 endpoints работают
- `POST /api/devices/discover` возвращает список BLE-устройств за 30 сек или таймаут
- `DELETE /api/devices/{id}` не удаляет физически, устанавливает `is_active=False`
- Тесты покрывают все endpoints

---

#### 1.4. Реализовать `POST callback` — push-уведомления Яндексу

**Файлы:**
- `api/routes/yandex.py` (modify)
- `tion_btle/operator.py` (modify)

**Что делать:**
При изменении состояния устройства (polling обнаружил изменение) — отправить уведомление в Яндекс:

```
POST https://dialogs.yandex.net/api/v1/skills/{skill_id}/callback/state
Authorization: OAuth {oauth_token}
Body: {
  "ts": <timestamp>,
  "payload": {
    "user_id": "<user_id>",
    "devices": [<device_state>]
  }
}
```

**Реализация:**
- В `Operator._poll_devices()`: сравнивать текущий статус с кешированным, при изменении — ставить задачу в очередь callback
- Создать `YandexCallbackSender` — класс, который принимает очередь изменений и отправляет через `httpx.AsyncClient`
- Конфигурация: `YANDEX_SKILL_ID` и `YANDEX_OAUTH_TOKEN` из `.env`

**Критерии готовности:**
- При изменении `fan_speed` или `state` устройства — callback отправляется в Яндекс
- При недоступности Яндекс API — ошибка логируется, но polling продолжается
- Тест мокирует `httpx.AsyncClient.post`

---

#### 1.5. Добавить таймауты на BLE-операции `get()` и `set()`

**Файлы:**
- `tion_btle/operator.py` (modify)

**Что делать:**
В методах `get_device_status()`, `set_device_state()`, `set_fan_speed()`, `set_heater_state()`, `set_heater_temp()`, `set_mode()`, `set_sound()`, `set_light()`:
```python
BLE_OPERATION_TIMEOUT = float(os.getenv("BLE_OPERATION_TIMEOUT", "10.0"))

status = await asyncio.wait_for(
    tion.get(),
    timeout=BLE_OPERATION_TIMEOUT
)
```

**Критерии готовности:**
- Все BLE-операции защищены `asyncio.wait_for`
- `asyncio.TimeoutError` перехватывается явно и логируется
- `BLE_OPERATION_TIMEOUT` конфигурируется через `.env`

---

#### 1.6. Удалить/мигрировать `automation.py`

**Файлы:**
- `automation.py` (delete или archive)

**Что делать:**
- Проверить, что вся функциональность `automation.py` присутствует в `Scenarist`
- Удалить файл (функциональность полностью дублируется `Scenarist`)
- Добавить импорт `Scenarist` везде, где использовался `AutomationManager`

**Критерии готовности:**
- `automation.py` отсутствует в репозитории
- Нет импортов `AutomationManager` нигде в коде
- `ruff` не показывает orphaned imports

---

### Фаза 2: Should Have — веб-интерфейс и инфраструктура

После завершения Фазы 1. Добавляем веб-интерфейс и улучшаем операционную зрелость.

---

#### 2.1. Групповые команды через API

**Файлы:**
- `api/routes/groups.py` (create)
- `tion_btle/operator.py` (modify)

**Что делать:**
```
POST /api/groups                   → создать группу
GET  /api/groups                   → список групп
GET  /api/groups/{id}              → детали группы
PUT  /api/groups/{id}              → обновить группу
DELETE /api/groups/{id}            → удалить группу
POST /api/groups/{id}/action       → групповая команда (параллельно всем устройствам группы)
```

В `Operator` добавить `set_group_state(group_id, action)` — выполняет `asyncio.gather(*[set_device_state(dev_id, ...) for dev_id in group.device_ids])`.

**Критерии готовности:**
- Групповая команда выполняется параллельно на все устройства группы
- Результат возвращает статус по каждому устройству отдельно

---

#### 2.2. MQTT-интеграция для сторонних датчиков

**Файлы:**
- `tion_btle/mqtt_client.py` (create)
- `requirements.txt` (modify) — добавить `aiomqtt` или `asyncio-mqtt`

**Что делать:**
- Создать `MqttSensorClient` — asyncio-клиент, подписывается на топики датчиков
- Интерфейс: `ISensorDataSource` с методом `get_sensor_data(device_id: str) -> SensorData | None`
- `SensorData` dataclass: `co2: int | None`, `temperature: float | None`, `humidity: float | None`
- Передавать в `Operator` при инициализации как зависимость
- Конфигурация через `.env`: `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_TOPIC_PREFIX`

**Критерии готовности:**
- При CO₂ > 1000 ppm — сценарий "турбо" срабатывает автоматически
- MQTT недоступен → сервис продолжает работу, логирует WARNING

---

#### 2.3. Веб-интерфейс: базовый CRUD устройств

**Файлы:**
- `web/` (create directory)
- `web/templates/` (create)
- `web/templates/base.html` (create)
- `web/templates/devices.html` (create)
- `web/static/` (create)
- `api/routes/web.py` (create) — роуты для веб-интерфейса

**Стек:** Jinja2 (уже в зависимостях FastAPI) + минимальный CSS (без JS-фреймворков).

**Функциональность:**
- Список устройств с текущим статусом
- Кнопка "Сканировать BLE" → вызывает `/api/devices/discover`
- Форма добавления устройства → вызывает `/api/devices/register`
- Удаление устройства

**Критерии готовности:**
- Доступен на `http://localhost:5000/web/devices`
- Не требует JS-фреймворков (только vanilla JS или htmx для async-запросов)
- Работает без интернета (CSS из статики)

---

#### 2.4. JSON-логирование с ротацией

**Файлы:**
- `main.py` (modify)
- `tion_btle/logging_config.py` (create)

**Что делать:**
- Создать функцию `setup_logging(log_dir: str) -> None`
- Использовать `logging.handlers.RotatingFileHandler` (maxBytes=10MB, backupCount=5)
- JSON-формат через `python-json-logger` (добавить в requirements)
- Отдельный handler для BLE-событий: `ble.log`
- Общий лог: `app.log`

**Критерии готовности:**
- Логи в JSON-формате
- Ротация срабатывает при превышении 10 МБ
- BLE DEBUG-события идут в отдельный файл

---

#### 2.5. `systemd` юнит-файл для автозапуска

**Файлы:**
- `deploy/tion-breezer.service` (create)

**Что делать:**
```ini
[Unit]
Description=Tion Breezer Control Service
After=network.target bluetooth.target

[Service]
Type=simple
User=pi
WorkingDirectory=/opt/tion_python
EnvironmentFile=/opt/tion_python/.env
ExecStart=/opt/tion_python/venv/bin/python main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Критерии готовности:**
- Файл задокументирован
- Инструкция по установке в `deploy/README.md`

---

#### 2.6. Покрытие тестами > 80%

**Файлы:**
- `tests/unit/test_yandex_api.py` (create) — тесты новых FastAPI роутов
- `tests/unit/test_operator.py` (modify) — добавить тесты BLE таймаутов
- `tests/unit/test_s3.py` (create) — тесты `TionS3._encode_request()`
- `tests/unit/test_s4.py` (create) — тесты `TionS4._encode_request()`
- `tests/unit/test_lite_encode.py` (create) — тесты `TionLite._encode_request()`
- `tests/unit/test_mqtt_client.py` (create)

**Что делать:**
- Заполнить пустой `tests/unit/test_device_manager.py`
- Добавить тесты encode-методов для S3, S4, Lite (реверс-инженерия по decode-тестам)
- Покрыть `YandexCallbackSender`
- Целевое покрытие: > 80% для каждого модуля

**Критерии готовности:**
- `pytest --cov` показывает > 80%
- CI публикует coverage report

---

#### 2.7. Предустановленные шаблоны сценариев

**Файлы:**
- `tion_btle/scenario_templates.py` (create)
- `api/routes/scenarios.py` (create)

**Что делать:**
Определить константы-шаблоны:
```python
SCENARIO_TEMPLATES = {
    "night_mode": {
        "name": "Ночной режим",
        "trigger_type": "time",
        "trigger_params": {"time": "23:00"},
        "action_params": {"command": "set_speed", "value": 1, "sound": "off"}
    },
    "ventilation": {
        "name": "Проветривание",
        "trigger_type": "manual",
        "action_params": {"command": "set_speed", "value": 4, "mode": "outside"}
    },
    "co2_turbo": {
        "name": "Авто-турбо при CO₂",
        "trigger_type": "sensor",
        "trigger_params": {"sensor": "co2", "threshold": 1000, "operator": "gt"},
        "action_params": {"command": "set_speed", "value": 6}
    }
}
```
- Endpoint `GET /api/scenarios/templates` — список шаблонов
- Endpoint `POST /api/scenarios/from-template` — создать сценарий из шаблона

**Критерии готовности:**
- 3 предустановленных шаблона доступны через API
- Созданные из шаблонов сценарии работают как обычные

---

### Фаза 3: Could Have — расширенные возможности

После завершения Фазы 2. Улучшения производительности, статистика, деплой.

---

#### 3.1. Redis-кеширование статусов устройств и токенов

**Файлы:**
- `tion_btle/cache.py` (create) — интерфейс `ICache` + `RedisCache` + `InMemoryCache`
- `api/middleware/auth.py` (modify)
- `requirements.txt` (modify) — добавить `redis[asyncio]`

**Что делать:**
- `ICache` с методами `get(key)`, `set(key, value, ttl)`, `delete(key)`
- `InMemoryCache` — реализация по умолчанию (без Redis)
- `RedisCache` — реализация с `aioredis`
- Заменить `token_cache` dict на `ICache`
- Передавать `ICache` в `Operator` для кеширования device status

**Критерии готовности:**
- При отсутствии Redis — fallback на `InMemoryCache` автоматически
- TTL токенов: 1 час; TTL device status: 30 сек

---

#### 3.2. История команд и статистика в SQLite

**Файлы:**
- `tion_btle/domain/device_manager/sqlite_storage.py` (modify) — добавить таблицу `command_history`
- `api/routes/history.py` (create)

**Что делать:**
- Таблица `command_history`: `id, device_id, command, params, result, timestamp`
- Записывать каждую команду из `Operator.set_*` методов
- `GET /api/devices/{id}/history?limit=100` — история команд устройства

**Критерии готовности:**
- История сохраняется после рестарта сервиса
- API возвращает историю с пагинацией

---

#### 3.3. Docker / docker-compose конфигурация

**Файлы:**
- `Dockerfile` (create)
- `docker-compose.yml` (create)
- `.dockerignore` (create)

**Что делать:**
```dockerfile
FROM python:3.11-slim
# Bluetooth requires host network mode on Linux
```

**Ограничение:** BLE на Linux требует `--network host` и доступа к `/var/run/dbus` — документировать.

**Критерии готовности:**
- `docker-compose up` запускает сервис
- BLE-доступ задокументирован (requires host network + privileged или cap_add: NET_ADMIN)

---

#### 3.4. `mypy strict` типизация

**Файлы:**
- Все модули в `tion_btle/` и `api/` (modify)

**Что делать:**
- Добавить `from __future__ import annotations` во все файлы
- Исправить все ошибки `mypy --strict`
- Добавить шаг `mypy` в CI

**Критерии готовности:**
- `mypy --strict tion_btle/ api/` проходит без ошибок
- CI проверяет типы автоматически

---

#### 3.5. Google-style docstrings для публичных методов

**Файлы:**
- Все публичные классы и методы в `tion_btle/` и `api/` (modify)

**Что делать:**
- Добавить docstrings в формате Google-style
- Приоритет: `Operator`, `DeviceManager`, `Scenarist`, API роуты
- Проверить через `pydocstyle` (добавить в CI)

**Критерии готовности:**
- Все публичные методы имеют docstrings
- `pydocstyle --convention=google` проходит без ошибок

---

#### 3.6. Резервное копирование SQLite

**Файлы:**
- `tion_btle/backup.py` (create)
- `main.py` (modify)

**Что делать:**
- Функция `backup_database(db_path: str, backup_dir: str) -> None` — копирует файл с timestamp
- Запускать через `asyncio` как задачу по расписанию (раз в сутки)
- Хранить последние 7 копий

**Критерии готовности:**
- Бэкапы создаются автоматически
- При переполнении — старые файлы удаляются

---

## Зависимости между фазами

```
Фаза 0 (критические исправления)
    │
    ├── 0.1 requests → httpx ─────────────────────────────────┐
    ├── 0.2 .env / python-dotenv                               │
    ├── 0.3 except Exception fix                               │
    ├── 0.4 pyproject.toml                                     │
    └── 0.5 CI fix                                             │
            │                                                   │
            ▼                                                   │
Фаза 1 (ядро интеграции)                                       │
    │                                                           │
    ├── 1.1 main.py + FastAPI ◄─────────────────────────────────┘
    │       (зависит от 0.1, 0.2)
    ├── 1.2 Яндекс роуты ◄───────────────────────────── от 1.1
    ├── 1.3 devices endpoints ◄──────────────────────── от 1.1
    ├── 1.4 callback ◄──────────────────────────────── от 1.1, 1.2
    ├── 1.5 BLE таймауты ◄──────────────────────────── независимо
    └── 1.6 удалить automation.py ◄─────────────────── независимо
            │
            ▼
Фаза 2 (веб-интерфейс и инфраструктура)
    │
    ├── 2.1 групповые команды ◄──────────────── от 1.3
    ├── 2.2 MQTT ◄───────────────────────────── от 1.1
    ├── 2.3 веб-интерфейс ◄──────────────────── от 1.3, 1.1
    ├── 2.4 JSON-логи ◄───────────────────────── от 1.1
    ├── 2.5 systemd ◄────────────────────────── от 1.1
    ├── 2.6 тесты > 80% ◄───────────────────── от всех 1.x
    └── 2.7 шаблоны сценариев ◄──────────────── от 1.3
            │
            ▼
Фаза 3 (расширенные возможности)
    │
    ├── 3.1 Redis ◄──────────────────────────── от 2.x
    ├── 3.2 история ◄────────────────────────── от 1.3
    ├── 3.3 Docker ◄─────────────────────────── от 1.1
    ├── 3.4 mypy ◄───────────────────────────── от 0.4
    ├── 3.5 docstrings ◄─────────────────────── независимо
    └── 3.6 бэкап ◄──────────────────────────── от 1.1
```

**Жёсткие зависимости (блокирующие):**
- Фаза 1 не начинается до завершения всей Фазы 0
- `1.2` зависит от `1.1` (FastAPI app должен существовать)
- `1.4` зависит от `1.1` и `1.2` (нужны роуты и httpx)
- `2.3` зависит от `1.3` (endpoints устройств)
- `3.1` зависит от завершения Фазы 2

---

## Технические решения

### Яндекс API: выбор фреймворка и структура роутов

**Решение: FastAPI вместо Flask**

Обоснование:
- Flask — синхронный фреймворк. Текущая архитектура (Flask + asyncio в отдельном потоке) требует `run_coroutine_threadsafe` — потокобезопасный, но громоздкий паттерн с риском deadlock.
- FastAPI нативно поддерживает `async def` роуты, устраняет необходимость в `threading.Thread` для event loop.
- FastAPI включает автоматическую валидацию через Pydantic, Swagger UI из коробки.
- Миграция Flask → FastAPI минимальна для текущего объёма роутов (5 endpoints).

**Структура роутов:**
```
/v1.0/                           # Yandex Smart Home API
    HEAD /                       # Ping
    GET  /user/devices           # Список устройств
    POST /user/devices/query     # Состояние устройств
    POST /user/devices/action    # Команды
    POST /user/devices/unlink    # Отзыв доступа

/api/                            # Internal REST API
    /devices/                    # CRUD устройств + discover
    /groups/                     # CRUD групп + групповые команды
    /scenarios/                  # CRUD сценариев + шаблоны
    /devices/{id}/history        # История команд

/web/                            # Веб-интерфейс (HTML)
    /devices                     # Список и управление устройствами
```

**Lifespan pattern (FastAPI):**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await operator.initialize()
    await operator.start_polling()
    yield
    await operator.shutdown()

app = FastAPI(lifespan=lifespan)
```

---

### Веб-интерфейс: технологии

**Решение: Jinja2 + HTMX**

- Jinja2 — стандартный шаблонизатор, входит в зависимости FastAPI (Starlette).
- HTMX — легковесная библиотека (14KB) для async HTTP-запросов без написания JS. Позволяет делать "живые" кнопки (сканирование BLE, управление устройствами) без SPA-фреймворка.
- Минимальная внешняя зависимость (CDN или self-hosted).

**Альтернативы отклонены:**
- React/Vue — избыточно для данного проекта, требует сборки
- Чистый JS fetch — требует больше кода для тех же задач

---

### MQTT: архитектура

**Решение: `aiomqtt` (asyncio-native wrapper над `paho-mqtt`)**

- `aiomqtt` — context manager API, совместим с asyncio event loop.
- `MqttSensorClient` реализует `ISensorDataSource` — позволяет подставить mock в тестах.
- При недоступности MQTT-брокера — `Operator` продолжает работу с данными только от BLE-устройств.
- Данные с датчиков хранятся в `InMemoryCache` (или Redis) с TTL 5 минут.

**Топики MQTT:**
```
sensors/{room}/co2          → int (ppm)
sensors/{room}/temperature  → float (°C)
sensors/{room}/humidity     → float (%)
```

---

### Тестирование: стратегия

**Принципы:**
1. Все BLE-вызовы мокируются через `pytest-mock` (`mocker.patch`). Нет реального железа.
2. FastAPI endpoints тестируются через `httpx.AsyncClient(app=app, base_url="http://test")`.
3. SQLite тесты используют in-memory БД (`:memory:`) для изоляции.
4. MQTT клиент — мокируется через `mocker.patch("aiomqtt.Client")`.
5. Яндекс OAuth — мокируется через `mocker.patch("httpx.AsyncClient.get")`.
6. `asyncio_mode = auto` в `pytest.ini` — уже настроен корректно.

**Целевое покрытие (по модулям):**
| Модуль | Текущее | Целевое |
|---|---|---|
| `tion_btle/tion.py` | ~70% | 85% |
| `tion_btle/operator.py` | ~65% | 85% |
| `tion_btle/scenarist.py` | ~75% | 85% |
| `tion_btle/domain/device_manager/` | ~80% | 90% |
| `api/` | 0% | 85% |
| `tion_btle/s3.py` + `s4.py` + `lite.py` | ~50% | 80% |

---

## Файлы к созданию / изменению

### Создать (create)

| Файл | Фаза | Назначение |
|---|---|---|
| `main.py` | 1.1 | Единая точка входа |
| `api/__init__.py` | 1.1 | Пакет API |
| `api/app.py` | 1.1 | FastAPI приложение, lifespan |
| `api/schemas.py` | 1.1 | Pydantic-модели |
| `api/routes/__init__.py` | 1.1 | Пакет роутов |
| `api/routes/yandex.py` | 1.2 | Yandex Smart Home endpoints |
| `api/routes/devices.py` | 1.3 | REST endpoints устройств |
| `api/routes/groups.py` | 2.1 | REST endpoints групп |
| `api/routes/scenarios.py` | 2.7 | REST endpoints сценариев |
| `api/routes/history.py` | 3.2 | История команд |
| `api/routes/web.py` | 2.3 | Веб-интерфейс роуты |
| `api/middleware/__init__.py` | 1.1 | Пакет middleware |
| `api/middleware/auth.py` | 1.1 | async OAuth middleware |
| `web/templates/base.html` | 2.3 | Базовый HTML-шаблон |
| `web/templates/devices.html` | 2.3 | Страница устройств |
| `web/static/` | 2.3 | CSS, JS |
| `tion_btle/logging_config.py` | 2.4 | Настройка JSON-логирования |
| `tion_btle/mqtt_client.py` | 2.2 | MQTT asyncio клиент |
| `tion_btle/scenario_templates.py` | 2.7 | Шаблоны сценариев |
| `tion_btle/cache.py` | 3.1 | ICache интерфейс + реализации |
| `tion_btle/backup.py` | 3.6 | Резервное копирование БД |
| `deploy/tion-breezer.service` | 2.5 | systemd юнит |
| `deploy/README.md` | 2.5 | Инструкция по деплою |
| `Dockerfile` | 3.3 | Docker образ |
| `docker-compose.yml` | 3.3 | Docker Compose |
| `.dockerignore` | 3.3 | Docker ignore |
| `.env.example` | 0.2 | Пример переменных окружения |
| `pyproject.toml` | 0.4 | Конфигурация black/ruff/isort/mypy |
| `tests/unit/test_yandex_api.py` | 2.6 | Тесты FastAPI Yandex роутов |
| `tests/unit/test_s3_encode.py` | 2.6 | Тесты TionS3._encode_request |
| `tests/unit/test_s4_encode.py` | 2.6 | Тесты TionS4._encode_request |
| `tests/unit/test_lite_encode.py` | 2.6 | Тесты TionLite._encode_request |
| `tests/unit/test_mqtt_client.py` | 2.6 | Тесты MQTT клиента |
| `tests/unit/test_callback_sender.py` | 2.6 | Тесты YandexCallbackSender |

### Изменить (modify)

| Файл | Фаза | Что изменить |
|---|---|---|
| `yandex_api_integration.py` | 0.1–0.3, 1.x | requests→httpx, .env, logging; постепенная миграция на FastAPI |
| `requirements.txt` | 0.1–3.x | httpx, python-dotenv, fastapi, uvicorn, aiomqtt, redis |
| `requirements_test.txt` | 0.4 | black, isort, ruff, mypy, pytest-mock, pytest-cov |
| `tion_btle/operator.py` | 1.4, 1.5, 2.1 | BLE таймауты, callback, групповые команды |
| `.github/workflows/tests.yml` | 0.5 | Добавить domain tests в CI |
| `.gitignore` | 0.2 | Добавить .env |
| `tests/unit/test_device_manager.py` | 2.6 | Заполнить пустой файл |
| `tests/unit/test_operator.py` | 2.6 | Добавить тесты таймаутов |

### Удалить (delete)

| Файл | Фаза | Причина |
|---|---|---|
| `automation.py` | 1.6 | Дублирует Scenarist, содержит нарушения конвенций |
