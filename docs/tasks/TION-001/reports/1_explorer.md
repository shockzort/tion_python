# Explorer Report — TION-001

Date: 2026-03-05
Branch: feature-search-and-register-devices
Agent: explorer

---

## Структура проекта (текущая)

```
tion_python/
├── CLAUDE.md                            # Конвенции разработки
├── README.md
├── README_YANDEX_INTEGRATION.md
├── LICENSE
├── pyproject.toml                       # СОЗДАН (hatchling, black, ruff, isort, mypy)
├── uv.lock                              # Lockfile uv
├── devices.db                           # Рабочая БД SQLite прямо в корне!
├── .env.example                         # СОЗДАН — переменные окружения
├── .gitignore                           # Содержит .env, .venv
│
├── main.py                              # СОЗДАН — точка входа (FastAPI + uvicorn)
├── yandex_api_integration.py            # Старый Flask API — НЕ удалён, всё ещё актуален
│
├── api/                                 # СОЗДАН — FastAPI пакет
│   ├── __init__.py
│   ├── app.py                           # FastAPI app с lifespan
│   ├── schemas.py                       # Pydantic-модели запросов/ответов
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── auth.py                      # Async OAuth middleware
│   └── routes/
│       ├── __init__.py
│       ├── yandex.py                    # Yandex Smart Home endpoints v1.0
│       └── devices.py                   # REST endpoints устройств
│
├── tion_btle/                           # Основная библиотека
│   ├── __init__.py
│   ├── tion.py                          # Базовый класс Tion (ABC)
│   ├── light_family.py                  # TionLiteFamily (промежуточный ABC)
│   ├── s3.py                            # TionS3
│   ├── s4.py                            # TionS4
│   ├── lite.py                          # TionLite
│   ├── operator.py                      # Operator (центральный менеджер)
│   ├── scenarist.py                     # Scenarist (сценарии автоматизации)
│   └── domain/
│       ├── __init__.py
│       └── device_manager/
│           ├── __init__.py
│           ├── interfaces.py            # IDeviceStorage, IDeviceGroupStorage
│           ├── models.py               # DeviceInfo, DeviceGroup (dataclass)
│           ├── device_manager.py       # DeviceManager (domain service)
│           ├── sqlite_storage.py       # SQLiteDeviceStorage
│           └── tests/
│               ├── __init__.py
│               ├── test_device_manager.py
│               └── test_sqlite_storage.py
│
├── tests/
│   ├── __init__.py
│   ├── functional/
│   │   ├── __init__.py
│   │   ├── test_lite.py               # Требует реального железа
│   │   └── test_s4.py
│   └── unit/
│       ├── __init__.py
│       ├── tion.py                    # Вспомогательный файл
│       ├── test_decode.py
│       ├── test_device_manager.py     # ПУСТОЙ (1 строка)
│       ├── test_lite.py
│       ├── test_operator.py
│       ├── test_scenarist.py
│       ├── test_tion.py
│       └── test_yandex_api_integration.py   # Тесты Flask (yandex_api_integration.py)
│
├── context/
│   ├── brd/brd.md
│   └── frd/frd.md
│
├── docs/
│   └── tasks/TION-001/
│       ├── plan.md
│       └── reports/
│           ├── 1_explorer.md           # Этот файл
│           ├── 2_analyst.md
│           └── 3_architect.md
│
├── .venv/                              # Виртуальное окружение (uv)
└── .github/
    └── workflows/
        ├── tests.yml                   # CI: устаревший (pip + requirements_test.txt)
        └── release.yml
```

**Файлы, помеченные в git как удалённые (D):**
- `automation.py` — удалён
- `pytest.ini` — удалён (заменён секцией в pyproject.toml)
- `requirements.txt` — удалён (заменён pyproject.toml)
- `requirements_test.txt` — удалён (заменён pyproject.toml)
- `setup.py` — удалён

---

## Статус по фазам плана

### Фаза 0: Критические исправления

#### 0.1 requests → httpx
**Статус: ВЫПОЛНЕНО**

- В `yandex_api_integration.py` используется `httpx.AsyncClient` (строки 85–95)
- В `api/middleware/auth.py` используется `httpx.AsyncClient` (строки 37–44)
- В `api/routes/yandex.py` используется `httpx.AsyncClient` (строки 393–414)
- `import requests` отсутствует в кодовой базе (проверено grep)
- `httpx>=0.27.0` зафиксирован в `pyproject.toml`

#### 0.2 .env / python-dotenv
**Статус: ВЫПОЛНЕНО**

- `python-dotenv>=1.0.0` в `pyproject.toml`
- `load_dotenv()` вызывается в `main.py` (строка 13) и `yandex_api_integration.py` (строка 18)
- `.env.example` создан с переменными: `DB_PATH`, `YANDEX_OAUTH_INFO_URL`, `YANDEX_SKILL_ID`, `YANDEX_CALLBACK_TOKEN`, `HOST`, `PORT`, `DEBUG`, `BLE_OPERATION_TIMEOUT`, `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_TOPIC_PREFIX`, `LOG_DIR`
- `.env` добавлен в `.gitignore`

#### 0.3 except Exception без логирования
**Статус: ЧАСТИЧНО ВЫПОЛНЕНО / НАРУШЕНИЯ ОСТАЛИСЬ**

Нарушения по-прежнему присутствуют в старом коде:
- `yandex_api_integration.py:96` — `except Exception as e` с `_LOGGER.error()` c `exc_info=True` — **корректно**
- `tion_btle/operator.py:531` — `except Exception: pass` — **НАРУШЕНИЕ** (строка 532: `pass` без логирования)
- `tion_btle/operator.py:202` — `except Exception as e: _LOGGER.error(f"Polling error: {str(e)}")` — нет `exc_info=True`
- `tion_btle/operator.py:452` — `except Exception as e: _LOGGER.error(f"Failed...")` — f-string вместо `%s`, нет `exc_info=True`
- `tion_btle/operator.py:474` — аналогично
- `tion_btle/operator.py:557` — аналогично
- `tion_btle/domain/device_manager/device_manager.py:145,163,178` — `except Exception as e: _LOGGER.error(f"...")` — f-string, нет `exc_info=True`
- `tests/functional/test_lite.py` — `print()` вызовы в тестовом коде (строки 19-22)

#### 0.4 pyproject.toml
**Статус: ВЫПОЛНЕНО**

`pyproject.toml` создан со всеми необходимыми секциями:
- `[tool.black]`: `line-length = 88`, `target-version = ["py310"]`
- `[tool.isort]`: `profile = "black"`, `line_length = 88`
- `[tool.ruff]`: `line-length = 88`, `target-version = "py310"`, все нужные правила
- `[tool.mypy]`: `strict = true`, `python_version = "3.10"`
- `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`, `testpaths = ["tests"]`
- Зависимости dev: `pytest`, `pytest-asyncio`, `pytest-mock`, `pytest-cov`, `black`, `isort`, `ruff`, `mypy`

**Проблема:** В `[tool.pytest.ini_options]` указан `testpaths = ["tests"]`, что НЕ включает `tion_btle/domain/device_manager/tests/` в автоматический запуск.

#### 0.5 CI fix
**Статус: НЕ ВЫПОЛНЕНО**

`.github/workflows/tests.yml` всё ещё использует:
- `pip install -r requirements_test.txt` — файл удалён из репозитория (D в git status)
- `python: ['3.9', '3.10']` — Python 3.9 включён, хотя проект требует 3.10+
- `actions/checkout@v2.3.4` — устаревшая версия (актуальна v4)
- `actions/setup-python@v4` — устаревшая версия (актуальна v5)
- Команда pytest всё ещё добавляет `tion_btle/domain/device_manager/tests/` явно, что хорошо, но зависит от удалённого `requirements_test.txt`
- Нет шага `uv sync` или `pip install -e ".[dev]"`

---

### Фаза 1: Ядро интеграции

#### 1.1 main.py — единая точка входа
**Статус: ВЫПОЛНЕНО**

`main.py` создан и содержит:
- `load_dotenv()` вызывается до любых импортов
- `setup_logging()` — настройка логирования (JSON через `python-json-logger`, ротация через `RotatingFileHandler`)
- Запуск через `uvicorn.run(app, ...)` — корректная async архитектура
- Обработчики `signal.SIGTERM` / `SIGINT`
- Импорт `from api.app import app` отложен после `load_dotenv()`

**Проблема:** `setup_logging()` пробует импортировать `pythonjsonlogger` (строка 51), но этот пакет (`python-json-logger`) добавлен только в runtime зависимости `pyproject.toml` как `python-json-logger>=2.0.0`, что корректно. Однако import path: `from pythonjsonlogger import jsonlogger` — зависит от версии пакета.

#### 1.2 Яндекс роуты
**Статус: ВЫПОЛНЕНО**

`api/routes/yandex.py` реализует все 5 обязательных endpoint:
- `HEAD /v1.0/` — ping (строка 112)
- `GET /v1.0/user/devices` — список устройств (строка 122)
- `POST /v1.0/user/devices/query` — состояние (строка 162)
- `POST /v1.0/user/devices/action` — команды (строка 240)
- `POST /v1.0/user/devices/unlink` — отзыв доступа (строка 344)

`request_id` берётся из заголовка `X-Request-Id` (через `get_request_id()` в `auth.py`, строка 90).

**Дополнительно реализовано:** `send_yandex_callback()` — push-уведомления Яндексу (строки 363–419) — относится к плану 1.4.

#### 1.3 REST endpoints устройств
**Статус: ЧАСТИЧНО ВЫПОЛНЕНО / КРИТИЧЕСКИЙ СИГНАТУРНЫЙ КОНФЛИКТ**

`api/routes/devices.py` реализует:
- `POST /api/devices/discover` — BLE-сканирование
- `POST /api/devices/register` — регистрация устройства
- `GET /api/devices` — список устройств
- `GET /api/devices/{id}` — детали устройства
- `DELETE /api/devices/{id}` — мягкое удаление
- `GET /api/devices/{id}/status` — статус через BLE
- `POST /api/devices/{id}/command` — выполнение команды
- `POST /api/devices/{id}/pair` — BLE-сопряжение

**КРИТИЧЕСКИЙ БАГИ:**

1. **Сигнатурный конфликт `register_device`** (строки 87–92):
   ```python
   # api/routes/devices.py вызывает:
   device = await device_manager.register_device(
       name=body.name,
       mac_address=body.mac_address,
       model=body.model,
       room=body.room,
   )

   # Но device_manager.register_device() имеет сигнатуру:
   async def register_device(
       self, device: BLEDevice, name: str = None, auto_pair: bool = False
   ) -> DeviceInfo:
   ```
   Вызов по kwargs (`name`, `mac_address`, `model`, `room`) не соответствует сигнатуре, принимающей `BLEDevice` как первый позиционный аргумент. **При вызове этого endpoint — TypeError.**

2. **`delete_device` вызывается синхронно** (строка 213):
   ```python
   device_manager.delete_device(device_id)  # нет await
   ```
   Но `DeviceManager.delete_device()` — `async def` (вызывает `unpair_device` внутри). **Coroutine не выполняется.**

3. **`pair_device` вызывается на `operator.device_manager`** (строка 96):
   ```python
   await operator.device_manager.pair_device(device.id)
   ```
   `Operator` не имеет публичного `device_manager` атрибута через публичный интерфейс — обращение к внутреннему атрибуту.

#### 1.4 POST callback — push-уведомления Яндексу
**Статус: ЧАСТИЧНО ВЫПОЛНЕНО**

Функция `send_yandex_callback()` реализована в `api/routes/yandex.py` (строки 363–419).

**Не реализовано:**
- Интеграция с `Operator._poll_devices()` для определения изменений статуса
- `YandexCallbackSender` как отдельный класс
- Очередь изменений для callback

Функция существует изолированно и нигде не вызывается из `Operator`.

#### 1.5 Таймауты на BLE-операции
**Статус: ВЫПОЛНЕНО**

В `tion_btle/operator.py`:
- `BLE_OPERATION_TIMEOUT = float(os.getenv("BLE_OPERATION_TIMEOUT", "10.0"))` (строка 17)
- `asyncio.wait_for(device.get(), timeout=BLE_OPERATION_TIMEOUT)` в `get_device_status()` (строки 237–248)
- `asyncio.wait_for(device.set(...), timeout=BLE_OPERATION_TIMEOUT)` в `_set_device_property()` (строки 386–400)
- `asyncio.wait_for(device.get(), timeout=BLE_OPERATION_TIMEOUT)` в `_update_devices_status()` (строки 137–177)
- `asyncio.TimeoutError` перехватывается явно с логированием

#### 1.6 Удалить automation.py
**Статус: ВЫПОЛНЕНО**

`automation.py` удалён (помечен как D в git status). Нет импортов `AutomationManager` в коде.

---

### Фаза 2-3

#### 2.1 Групповые команды
**Статус: НЕ РЕАЛИЗОВАНО**

Нет `api/routes/groups.py`. `DeviceGroup` модель существует в `models.py`. Метод `create_device_group`, `update_device_group`, `delete_device_group` есть в `DeviceManager`, но API endpoint отсутствует.

#### 2.2 MQTT-интеграция
**Статус: НЕ РЕАЛИЗОВАНО**

Нет `tion_btle/mqtt_client.py`. MQTT переменные есть в `.env.example`, но код отсутствует.

#### 2.3 Веб-интерфейс
**Статус: НЕ РЕАЛИЗОВАНО**

Нет директории `web/`. Нет `api/routes/web.py`.

#### 2.4 JSON-логирование с ротацией
**Статус: ЧАСТИЧНО ВЫПОЛНЕНО**

`setup_logging()` реализован в `main.py` (строки 16–64):
- `RotatingFileHandler` с `maxBytes=10MB`, `backupCount=5`
- Попытка JSON-формата через `pythonjsonlogger`
- Отдельный handler для BLE-событий (`ble.log`)

Не создан отдельный `tion_btle/logging_config.py` (логирование встроено в `main.py`).

#### 2.5 systemd юнит-файл
**Статус: НЕ РЕАЛИЗОВАНО**

Нет директории `deploy/`. Нет `.service` файла.

#### 2.6 Покрытие тестами > 80%
**Статус: НЕ ВЫПОЛНЕНО**

- `tests/unit/test_device_manager.py` — **ПУСТОЙ** (1 строка)
- Нет тестов для `api/` (FastAPI роуты не покрыты)
- Нет тестов `test_s3_encode.py`, `test_s4_encode.py`, `test_lite_encode.py`
- Нет `test_callback_sender.py`
- `test_yandex_api_integration.py` тестирует **старый Flask API**, а не новые FastAPI роуты

#### 2.7 Шаблоны сценариев
**Статус: НЕ РЕАЛИЗОВАНО**

Нет `tion_btle/scenario_templates.py`. Нет `api/routes/scenarios.py`.

#### 3.1–3.6 Все фазы 3
**Статус: НЕ РЕАЛИЗОВАНО**

Нет Redis-кеширования, истории команд, Docker-конфигурации, mypy strict для всех модулей, полных docstrings, резервного копирования.

---

## Нарушения конвенций CLAUDE.md

### Критические нарушения

| Файл | Строки | Нарушение |
|---|---|---|
| `tion_btle/operator.py` | 531 | `except Exception: pass` — без логирования |
| `tion_btle/operator.py` | 202, 452, 474, 557 | `_LOGGER.error(f"...")` — f-string в logging, нет `exc_info=True` |
| `tion_btle/domain/device_manager/device_manager.py` | 145, 163, 178 | `_LOGGER.error(f"...")` — f-string в logging, нет `exc_info=True` |
| `api/routes/devices.py` | 213 | `device_manager.delete_device(device_id)` без `await` — async coroutine игнорируется |
| `api/routes/devices.py` | 87–92 | `register_device(name=..., mac_address=..., model=..., room=...)` — несовместимая сигнатура |

### Нарушения типизации

| Файл | Нарушение |
|---|---|
| `tion_btle/domain/device_manager/models.py` | Нет `from __future__ import annotations`; использует `Optional[str]`, `List[str]`, `Dict` вместо `X \| None`, `list[X]`, `dict` |
| `tion_btle/domain/device_manager/interfaces.py` | Нет `from __future__ import annotations`; использует `List`, `Dict`, `Optional` из `typing` |
| `tion_btle/domain/device_manager/sqlite_storage.py` | Нет `from __future__ import annotations`; использует `List`, `Dict`, `Optional`, `Any` из `typing` |
| `tion_btle/domain/device_manager/device_manager.py` | Нет `from __future__ import annotations`; использует `List`, `Dict`, `Optional` из `typing`; `name: str = None` (несовместимый тип) |
| `tion_btle/scenarist.py` | Нет `from __future__ import annotations`; `created_at: datetime = None` (нарушение типа, должно быть `Optional[datetime]`) |
| `tion_btle/operator.py` | Использует `Dict`, `Optional` из `typing` (строки 8, 48–52) |

### Нарушения docstrings (Google-style)

| Файл | Нарушение |
|---|---|
| `tion_btle/domain/device_manager/device_manager.py` | Все публичные методы без Google-style docstrings (нет Args/Returns) |
| `tion_btle/domain/device_manager/models.py` | Нет docstrings у `DeviceInfo` и `DeviceGroup` |
| `tion_btle/domain/device_manager/interfaces.py` | Нет Args/Returns в методах |
| `tion_btle/domain/device_manager/sqlite_storage.py` | Нет docstrings у методов |
| `tion_btle/scenarist.py` | Нет docstrings у класса `Scenarist` и метода `Scenario` |

### Нарушения именования/стиля

| Файл | Строки | Нарушение |
|---|---|---|
| `tion_btle/operator.py` | 85, 89, 94–96, 411–412, 432, 447–451, 453–454, 475, 531, 557 | f-string логирование вместо `%s` формата |
| `tion_btle/domain/device_manager/device_manager.py` | 135, 139, 146, 163, 164, 177, 178 | f-string логирование |
| `tests/functional/test_lite.py` | 19–22 | `print()` в тестовом коде |

### Архитектурные нарушения

| Нарушение | Описание |
|---|---|
| `yandex_api_integration.py` существует параллельно с `api/` | Дублирование логики: Flask app с теми же endpoints параллельно FastAPI; `check_authorization` — синхронная функция, вызывает async через `asyncio.run_coroutine_threadsafe` |
| `Operator.__init__` создаёт зависимости внутри | Нарушает DI принцип; затрудняет тестирование |
| `tion_btle/operator.py` дублирует инициализацию storage | `Operator.__init__` создаёт `SQLiteDeviceStorage` дважды (`device_storage` и `group_storage`) для одного файла |
| `.github/workflows/tests.yml` сломан | Ссылается на `requirements_test.txt` (удалён из репозитория) |

---

## Ключевые файлы

| Файл | Описание текущего состояния |
|---|---|
| `main.py` | **Новый.** Точка входа для FastAPI/uvicorn. Реализован корректно. Зависит от `api.app`. |
| `api/app.py` | **Новый.** FastAPI приложение с lifespan. Дважды инициализирует storage и managers (как в Operator). |
| `api/routes/yandex.py` | **Новый.** Все 5 Yandex Smart Home endpoints реализованы. Включает `send_yandex_callback()`. MODE_MAPPING дублируется с `yandex_api_integration.py`. |
| `api/routes/devices.py` | **Новый.** 8 endpoints. **КРИТИЧЕСКИЙ БАГ:** `register_device` вызывается с несовместимой сигнатурой; `delete_device` не awaited. |
| `api/middleware/auth.py` | **Новый.** Async OAuth middleware. Корректно использует `httpx.AsyncClient`. |
| `api/schemas.py` | **Новый.** Pydantic v2 модели. Содержит схемы для Yandex и device management. |
| `yandex_api_integration.py` | **Старый Flask API.** Не удалён. Дублирует функционал `api/routes/yandex.py`. Нарушает архитектуру (2 HTTP сервера в проекте). |
| `tion_btle/operator.py` | Центральный менеджер. BLE таймауты добавлены. Множественные нарушения логирования. `except Exception: pass` на строке 531. |
| `tion_btle/domain/device_manager/device_manager.py` | `register_device()` принимает `BLEDevice`, но `api/routes/devices.py` вызывает с kwargs. Несоответствие интерфейсов. |
| `tion_btle/scenarist.py` | `Scenario.created_at: datetime = None` — некорректный тип по умолчанию. `Scenario` в `get_scenarios()` не заполняет `last_executed`, `execution_count`, `last_status`. |
| `tion_btle/domain/device_manager/sqlite_storage.py` | Таблица `scenarios` отсутствует (она в `Scenarist._init_db`). SQLiteDeviceStorage — единственная реализация обоих интерфейсов. |
| `.github/workflows/tests.yml` | **СЛОМАН.** Ссылается на `requirements_test.txt` (файл удалён). CI не запустится. |
| `pyproject.toml` | **Новый.** Корректно настроен. `testpaths = ["tests"]` не включает domain tests. `[[tool.mypy.overrides]]` игнорирует ошибки в `yandex_api_integration` (строки 86–87). |
| `tests/unit/test_device_manager.py` | **ПУСТОЙ.** 1 строка. Файл не содержит тестов. |
| `tests/unit/test_yandex_api_integration.py` | Тестирует **старый Flask API**. При удалении `yandex_api_integration.py` все тесты сломаются. |

---

## Критические проблемы

### Блокирующие разработку

1. **`.github/workflows/tests.yml` сломан** — CI не может выполниться: `pip install -r requirements_test.txt` — файл удалён (D). Любой push в master завершится ошибкой CI.

2. **`register_device` в `api/routes/devices.py:87–92` несовместимо с `DeviceManager.register_device()`** — `POST /api/devices/register` всегда будет выдавать `TypeError: register_device() got unexpected keyword argument 'mac_address'`. Функциональность TION-001 (регистрация устройства) недоступна через API.

3. **`delete_device` в `api/routes/devices.py:213` без `await`** — `DELETE /api/devices/{id}` не выполняет мягкое удаление; возвращает успех, но устройство остаётся активным в БД.

4. **`pyproject.toml: testpaths = ["tests"]`** — `tion_btle/domain/device_manager/tests/` не запускается при `pytest` без явного указания пути. Domain tests выпадают из стандартного запуска тестов.

5. **`yandex_api_integration.py` не удалён и создаёт конфликт** — проект содержит два HTTP API (Flask на `yandex_api_integration.py` и FastAPI в `api/`). `test_yandex_api_integration.py` тестирует Flask-версию, которая теперь является мёртвым кодом, но mypy игнорирует её ошибки (`[[tool.mypy.overrides]] ignore_errors = true`).

### Серьёзные, но не блокирующие

6. **`Scenarist.get_scenarios()` не заполняет `last_executed`, `execution_count`, `last_status`** — эти поля отсутствуют в таблице `scenarios`. При вызове `execute_scenario()` в `Operator` обновляются атрибуты `scenario` объекта в памяти, но в БД не записываются — после рестарта информация теряется.

7. **`except Exception: pass` в `tion_btle/operator.py:531`** — при ошибке disconnect во время `reconnect_device()` исключение молча проглатывается без логирования. Нарушение CLAUDE.md.

8. **`Operator.__init__` создаёт `SQLiteDeviceStorage` дважды** (строки 43–45) — `device_storage` и `group_storage` оба указывают на один файл через отдельные объекты. Избыточность.

9. **`api/app.py` дублирует инициализацию** (строки 32–36) — создаёт `DeviceManager` и `Operator`, но `Operator.__init__` внутри тоже создаёт свой `DeviceManager`. Итого два `DeviceManager` с разными `SQLiteDeviceStorage` экземплярами.

---

## Что уже реализовано корректно

1. **FastAPI архитектура** — переход с Flask на FastAPI с lifespan pattern выполнен правильно. Нет `threading.Thread` для asyncio.

2. **httpx везде** — `requests` полностью устранён. Все HTTP-запросы (OAuth, Yandex callback) используют `httpx.AsyncClient` с явными таймаутами.

3. **python-dotenv** — `load_dotenv()` вызывается до импортов в `main.py`. `.env.example` создан.

4. **pyproject.toml** — корректно настроен с `black`, `isort`, `ruff`, `mypy strict`.

5. **BLE таймауты** — все BLE-операции (`get()`, `set()`) защищены `asyncio.wait_for(BLE_OPERATION_TIMEOUT)`. `asyncio.TimeoutError` перехватывается явно.

6. **Yandex Smart Home API endpoints** — все 5 обязательных endpoint реализованы в `api/routes/yandex.py` с корректным форматом ответов.

7. **`send_yandex_callback()`** — push-уведомления реализованы (нужна интеграция с polling).

8. **`from __future__ import annotations`** — добавлен в 16 файлов (включая все файлы `api/` и основные `tion_btle/`).

9. **Pydantic v2 схемы** — `api/schemas.py` содержит типизированные модели для всех endpoint.

10. **async OAuth middleware** — `api/middleware/auth.py` полностью асинхронный, с кешированием токенов (1 час), корректной обработкой ошибок.

11. **`automation.py` удалён** — дублирующий файл устранён.

12. **SQLiteDeviceStorage** — корректная реализация с soft delete, upsert по MAC, обработкой ошибок.

13. **Domain tests** — `tion_btle/domain/device_manager/tests/` содержит полный набор тестов с хорошим покрытием edge cases.

14. **`Operator.shutdown()`** — корректная очистка ресурсов: отмена задач polling и scenarios, disconnect всех устройств.

15. **Экспоненциальный backoff** — реализован в `_load_device()` (`await asyncio.sleep(2**attempt)`).

---

## Точки интеграции

### Компонентная карта (текущее состояние)

```
[Яндекс Алиса]
    │
    ▼ HTTPS
[FastAPI — api/app.py]
    │
    ├── GET/POST /v1.0/* ──────────► [api/routes/yandex.py]
    │                                      │
    │                                      ▼
    │                                 [Operator]
    │                                 [DeviceManager]
    │
    ├── POST/GET /api/devices/* ───► [api/routes/devices.py]
    │                                      │
    │                                      ├──► [DeviceManager]
    │                                      │      ├── [IDeviceStorage] ◄── [SQLiteDeviceStorage]
    │                                      │      └── [IDeviceGroupStorage] ◄── [SQLiteDeviceStorage]
    │                                      │
    │                                      └──► [Operator]
    │                                               └── [_devices: Dict[str, Tion]]
    │                                                       ├── [TionS3]
    │                                                       ├── [TionS4]
    │                                                       └── [TionLite]
    │                                                               ▼
    │                                                       [BleakClient → BLE]
    │
    └── [api/middleware/auth.py] ──► [Yandex OAuth API]
              (токен кеш: 1 час)      httpx.AsyncClient


[main.py]
    │
    ├── setup_logging()
    ├── uvicorn.run(app, ...)
    └── signal handlers → operator.shutdown()


[yandex_api_integration.py]  ← МЁРТВЫЙ КОД, не удалён
    │ Flask (синхронный)
    ├── /devices, /state, /action, /scenarios
    └── threading.Thread(asyncio loop)  ← устаревший паттерн
```

### Точки для продолжения работы

| Задача | Файл | Что нужно изменить |
|---|---|---|
| Исправить register_device | `tion_btle/domain/device_manager/device_manager.py` | Изменить сигнатуру: принимать `name, mac_address, model, room` вместо `BLEDevice` |
| Или исправить вызов | `api/routes/devices.py:87–92` | Вызывать `register_device` с `BLEDevice`-совместимым объектом |
| Исправить delete_device | `api/routes/devices.py:213` | Добавить `await` |
| Исправить CI | `.github/workflows/tests.yml` | Перейти на `uv sync` + `uv run pytest` |
| Добавить domain tests в testpaths | `pyproject.toml` | Добавить `tion_btle/domain/device_manager/tests` в `testpaths` |
| Удалить Flask API | `yandex_api_integration.py` | Удалить или переименовать для обратной совместимости |
| Callback интеграция | `tion_btle/operator.py:_update_devices_status` | Вызывать `send_yandex_callback()` при изменении статуса |
| Сохранение статистики сценариев | `tion_btle/scenarist.py` | Добавить колонки в таблицу; сохранять `last_executed`, `execution_count`, `last_status` |
| except Exception: pass | `tion_btle/operator.py:531` | Добавить логирование |
| Тесты FastAPI endpoints | `tests/unit/` | Создать `test_api_devices.py`, `test_api_yandex.py` используя `httpx.AsyncClient(app=app)` |
