# Architect Report — TION-001

Date: 2026-03-05
Branch: feature-search-and-register-devices
Agent: architect (v2 — на основе фактического состояния кода после частичной реализации)

> Эта версия заменяет предыдущую от 2026-03-04.
> Предыдущая версия проектировала систему с нуля. Текущая фиксирует конкретные исправления
> для уже существующего кода (FastAPI реализован, `api/` создан, `pyproject.toml` существует).

---

## Архитектурное решение

### Проблема 1: CI broken

**Файл:** `.github/workflows/tests.yml`

**Изменение:**
- Строка 18: матрица Python `['3.9', '3.10']` → `['3.10', '3.11']`
- Строка 24: `actions/checkout@v2.3.4` → `actions/checkout@v4`
- Строка 27: `actions/setup-python@v4` → `actions/setup-python@v5`
- Строки 35–40: заменить `pip install -r requirements_test.txt` на `uv sync --group dev` (с шагом `astral-sh/setup-uv@v3`)
- Строка 43: убрать `--cov=yandex_api_integration` (файл удаляется в Task-7), добавить `--cov=api`; убрать явное указание путей (они берутся из `testpaths` после Task-5)

**Причина:** `requirements_test.txt` удалён из репозитория (помечен D в git status). CI падает на шаге установки зависимостей при каждом push. Все dev-зависимости перенесены в `[dependency-groups] dev` в `pyproject.toml`, управляемый через `uv`.

---

### Проблема 2: register_device сигнатура

**Файл:** `tion_btle/domain/device_manager/device_manager.py`, строки 47–65

**Изменение:** переписать сигнатуру `register_device`.

Было:
```python
async def register_device(
    self, device: BLEDevice, name: str = None, auto_pair: bool = False
) -> DeviceInfo:
```

Стало:
```python
async def register_device(
    self,
    name: str,
    mac_address: str,
    model: str,
    room: str | None = None,
    auto_pair: bool = False,
) -> DeviceInfo:
```

Тело метода: вместо `get_device_class(device.name)` использовать маппинг по `model`:
```python
_MODEL_TO_TYPE: dict[str, type[Tion]] = {"S3": TionS3, "S4": TionS4, "Lite": TionLite}
device_class = _MODEL_TO_TYPE.get(model, Tion)
device_info = DeviceInfo(
    id=mac_address,
    name=name,
    type=device_class.__name__,
    mac_address=mac_address,
    model=model,
    room=room,
)
```

Сопутствующее: обновить `discover_and_register_all` (строки 168–181) — он вызывает `register_device(device)` со старой сигнатурой.

Также в `api/routes/devices.py` строки 94–100 (блок `if body.auto_pair`) — удалить, т.к. `auto_pair` теперь передаётся напрямую в `register_device` как параметр и обрабатывается внутри метода.

**Причина:** `api/routes/devices.py:87–92` вызывает метод с kwargs `(name=, mac_address=, model=, room=)`, что соответствует `RegisterRequest` (Pydantic-схема). `BLEDevice` — объект Bleak, недоступный в HTTP-контексте без предварительного сканирования. Текущий вызов всегда выбрасывает `TypeError`. По плану TION-001/plan.md раздел 1.3 правильный интерфейс: `register_device(name, mac, model, room)`. Поле `room` уже есть в `DeviceInfo` (строка 14 `models.py`) — модель изменять не нужно.

---

### Проблема 3: delete_device без await

**Файл:** `api/routes/devices.py`, строка 213

**Изменение:**
```python
# было:
device_manager.delete_device(device_id)

# стало:
await device_manager.delete_device(device_id)
```

**Причина:** `DeviceManager.delete_device()` объявлен `async def` (строка 118 `device_manager.py`) — вызывает внутри `unpair_device`. Без `await` Python создаёт coroutine-объект, но не исполняет его. Устройство остаётся `is_active=True` в SQLite. Endpoint возвращает HTTP 200, вводя клиента в заблуждение. Молчаливая ошибка без исключения.

---

### Проблема 4: except Exception без логирования

**Файл:** `tion_btle/operator.py`, строки 531, 202, 452, 474, 557

**Изменения:**

Строки 531–532 (критическое нарушение — `pass` без логирования):
```python
# было:
except Exception:
    pass

# стало:
except Exception:
    _LOGGER.warning(
        "Failed to disconnect device %s before reconnect",
        device_id,
        exc_info=True,
    )
```

Строка 202 (f-string без `exc_info`):
```python
# было:
_LOGGER.error(f"Polling error: {str(e)}")
# стало:
_LOGGER.error("Polling error: %s", e, exc_info=True)
```

Строка 452:
```python
# было:
_LOGGER.error(f"Failed to execute scenario {scenario_id}: {str(e)}")
# стало:
_LOGGER.error("Failed to execute scenario %s: %s", scenario_id, e, exc_info=True)
```

Строка 474:
```python
# было:
_LOGGER.error(f"Scenario execution error: {str(e)}")
# стало:
_LOGGER.error("Scenario execution error: %s", e, exc_info=True)
```

Строка 557:
```python
# было:
_LOGGER.error(f"Error disconnecting device {device_id}: {str(e)}")
# стало:
_LOGGER.error("Error disconnecting device %s: %s", device_id, e, exc_info=True)
```

**Причина:** CLAUDE.md запрещает `except Exception:` без повторного raise или явного логирования. Строка 531 — `pass` без каких-либо действий скрывает ошибки BLE disconnect при переподключении. Остальные случаи используют f-string logging (теряется возможность lazy evaluation) и не передают `exc_info=True` (traceback не попадает в лог).

---

### Проблема 5: domain tests не в testpaths

**Файл:** `pyproject.toml`, строка 92

**Изменение:**
```toml
# было:
testpaths = ["tests"]

# стало:
testpaths = ["tests", "tion_btle/domain/device_manager/tests"]
```

**Причина:** `tion_btle/domain/device_manager/tests/` содержит `test_device_manager.py` и `test_sqlite_storage.py` с полноценными тестами. При `pytest` без аргументов они не запускаются. Регрессии в `DeviceManager` и `SQLiteDeviceStorage` невидимы.

---

### Проблема 6: test_device_manager.py пустой

**Файл:** `tests/unit/test_device_manager.py`

**Изменение:** написать минимум 10 тест-кейсов (подробный шаблон в `architect_plan.md`).

Покрываемые сценарии:
- Новая сигнатура `register_device(name, mac_address, model, room, auto_pair)`
- Маппинг `model` → `device_class` для S3, S4, Lite, неизвестной модели
- `delete_device` — вызывает `storage.delete_device`
- `get_devices` — возвращает список
- `get_device` — возвращает None для несуществующего
- `get_device_capabilities` для S3 (heater=True, light=False) и Lite (heater=False, light=True)
- `get_connected_devices` — фильтрация по `is_active=True` и `is_paired=True`

**Причина:** файл содержит 1 строку без тестов. Domain-тесты в `tion_btle/domain/device_manager/tests/` уже покрывают `DeviceManager` напрямую, но тесты в `tests/unit/` являются стандартным местом для unit-тестов уровня приложения. Новая сигнатура `register_device` после Task-2 не будет покрыта без этого файла.

---

### Проблема 7: yandex_api_integration.py конфликт с новым API

**Файлы:**
- `yandex_api_integration.py` — удалить через `git rm`
- `tests/unit/test_yandex_api_integration.py` — удалить через `git rm`
- `pyproject.toml` строки 85–87 — удалить секцию `[[tool.mypy.overrides]]` для `yandex_api_integration`

**Причина:** Flask API в `yandex_api_integration.py` полностью дублируется FastAPI в `api/routes/yandex.py`. Два HTTP-сервера в одном проекте нарушают архитектуру. `test_yandex_api_integration.py` тестирует мёртвый код. Секция `mypy.overrides` с `ignore_errors = true` скрывает ошибки типизации, маскируя потенциальные проблемы. После удаления mypy проверяет весь активный код без исключений.

---

## Подзадачи (в порядке выполнения)

### Task-1: Исправить CI

**Файлы:**
- `.github/workflows/tests.yml`

**Изменения:**
```yaml
# матрица:
python: ['3.10', '3.11']

# actions:
uses: actions/checkout@v4
uses: actions/setup-python@v5

# вместо pip install -r requirements_test.txt:
- name: Install uv
  uses: astral-sh/setup-uv@v3
- name: Install dependencies
  run: uv sync --group dev

# pytest (testpaths возьмёт пути из pyproject.toml после Task-5):
run: uv run pytest --cov=tion_btle --cov=api --cov-report=xml --cov-report=term
```

**Критерии готовности:**
- Workflow запускается без ошибки "requirements_test.txt not found"
- Python 3.9 исключён из матрицы; тестируются 3.10 и 3.11
- Устаревшие версии actions заменены актуальными
- Coverage report включает `tion_btle/` и `api/`

---

### Task-2: Исправить register_device

**Файлы:**
- `tion_btle/domain/device_manager/device_manager.py` (строки 47–65, 168–181)
- `api/routes/devices.py` (строки 86–116 — убрать блок auto_pair строки 94–100)

**Изменения:** новая сигнатура `register_device(self, name, mac_address, model, room=None, auto_pair=False)`, маппинг по `model`, обновление `discover_and_register_all`, удаление дублирующего блока auto_pair из routes.

**Критерии готовности:**
- `POST /api/devices/register {"name":"...", "mac_address":"AA:BB:CC:DD:EE:FF", "model":"S3"}` возвращает HTTP 201
- Нет `TypeError: register_device() got unexpected keyword argument 'mac_address'`
- `discover_and_register_all` работает корректно

---

### Task-3: Исправить delete_device await

**Файлы:**
- `api/routes/devices.py` (строка 213)

**Изменения:** добавить `await` перед `device_manager.delete_device(device_id)`.

**Критерии готовности:**
- `DELETE /api/devices/{id}` устанавливает `is_active=False` в SQLite
- `GET /api/devices` не возвращает удалённое устройство

---

### Task-4: Исправить except Exception в operator.py

**Файлы:**
- `tion_btle/operator.py` (строки 531, 202, 452, 474, 557)

**Изменения:** строка 531 — заменить `pass` на `_LOGGER.warning(..., exc_info=True)`; строки 202, 452, 474, 557 — добавить `exc_info=True`, заменить f-string на `%s` формат.

**Критерии готовности:**
- `ruff check tion_btle/operator.py` не выдаёт B110 (try-except-pass)
- Все `except Exception` в `operator.py` содержат явное логирование

---

### Task-5: Добавить domain tests в testpaths

**Файлы:**
- `pyproject.toml` (строка 92)

**Изменения:**
```toml
testpaths = ["tests", "tion_btle/domain/device_manager/tests"]
```

**Критерии готовности:**
- `pytest --collect-only` включает `tion_btle/domain/device_manager/tests/` без явного указания пути
- Domain tests попадают в coverage report

---

### Task-6: Заполнить tests/unit/test_device_manager.py

**Файлы:**
- `tests/unit/test_device_manager.py`

**Изменения:** написать 10+ тест-кейсов. Шаблон с конкретными именами тестов и кодом приведён в `architect_plan.md`.

**Критерии готовности:**
- `pytest tests/unit/test_device_manager.py` — все тесты зелёные
- Нет зависимости от реального BLE-оборудования (все BLE-вызовы замокированы)

---

### Task-7: Удалить yandex_api_integration.py

**Файлы:**
- `yandex_api_integration.py` — git rm
- `tests/unit/test_yandex_api_integration.py` — git rm
- `pyproject.toml` — удалить строки 85–87 (`[[tool.mypy.overrides]] module = ["yandex_api_integration"] ignore_errors = true`)

**Критерии готовности:**
- Файлы отсутствуют в репозитории
- `pytest` проходит без ошибок
- `mypy` не использует override для `yandex_api_integration`
- `ruff check .` не выдаёт orphaned imports

---

## Зависимости между задачами

**Независимые (можно параллельно):**
- Task-1 (CI), Task-4 (except Exception), Task-5 (testpaths), Task-7 (Flask удалить)

**Последовательные:**
- Task-2 (register_device) + Task-3 (await delete) — логично в одном PR, оба затрагивают связанные файлы
- Task-6 (тесты) — зависит от Task-2 (тесты проверяют новую сигнатуру `register_device`)

**Рекомендуемый порядок PR:**

| Порядок | Task | Обоснование |
|---|---|---|
| 1 | Task-1 | Восстановить CI первым — без него PR нельзя проверить автоматически |
| 2 | Task-7 | Убрать мёртвый код; после этого `ruff` и `mypy` чище |
| 3 | Task-4 | Изолированное изменение, не влияет на API |
| 4 | Task-5 | Конфигурационное изменение; после него domain tests видны в CI |
| 5 | Task-2 + Task-3 | Ядро TION-001 — один PR, оба изменяют связанные файлы |
| 6 | Task-6 | Тесты для новой сигнатуры — после Task-2 |

**Граф:**
```
Task-1 ─────────────────────────────────────────┐
Task-7 ─────────────────────────────────────────┤
Task-4 ─────────────────────────────────────────┤──► merge в master
Task-5 ─────────────────────────────────────────┤
Task-2 ──► Task-3 ──► Task-6 ──────────────────┘
```

---

## Дополнительный риск (вне текущего плана)

### Двойная инициализация DeviceManager

`api/app.py` создаёт `DeviceManager` и кладёт в `app.state.device_manager`. `Operator.__init__` внутри создаёт свой `DeviceManager`. Два независимых экземпляра с разными `SQLiteDeviceStorage` объектами на одном файле БД. Запись через `app.state.device_manager` не видна `operator.device_manager` (в памяти). Это архитектурная проблема, но она не блокирует текущие задачи.

**Временная митигация (без изменений кода):** `api/routes/devices.py` использует `_get_device_manager(request)` (из `app.state`); Яндекс-роуты используют `operator` — разные `DeviceManager`, но оба читают/пишут в один SQLite. При каждом запросе данные читаются из БД, поэтому рассинхронизация проявится только если один экземпляр кеширует данные в памяти без инвалидации.

**Рекомендация для Фазы 1 следующей итерации:** `api/app.py` должен передавать `operator.device_manager` в `app.state.device_manager`, а не создавать отдельный экземпляр.

---

## Статус

Ожидает утверждения
