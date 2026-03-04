# Analyst Report — TION-001 (v2)

Date: 2026-03-05
Branch: feature-search-and-register-devices
Agent: analyst (обновлено на основе отчёта explorer v1)

> Этот отчёт заменяет предыдущую версию от 2026-03-04.
> Предыдущая версия отражала состояние ДО создания `api/`, `main.py`, `pyproject.toml`.
> Текущая версия основана на фактическом состоянии кода после частичной реализации плана.

---

## Статус по фазам (что выполнено / не выполнено)

### Фаза 0 (критические исправления)

| ID | Требование | Статус | Примечания |
| --- | --- | --- | --- |
| 0.1 | requests → httpx | ✅ | httpx используется во всех HTTP-вызовах; import requests отсутствует |
| 0.2 | .env / python-dotenv | ✅ | load_dotenv() в main.py и yandex_api_integration.py; .env.example создан |
| 0.3 | except Exception без логирования | ❌ | operator.py:531 — `except Exception: pass`; множество мест с f-string logging без exc_info=True |
| 0.4 | pyproject.toml | ✅ | Создан с black/isort/ruff/mypy/pytest; testpaths не включает domain tests |
| 0.5 | CI fix | ❌ | tests.yml ссылается на удалённый requirements_test.txt; Python 3.9 в матрице; устаревшие actions |

### Фаза 1 (ядро интеграции)

| ID | Требование | Статус | Примечания |
| --- | --- | --- | --- |
| 1.1 | main.py — единая точка входа | ✅ | FastAPI + uvicorn, signal handlers, setup_logging() |
| 1.2 | Яндекс роуты | ✅ | Все 5 endpoints реализованы в api/routes/yandex.py |
| 1.3 | REST endpoints устройств | ❌ | КРИТИЧЕСКИЙ БАГ: register_device — несовместимая сигнатура; delete_device — missing await |
| 1.4 | POST callback — push-уведомления | ⚠️ | send_yandex_callback() реализована, но не интегрирована с Operator polling |
| 1.5 | Таймауты на BLE-операции | ✅ | asyncio.wait_for с BLE_OPERATION_TIMEOUT во всех BLE-методах |
| 1.6 | Удалить automation.py | ✅ | Файл удалён (D в git status), нет импортов AutomationManager |

### Фаза 2 (веб-интерфейс и инфраструктура)

| ID | Требование | Статус | Примечания |
| --- | --- | --- | --- |
| 2.1 | Групповые команды через API | ❌ | Нет api/routes/groups.py; модель DeviceGroup есть, API нет |
| 2.2 | MQTT-интеграция | ❌ | Нет mqtt_client.py; переменные в .env.example, код отсутствует |
| 2.3 | Веб-интерфейс | ❌ | Нет директории web/, нет роутов |
| 2.4 | JSON-логирование с ротацией | ⚠️ | setup_logging() в main.py реализован; отдельный logging_config.py не создан |
| 2.5 | systemd юнит-файл | ❌ | Нет директории deploy/ |
| 2.6 | Покрытие тестами > 80% | ❌ | tests/unit/test_device_manager.py пуст; нет тестов api/; нет test_callback_sender.py |
| 2.7 | Шаблоны сценариев | ❌ | Нет scenario_templates.py, нет api/routes/scenarios.py |

### Фаза 3 (расширенные возможности)

| ID | Требование | Статус | Примечания |
| --- | --- | --- | --- |
| 3.1 | Redis-кеширование | ❌ | Не реализовано |
| 3.2 | История команд | ❌ | Нет таблицы command_history, нет api/routes/history.py |
| 3.3 | Docker / docker-compose | ❌ | Нет Dockerfile, нет docker-compose.yml |
| 3.4 | mypy strict типизация | ❌ | Optional/List/Dict из typing вместо X|None/list/dict; нет from __future__ в domain/ |
| 3.5 | Google-style docstrings | ❌ | Отсутствуют в domain/device_manager/, scenarist.py |
| 3.6 | Резервное копирование SQLite | ❌ | Нет backup.py |

### Дополнительные проблемы (не в плане, обнаружены при анализе)

| ID | Проблема | Описание |
| --- | --- | --- |
| X.1 | yandex_api_integration.py не удалён | Старый Flask API существует параллельно с FastAPI; мёртвый код; тесты Flask не удалены |
| X.2 | Двойная инициализация DeviceManager | api/app.py создаёт DeviceManager; Operator.__init__ создаёт свой — два независимых экземпляра |
| X.3 | Двойной SQLiteDeviceStorage в Operator | device_storage и group_storage — два объекта на один файл |
| X.4 | testpaths не включает domain tests | tion_btle/domain/device_manager/tests/ выпадает из стандартного pytest |
| X.5 | Scenarist не сохраняет статистику в БД | last_executed, execution_count, last_status — только в памяти, теряются при рестарте |
| X.6 | devices.db в корне репозитория | БД лежит в корне, не в настраиваемом DB_PATH |

---

## Acceptance Criteria

> Актуальные AC для текущего состояния кода (2026-03-05), основанные на отчёте explorer.

### Критические (блокирующие) — AC-0x

---

### AC-01: CI работоспособен

Контекст: `.github/workflows/tests.yml` ссылается на удалённый `requirements_test.txt`. Любой push завершается ошибкой на шаге установки зависимостей.

Критерии:
- `.github/workflows/tests.yml` не содержит ссылок на `requirements_test.txt` или `setup.py`
- Установка зависимостей выполняется через `uv sync` или `pip install -e ".[dev]"`
- Матрица Python содержит только `["3.10", "3.11"]` (минимальная версия проекта — 3.10+)
- Версии actions обновлены: `actions/checkout@v4`, `actions/setup-python@v5`
- `pytest tests/unit tion_btle/domain/device_manager/tests/` выполняется успешно в CI
- Coverage report присутствует в артефактах CI

Проверяется через: успешный прогон workflow после пуша в ветку.

---

### AC-02: `POST /api/devices/register` работает без ошибки TypeError

Контекст: `api/routes/devices.py:87-92` вызывает `device_manager.register_device(name=..., mac_address=..., model=..., room=...)`, тогда как `DeviceManager.register_device()` принимает `(self, device: BLEDevice, name: str = None, auto_pair: bool = False)`. Endpoint всегда выбрасывает `TypeError`.

Критерии:
- `DeviceManager.register_device()` принимает `name: str`, `mac_address: str`, `model: str`, `room: str | None`, `auto_pair: bool = False` (без BLEDevice как обязательного аргумента)
- `POST /api/devices/register` с корректным телом `{"name": "...", "mac_address": "AA:BB:CC:DD:EE:FF", "model": "S3"}` возвращает HTTP 201 с объектом DeviceInfo
- `DeviceInfo` содержит корректный `id`, `name`, `mac_address`, `model`, `is_active=True`
- Устройство сохраняется в SQLite и доступно через `GET /api/devices`
- Тест `test_api_devices.py::test_register_device` проходит без реального BLE-оборудования

Проверяется через: `pytest tests/unit/test_api_devices.py::test_register_device`; `curl -X POST /api/devices/register`.

---

### AC-03: `DELETE /api/devices/{id}` выполняет мягкое удаление

Контекст: `api/routes/devices.py:213` — `device_manager.delete_device(device_id)` без `await`. Async coroutine игнорируется: возвращается 200 OK, но устройство остаётся активным в БД.

Критерии:
- `api/routes/devices.py:213` содержит `await device_manager.delete_device(device_id)`
- `DELETE /api/devices/{id}` возвращает HTTP 200
- После запроса устройство имеет `is_active=False` в SQLite
- `GET /api/devices` не возвращает удалённое устройство (фильтрация по `is_active=True`)
- `GET /api/devices/{id}` возвращает HTTP 404 для удалённого устройства

Проверяется через: `pytest tests/unit/test_api_devices.py::test_delete_device`; проверка записи в SQLite.

---

### AC-04: `except Exception: pass` устранён

Контекст: `tion_btle/operator.py:531` — `except Exception: pass` при disconnect в `reconnect_device()`. Нарушение CLAUDE.md: запрещено без логирования или re-raise.

Критерии:
- `tion_btle/operator.py:531` содержит явное логирование ошибки с `exc_info=True` или re-raise
- `ruff check tion_btle/operator.py` не выдаёт нарушений правил `S110` (try-except-pass)
- Все `except Exception` в `operator.py` содержат `_LOGGER.error("...", exc_info=True)` или re-raise
- Все `_LOGGER.error(f"...")` заменены на `_LOGGER.error("...", ...)` (без f-string) с `exc_info=True`

Проверяется через: `ruff check tion_btle/operator.py`; код-ревью строки 531.

---

### AC-05: domain tests включены в стандартный запуск pytest

Контекст: `pyproject.toml: testpaths = ["tests"]` не включает `tion_btle/domain/device_manager/tests/`. Domain-тесты выпадают из CI и локального запуска без явного указания пути.

Критерии:
- `pyproject.toml: testpaths` содержит `["tests", "tion_btle/domain/device_manager/tests"]`
- `pytest` без аргументов запускает domain tests
- `tion_btle/domain/device_manager/tests/test_device_manager.py` и `test_sqlite_storage.py` включены в coverage

Проверяется через: `pytest --collect-only` показывает domain tests без явного указания пути.

---

### AC-06: Единственный HTTP API (Flask API удалён)

Контекст: `yandex_api_integration.py` — Flask API существует параллельно с FastAPI в `api/`. Два HTTP-сервера в одном проекте. `test_yandex_api_integration.py` тестирует мёртвый код. `mypy` игнорирует ошибки в этом файле через `[[tool.mypy.overrides]]`.

Критерии:
- `yandex_api_integration.py` удалён из репозитория
- `tests/unit/test_yandex_api_integration.py` удалён или полностью переписан для FastAPI (`httpx.AsyncClient(app=app)`)
- `[[tool.mypy.overrides]]` для `yandex_api_integration` удалён из `pyproject.toml`
- `ruff check .` и `mypy` не показывают orphaned imports

Проверяется через: `git status` не содержит `yandex_api_integration.py`; `pytest` проходит.

---

### Фаза 1 — AC-1x

---

### AC-10: `python main.py` запускает сервер с корректным логированием

Критерии:
- `python main.py` запускает FastAPI сервер на порту из `PORT` env переменной (по умолчанию 8000)
- Логи выводятся в JSON-формате (поля: `timestamp`, `level`, `message`, `logger`)
- `LOG_DIR` из `.env` создаётся автоматически при отсутствии
- При `SIGTERM` сервер корректно завершает работу: BLE-устройства отключаются, polling останавливается
- `HEAD /v1.0/` возвращает HTTP 200 после старта

Проверяется через: запуск с тестовым `.env`; `curl -I http://localhost:8000/v1.0/`; `kill -TERM <pid>` без ошибок.

---

### AC-11: Все 5 Yandex Smart Home endpoints соответствуют спецификации v1.0

Критерии:
- `HEAD /v1.0/` возвращает HTTP 200
- `GET /v1.0/user/devices` возвращает JSON с полями `request_id`, `payload.user_id`, `payload.devices`
- `POST /v1.0/user/devices/query` возвращает состояние каждого запрошенного устройства
- `POST /v1.0/user/devices/action` выполняет команду и возвращает результат по каждому устройству
- `POST /v1.0/user/devices/unlink` возвращает HTTP 200 OK
- `request_id` во всех ответах берётся из заголовка `X-Request-Id` запроса
- OAuth middleware блокирует запросы без корректного токена (HTTP 401)
- Тесты покрывают все 5 endpoints с мокированным OAuth и Operator

Проверяется через: `pytest tests/unit/test_api_yandex.py`.

---

### AC-12: `POST /api/devices/discover` возвращает список BLE-устройств

Критерии:
- `POST /api/devices/discover` запускает BLE-сканирование на 30 секунд (или значение из параметра запроса `timeout`)
- Ответ содержит список устройств: `[{"name": "...", "mac_address": "...", "rssi": ...}]`
- При таймауте (BLE недоступен) возвращает HTTP 408 или пустой список с предупреждением
- Фильтрация по имени `Tion_Breezer_*` применяется при сканировании
- Тест мокирует `bleak.BleakScanner.discover`

Проверяется через: `pytest tests/unit/test_api_devices.py::test_discover_devices`.

---

### AC-13: Yandex callback отправляется при изменении статуса устройства

Контекст: `send_yandex_callback()` реализована, но не вызывается из `Operator._poll_devices()` или `_update_devices_status()`.

Критерии:
- `Operator._update_devices_status()` или `_poll_devices()` сравнивает текущий статус с кешированным
- При обнаруженном изменении `fan_speed`, `heater_state`, `is_on` — вызывается `send_yandex_callback()`
- `send_yandex_callback()` использует `httpx.AsyncClient` с таймаутом 5.0 сек
- При HTTP-ошибке Яндекс API — ошибка логируется, polling продолжается (не падает)
- `YANDEX_SKILL_ID` и `YANDEX_CALLBACK_TOKEN` берутся из `.env`
- Тест мокирует `httpx.AsyncClient.post` и проверяет тело запроса

Проверяется через: `pytest tests/unit/test_callback_sender.py`.

---

### AC-14: Все BLE-операции защищены таймаутом

Критерии (верификация уже реализованного):
- `asyncio.wait_for(..., timeout=BLE_OPERATION_TIMEOUT)` присутствует в: `get_device_status()`, `_set_device_property()`, `_update_devices_status()`
- `asyncio.TimeoutError` перехватывается явно с `_LOGGER.warning("BLE timeout: %s", device_id)` (без f-string)
- `BLE_OPERATION_TIMEOUT` конфигурируется через `BLE_OPERATION_TIMEOUT` в `.env` (по умолчанию 10.0)
- `ruff check tion_btle/operator.py` проходит без ошибок

Проверяется через: `pytest tests/unit/test_operator.py::test_ble_timeout`.

---

### Фаза 2 — AC-2x

---

### AC-20: `POST /api/groups/{id}/action` выполняет команду параллельно

Критерии:
- Существует `api/routes/groups.py` с endpoints: POST/GET /api/groups, GET/PUT/DELETE /api/groups/{id}, POST /api/groups/{id}/action
- `POST /api/groups/{id}/action` вызывает `asyncio.gather()` для всех устройств группы
- Ответ содержит статус выполнения по каждому устройству: `[{"device_id": "...", "status": "ok"/"error", "error": "..."}]`
- При частичной ошибке (одно устройство недоступно) — возвращает HTTP 207 Multi-Status
- Тест проверяет параллельное выполнение с мокированным Operator

Проверяется через: `pytest tests/unit/test_api_groups.py`.

---

### AC-21: MQTT-клиент работает без блокировки event loop

Критерии:
- `tion_btle/mqtt_client.py` содержит `MqttSensorClient` с интерфейсом `ISensorDataSource`
- `MqttSensorClient` — asyncio-native (использует `aiomqtt` или аналог)
- При недоступности MQTT-брокера: `_LOGGER.warning(...)`, сервис продолжает работу
- При CO₂ > 1000 ppm — сценарий "co2_turbo" активируется автоматически через `Operator`
- Конфигурация через `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_TOPIC_PREFIX` из `.env`
- Тест мокирует MQTT-брокер

Проверяется через: `pytest tests/unit/test_mqtt_client.py`.

---

### AC-22: Веб-интерфейс доступен по адресу `/web/devices`

Критерии:
- `GET /web/devices` возвращает HTML-страницу с кодом 200
- Страница отображает список зарегистрированных устройств с текущим статусом
- Присутствует кнопка "Сканировать BLE" (вызывает `POST /api/devices/discover`)
- Присутствует форма добавления устройства (вызывает `POST /api/devices/register`)
- Страница работает без JavaScript-фреймворков (vanilla JS или htmx)
- CSS подключается из статики (не из CDN) — работает оффлайн

Проверяется через: `curl http://localhost:8000/web/devices` возвращает HTML с кодом 200.

---

### AC-23: Покрытие тестами > 80% для каждого модуля

Критерии:
- `pytest --cov=tion_btle --cov=api --cov-report=term` показывает > 80% для каждого модуля
- `tests/unit/test_device_manager.py` заполнен (минимум 10 тест-кейсов)
- Существуют файлы: `test_api_devices.py`, `test_api_yandex.py`, `test_callback_sender.py`
- Тесты не требуют реального BLE-оборудования (все BLE-вызовы замокированы)
- CI публикует coverage report

Проверяется через: `pytest --cov --cov-fail-under=80`.

---

### AC-24: JSON-логи с ротацией настроены корректно

Критерии:
- `app.log` содержит записи в JSON-формате (каждая строка — валидный JSON)
- `ble.log` содержит только BLE DEBUG-события
- Ротация при достижении 10 МБ (maxBytes=10485760, backupCount=5)
- `setup_logging()` вынесен в `tion_btle/logging_config.py`
- `main.py` импортирует `setup_logging` из `tion_btle.logging_config`

Проверяется через: `python main.py` создаёт JSON-логи в `LOG_DIR`; `python -c "import json; [json.loads(l) for l in open('app.log')]"` не выбрасывает исключений.

---

### AC-25: systemd юнит-файл задокументирован

Критерии:
- `deploy/tion-breezer.service` существует и содержит корректные секции `[Unit]`, `[Service]`, `[Install]`
- `deploy/README.md` содержит инструкцию по установке юнита
- `ExecStart` использует переменные из `EnvironmentFile` (не жёстко прописанные пути)
- `EnvironmentFile` указывает на `.env` файл

Проверяется через: `systemd-analyze verify deploy/tion-breezer.service`.

---

### Фаза 3 — AC-3x

---

### AC-30: Redis-кеширование с автоматическим fallback на InMemoryCache

Критерии:
- `tion_btle/cache.py` содержит `ICache`, `InMemoryCache`, `RedisCache`
- При недоступности Redis — автоматически используется `InMemoryCache`
- OAuth токены кешируются с TTL 3600 сек
- Device status кешируется с TTL 30 сек
- `ICache` передаётся в `Operator` как зависимость (не создаётся внутри)

Проверяется через: `pytest tests/unit/test_cache.py`.

---

### AC-31: История команд сохраняется в SQLite

Критерии:
- Таблица `command_history` существует: `id, device_id, command, params, result, timestamp`
- Каждая команда из `Operator.set_*` записывается в `command_history`
- `GET /api/devices/{id}/history?limit=100` возвращает историю с пагинацией
- История сохраняется после рестарта сервиса

Проверяется через: `pytest tests/unit/test_history.py`.

---

### AC-32: `mypy --strict` проходит без ошибок

Критерии:
- `from __future__ import annotations` присутствует во всех файлах `tion_btle/domain/device_manager/`
- `Optional[X]`, `List[X]`, `Dict[K, V]` заменены на `X | None`, `list[X]`, `dict[K, V]`
- `name: str = None` заменено на `name: str | None = None` везде
- `mypy --strict tion_btle/ api/` завершается без ошибок
- CI содержит шаг `mypy --strict`

Проверяется через: `mypy --strict tion_btle/ api/`.

---

### AC-33: Google-style docstrings для всех публичных методов

Критерии:
- Все публичные методы в `DeviceManager`, `Operator`, `Scenarist`, API роутах имеют docstrings
- Docstrings содержат секции `Args:`, `Returns:`, `Raises:` (где применимо)
- `pydocstyle --convention=google tion_btle/ api/` проходит без ошибок

Проверяется через: `pydocstyle --convention=google tion_btle/ api/`.

---

## Edge Cases

### BLE

- __Устройство не найдено при сканировании:__ `POST /api/devices/discover` возвращает пустой список, а не 404.
- __BLE-таймаут во время команды:__ `asyncio.TimeoutError` → HTTP 504 Gateway Timeout с сообщением об ошибке; polling не останавливается.
- __Потеря BLE-соединения в момент отправки команды:__ повторное подключение с экспоненциальным backoff (1s, 2s, 4s... до 60s).
- __Дублирующийся MAC-адрес при регистрации:__ upsert по MAC — обновляет существующую запись, не создаёт дубликат.
- __Несколько одновременных BLE-операций:__ `asyncio.Semaphore(1)` сериализует доступ на уровне устройства; очередь не должна накапливать устаревшие команды.
- __BLE-адаптер недоступен (bluetooth выключен):__ `BleakError` с корректным сообщением; сервис продолжает работу, HTTP API доступен.
- __Потеря соединения в середине многопакетной команды (TionLiteFamily):__ транзакционность команды — при `BleakError` в середине чанков сбрасывать и повторять команду целиком.

### API

- __`POST /api/devices/register` с несуществующим MAC-адресом:__ устройство регистрируется в БД без проверки доступности — BLE-подключение происходит позже при команде. Это ожидаемое поведение.
- __`DELETE /api/devices/{id}` для несуществующего устройства:__ HTTP 404 с телом `{"error": "Device not found"}`.
- __`POST /v1.0/user/devices/action` для устройства без BLE-подключения:__ HTTP 200 с `action_result.status = "ERROR"` (Яндекс требует 200 даже при ошибке устройства).
- __`GET /v1.0/user/devices` для пустой БД:__ возвращает `payload.devices = []`, не 404.
- __Яндекс OAuth токен истёк во время запроса:__ middleware возвращает HTTP 401; токен удаляется из кеша.
- __Параллельные запросы к одному устройству:__ очередь команд на устройство через Semaphore; нет race condition.

### База данных

- __`devices.db` недоступна при старте:__ сервис не запускается; ошибка логируется с конкретным путём к файлу.
- __Повреждённая SQLite БД:__ `sqlite3.DatabaseError` перехватывается явно; логируется `ERROR` с путём к файлу.
- __DB_PATH не задан в .env:__ используется путь по умолчанию `./devices.db`; `WARNING` в лог.

### Callback

- __Яндекс callback API недоступен:__ ошибка логируется с `WARNING`, polling не останавливается.
- __Частое изменение статуса (дребезг):__ не более 1 callback в секунду на устройство (debounce).
- __`YANDEX_SKILL_ID` или `YANDEX_CALLBACK_TOKEN` не заданы:__ callback отключается с `WARNING`, polling работает.

### MQTT

- __MQTT-брокер недоступен при старте:__ `WARNING` в лог, сервис работает без MQTT (BLE-only режим).
- __Устаревшие данные с датчика (нет пакета > 5 минут):__ TTL истёк → датчик считается недоступным, `None` в `SensorData`.
- __CO₂ > 1000 ppm, но сценарий уже активен:__ дубликат выполнения не происходит (идемпотентность триггера).

---

## Неясности / вопросы

1. __Конфликт двух DeviceManager в runtime:__ `api/app.py` создаёт `DeviceManager`, `Operator.__init__` создаёт свой. Два экземпляра с разными `SQLiteDeviceStorage` — запись через один не видна другому. Требует архитектурного решения: либо `Operator` принимает `DeviceManager` как зависимость (DI), либо `api/app.py` использует `operator.device_manager` напрямую.

2. __`pair_device` через `operator.device_manager`:__ `api/routes/devices.py:96` обращается к `operator.device_manager` как к публичному атрибуту. Если `device_manager` не является публичным — нужен публичный метод `operator.pair_device(device_id)`.

3. __Scenarist и персистентность статистики:__ `Scenarist._init_db()` создаёт таблицу `scenarios`, но `last_executed`, `execution_count`, `last_status` не записываются в БД — теряются при рестарте. Нужно определить: добавить колонки в таблицу `scenarios` в `Scenarist` или вынести в `SQLiteDeviceStorage`.

4. __Путь к `devices.db`:__ файл создаётся в корне репозитория, а не по `DB_PATH` из `.env`. Необходимо проверить, передаётся ли `DB_PATH` при инициализации `SQLiteDeviceStorage` в `api/app.py` и `Operator.__init__`.

5. __Фильтрация BLE при сканировании:__ план указывает фильтрацию по "Tion_Breezer_*", но текущая реализация `discover_devices()` возвращает все или фильтрованные устройства — нужно уточнить из кода `DeviceManager.discover_devices()`.

---

## Приоритизация

### Немедленно (блокирует всё остальное)

__Приоритет 1 — AC-01: Исправить CI__
CI сломан: ссылается на удалённый `requirements_test.txt`. Любой PR не проходит автоматическую проверку. Без этого невозможно безопасно вносить изменения.

__Приоритет 2 — AC-02: Исправить register_device__
Основная функция задачи TION-001 (регистрация устройств через API) недоступна. `POST /api/devices/register` всегда выбрасывает `TypeError`. Это основная ценность текущего Sprint.

__Приоритет 3 — AC-03: Исправить delete_device await__
Молчаливая ошибка: endpoint возвращает 200 OK, но не выполняет действие. Опасный паттерн — данные рассинхронизированы.

__Приоритет 4 — AC-04: Устранить except Exception: pass__
Нарушение CLAUDE.md. Скрывает ошибки при BLE-операциях; исправить также f-string logging в operator.py и device_manager.py.

__Приоритет 5 — AC-05: Добавить domain tests в testpaths__
Тесты domain/ не запускаются. Регрессии в DeviceManager и SQLiteDeviceStorage невидимы.

__Приоритет 6 — AC-06: Удалить yandex_api_integration.py__
Мёртвый код. Тесты Flask тестируют несуществующую логику. Mypy его игнорирует — скрывает ошибки типизации в codebase.

### После критических исправлений (Фаза 1)

__Приоритет 7 — Устранить двойную инициализацию DeviceManager (Неясность 1)__
Архитектурная проблема. До исправления — записи через api/app.py могут не отображаться в Operator и наоборот.

__Приоритет 8 — AC-13: Интеграция callback с polling__
`send_yandex_callback()` реализована, но нигде не вызывается. Push-уведомления Яндексу не работают.

__Приоритет 9 — AC-11: Тесты api/ endpoints__
Покрытие api/ = 0%. Без тестов изменения в API небезопасны.

__Приоритет 10 — AC-14: Верификация BLE таймаутов__
Формально реализовано (по данным explorer), но тесты для таймаутов отсутствуют — нет подтверждения корректности.

### Фаза 2 (после стабилизации Фазы 1)

- AC-20: Групповые команды через API
- AC-21: MQTT-интеграция
- AC-22: Веб-интерфейс
- AC-23: Покрытие тестами > 80%
- AC-24: Вынести logging_config.py
- AC-25: systemd юнит

### Фаза 3 (после завершения Фазы 2)

- AC-30: Redis-кеширование
- AC-31: История команд
- AC-32: mypy strict
- AC-33: Google-style docstrings

