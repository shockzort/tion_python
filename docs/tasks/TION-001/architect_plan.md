# Architect Plan — TION-001: Детальный план исправлений

Date: 2026-03-05
Branch: feature-search-and-register-devices
Agent: architect
Scope: Фаза 0 + Фаза 1 (критические и высокоприоритетные исправления)

---

## Контекст

На основе отчётов explorer и analyst выявлены следующие критические проблемы, блокирующие работу:

1. **CI broken** — `.github/workflows/tests.yml` ссылается на удалённый `requirements_test.txt`
2. **register_device сигнатура** — `DeviceManager.register_device()` принимает `BLEDevice`, а `api/routes/devices.py` вызывает с kwargs `(name, mac_address, model, room)`
3. **delete_device без await** — coroutine не исполняется (молчаливая ошибка)
4. **except Exception: pass** — `tion_btle/operator.py:531` нарушает CLAUDE.md
5. **domain tests не в testpaths** — `tion_btle/domain/device_manager/tests/` не запускается при `pytest` без явного указания пути
6. **test_device_manager.py пустой** — файл `tests/unit/test_device_manager.py` содержит только 1 строку без тестов
7. **yandex_api_integration.py** — Flask API существует параллельно с FastAPI; мёртвый код; mypy его игнорирует

---

## Архитектурные решения

### Решение для register_device (Проблема 2)

**Выбор стороны изменения:** изменить `DeviceManager.register_device()`, а не вызывающий код.

**Обоснование:**
- `api/routes/devices.py` вызывает метод с семантически правильными аргументами: `name`, `mac_address`, `model`, `room` — это то, что реально знает HTTP-клиент
- `BLEDevice` — объект Bleak-библиотеки, недоступный через HTTP API без предварительного сканирования
- Согласно плану TION-001/plan.md (раздел 1.3): `device_manager.register_device(name, mac, model, room)` — это правильный интерфейс
- Текущая сигнатура с `BLEDevice` нарушает принцип слоёв: доменная логика зависит от транспортного объекта Bleak
- Функция `discover_and_register_all` внизу `device_manager.py` использует `register_device(device)` — её нужно обновить

**Новая сигнатура:**
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

**Маппинг типов устройств:** вместо `get_device_class(device.name)` определять тип из параметра `model`:
```python
MODEL_TO_TYPE = {
    "S3": TionS3,
    "S4": TionS4,
    "Lite": TionLite,
}
device_class = MODEL_TO_TYPE.get(model, Tion)
```

### Решение для yandex_api_integration.py (Проблема 7)

**Решение:** удалить файл и связанные тесты.

**Обоснование:**
- Flask API полностью дублируется FastAPI в `api/`
- `test_yandex_api_integration.py` тестирует мёртвый код
- `[[tool.mypy.overrides]]` для `yandex_api_integration` скрывает ошибки типизации
- Файл помечен как `yandex_api_integration.py` без статуса D — он не удалён, но и не нужен
- Удаление позволяет убрать `mypy override` и очистить `pyproject.toml`

**Сопутствующие изменения:**
- Удалить `tests/unit/test_yandex_api_integration.py`
- Удалить секцию `[[tool.mypy.overrides]] module = ["yandex_api_integration"]` из `pyproject.toml`

### Решение для test_device_manager.py (Проблема 6)

**Два файла:** есть пустой `tests/unit/test_device_manager.py` и полный `tion_btle/domain/device_manager/tests/test_device_manager.py`.

**Решение:** заполнить `tests/unit/test_device_manager.py` тестами, ориентированными на интеграцию с `api/` (тесты API-слоя, использующие `DeviceManager`). Domain-тесты (unit-тесты самого `DeviceManager`) уже есть в `tion_btle/domain/device_manager/tests/`.

---

## Task-1: Исправить CI

### Файлы
- `.github/workflows/tests.yml` — изменить

### Конкретные изменения

**Строка 18:** изменить матрицу Python с `['3.9', '3.10']` на `['3.10', '3.11']`

**Строка 24:** заменить устаревший action:
```yaml
# было:
uses: actions/checkout@v2.3.4
# стало:
uses: actions/checkout@v4
```

**Строка 27:** заменить устаревший action:
```yaml
# было:
uses: actions/setup-python@v4
# стало:
uses: actions/setup-python@v5
```

**Строки 35–40:** заменить установку зависимостей. Вместо:
```yaml
- name: Install dependencies
  run: |
    python -m pip install --upgrade pip
    pip install setuptools wheel twine

- name: Install requirements
  run: pip install -r requirements_test.txt
```
Написать:
```yaml
- name: Install uv
  uses: astral-sh/setup-uv@v3

- name: Install dependencies
  run: uv sync --group dev
```

**Строка 43:** обновить команду pytest и покрытие:
```yaml
# было:
run: pytest tests/${{ matrix.type }} tion_btle/domain/device_manager/tests/ --cov=tion_btle --cov=yandex_api_integration --cov-report=xml

# стало:
run: uv run pytest --cov=tion_btle --cov=api --cov-report=xml --cov-report=term
```

Примечание: `testpaths` в `pyproject.toml` будет обновлён в Task-5, поэтому явно указывать пути в CI не нужно — pytest возьмёт их из конфигурации.

### Критерии готовности
- Workflow запускается без ошибки "requirements_test.txt not found"
- Python 3.9 исключён из матрицы
- Используются актуальные версии actions
- `uv sync --group dev` устанавливает все зависимости из `pyproject.toml`
- Coverage report включает `tion_btle/` и `api/`

---

## Task-2: Исправить register_device

### Файлы
- `tion_btle/domain/device_manager/device_manager.py` — изменить сигнатуру `register_device`
- `tion_btle/domain/device_manager/device_manager.py` — обновить `discover_and_register_all`

### Конкретные изменения

**Строки 47–65 (`register_device`):**

```python
# БЫЛО:
async def register_device(
    self, device: BLEDevice, name: str = None, auto_pair: bool = False
) -> DeviceInfo:
    """Register new device"""
    device_class = self.get_device_class(device.name)
    device_info = DeviceInfo(
        id=device.address,
        name=name or self._generate_device_name(device.name),
        type=device_class.__name__,
        mac_address=device.address,
        model=device_class.__name__.replace("Tion", ""),
    )
    self.device_storage.create_device(device_info)
    if auto_pair:
        await self.pair_device(device_info.id)
    return device_info

# СТАЛО:
async def register_device(
    self,
    name: str,
    mac_address: str,
    model: str,
    room: str | None = None,
    auto_pair: bool = False,
) -> DeviceInfo:
    """Register a new Tion device by MAC address.

    Args:
        name: Human-friendly device name.
        mac_address: BLE MAC address (e.g. 'AA:BB:CC:DD:EE:FF').
        model: Device model string ('S3', 'S4', 'Lite').
        room: Optional room name.
        auto_pair: If True, initiate BLE pairing immediately.

    Returns:
        Created DeviceInfo instance.
    """
    _MODEL_TO_TYPE: dict[str, type[Tion]] = {
        "S3": TionS3,
        "S4": TionS4,
        "Lite": TionLite,
    }
    device_class = _MODEL_TO_TYPE.get(model, Tion)
    device_info = DeviceInfo(
        id=mac_address,
        name=name,
        type=device_class.__name__,
        mac_address=mac_address,
        model=model,
        room=room,
    )
    self.device_storage.create_device(device_info)
    if auto_pair:
        await self.pair_device(device_info.id)
    return device_info
```

**Строки 168–181 (`discover_and_register_all`):** обновить вызов:
```python
# БЫЛО:
device_info = await manager.register_device(device)

# СТАЛО:
device_class = manager.get_device_class(device.name or "")
model = device_class.__name__.replace("Tion", "")
device_info = await manager.register_device(
    name=manager._generate_device_name(device.name or device.address),
    mac_address=device.address,
    model=model,
)
```

**Строка 4 (импорты):** `BLEDevice` импортируется только в `discover_devices` — оставить импорт, он используется как тип возврата.

**Модель DeviceInfo:** проверить наличие поля `room` в `tion_btle/domain/device_manager/models.py`. Если отсутствует — добавить `room: str | None = None`.

### Дополнительно — `api/routes/devices.py` строка 96

Строка `await operator.device_manager.pair_device(device.id)` обращается к `operator.device_manager` как к публичному атрибуту. Это допустимо, так как `Operator.__init__` устанавливает `self.device_manager = DeviceManager(...)` публично. Но здесь используется `operator.device_manager.pair_device()`, а не `device_manager.pair_device()` из `_get_device_manager`. Это создаёт риск рассинхронизации двух `DeviceManager` экземпляров (из `app.state.device_manager` и из `operator.device_manager`).

**Исправление в `api/routes/devices.py` строки 94–100:**
```python
# БЫЛО:
if body.auto_pair:
    try:
        await operator.device_manager.pair_device(device.id)
    except Exception as exc:
        _LOGGER.warning(
            "Auto-pair failed for device %s: %s", device.id, exc
        )

# СТАЛО:
# auto_pair передаётся в register_device как параметр — BLE pairing
# выполняется внутри DeviceManager без дублирования
```

Поскольку новая сигнатура `register_device` принимает `auto_pair: bool = False` и выполняет pairing внутри, код в `devices.py` строк 94–100 нужно убрать — логика уже встроена в `register_device`.

### Критерии готовности
- `POST /api/devices/register` с телом `{"name": "...", "mac_address": "AA:BB:CC:DD:EE:FF", "model": "S3"}` возвращает HTTP 201 без `TypeError`
- `DeviceManager.register_device()` не принимает `BLEDevice` как обязательный аргумент
- `discover_and_register_all` по-прежнему работает корректно
- Тест `test_register_device_by_kwargs` проходит

---

## Task-3: Исправить delete_device (добавить await)

### Файлы
- `api/routes/devices.py` — строка 213

### Конкретное изменение

```python
# БЫЛО (строка 213):
device_manager.delete_device(device_id)

# СТАЛО:
await device_manager.delete_device(device_id)
```

Это однострочное изменение. `DeviceManager.delete_device()` объявлен как `async def` (строка 118 `device_manager.py`) — вызывает `unpair_device` внутри. Без `await` coroutine создаётся, но не выполняется. Python не выдаёт ошибку, но действие не происходит.

### Критерии готовности
- `DELETE /api/devices/{id}` устанавливает `is_active=False` в SQLite
- `GET /api/devices` не возвращает удалённое устройство
- Ruff/mypy не выдают предупреждений о неиспользованном coroutine

---

## Task-4: Исправить except Exception в operator.py

### Файлы
- `tion_btle/operator.py` — несколько мест

### Конкретные изменения

**Строки 531–532 (критическое нарушение):**
```python
# БЫЛО:
try:
    await self._devices[device_id].disconnect()
except Exception:
    pass

# СТАЛО:
try:
    await self._devices[device_id].disconnect()
except Exception:
    _LOGGER.warning(
        "Failed to disconnect device %s before reconnect",
        device_id,
        exc_info=True,
    )
```

**Строка 202 (f-string logging без exc_info):**
```python
# БЫЛО:
except Exception as e:
    _LOGGER.error(f"Polling error: {str(e)}")

# СТАЛО:
except Exception as e:
    _LOGGER.error("Polling error: %s", e, exc_info=True)
```

**Строка 452 (execute_scenario):**
```python
# БЫЛО:
except Exception as e:
    _LOGGER.error(f"Failed to execute scenario {scenario_id}: {str(e)}")

# СТАЛО:
except Exception as e:
    _LOGGER.error(
        "Failed to execute scenario %s: %s", scenario_id, e, exc_info=True
    )
```

**Строка 474 (_run_scenarios_loop):**
```python
# БЫЛО:
except Exception as e:
    _LOGGER.error(f"Scenario execution error: {str(e)}")

# СТАЛО:
except Exception as e:
    _LOGGER.error("Scenario execution error: %s", e, exc_info=True)
```

**Строка 557 (shutdown):**
```python
# БЫЛО:
except Exception as e:
    _LOGGER.error(f"Error disconnecting device {device_id}: {str(e)}")

# СТАЛО:
except Exception as e:
    _LOGGER.error(
        "Error disconnecting device %s: %s", device_id, e, exc_info=True
    )
```

**Дополнительно — f-string logging в operator.py (не нарушение CLAUDE.md, но нарушение best practice):**
- Строки 85, 89, 94–96, 411–412, 432, 447–451, 453–454, 475: заменить `f"..."` на `"...", variable` формат
- Это отдельная задача, выходящая за рамки Фазы 0/1, но желательная

### Критерии готовности
- `tion_btle/operator.py:531` — `except Exception: pass` заменён на logging
- `ruff check tion_btle/operator.py` не выдаёт нарушений правила B110 (try-except-pass)
- Все `except Exception` в `operator.py` содержат явное логирование

---

## Task-5: Добавить domain tests в testpaths

### Файлы
- `pyproject.toml` — строка 92

### Конкретное изменение

```toml
# БЫЛО:
testpaths = ["tests"]

# СТАЛО:
testpaths = ["tests", "tion_btle/domain/device_manager/tests"]
```

### Критерии готовности
- `pytest --collect-only` показывает `tion_btle/domain/device_manager/tests/test_device_manager.py` и `test_sqlite_storage.py` без явного указания пути
- `pytest` без аргументов запускает domain tests
- Domain tests попадают в coverage report

---

## Task-6: Заполнить tests/unit/test_device_manager.py

### Файлы
- `tests/unit/test_device_manager.py` — написать тесты

### Контекст

Файл содержит 1 строку (предположительно пустой комментарий или `pass`). Domain-тесты в `tion_btle/domain/device_manager/tests/test_device_manager.py` уже существуют и тестируют `DeviceManager` напрямую.

`tests/unit/test_device_manager.py` должен тестировать `DeviceManager` через API-слой или дополнять domain-тесты интеграционными сценариями.

### Минимальный набор тестов (10 тест-кейсов)

```python
"""Unit tests for DeviceManager integration with API layer."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from tion_btle.domain.device_manager.device_manager import DeviceManager
from tion_btle.domain.device_manager.models import DeviceInfo


@pytest.fixture
def mock_storage():
    storage = MagicMock()
    storage.create_device = MagicMock()
    storage.get_device = MagicMock(return_value=None)
    storage.get_devices = MagicMock(return_value=[])
    storage.update_device = MagicMock(return_value=True)
    storage.delete_device = MagicMock(return_value=True)
    return storage


@pytest.fixture
def device_manager(mock_storage):
    return DeviceManager(mock_storage, mock_storage)


@pytest.mark.asyncio
async def test_register_device_by_kwargs(device_manager):
    """register_device accepts name/mac_address/model kwargs without BLEDevice."""
    result = await device_manager.register_device(
        name="Living Room",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
    )
    assert result.name == "Living Room"
    assert result.mac_address == "AA:BB:CC:DD:EE:FF"
    assert result.model == "S3"


@pytest.mark.asyncio
async def test_register_device_with_room(device_manager):
    result = await device_manager.register_device(
        name="Bedroom",
        mac_address="11:22:33:44:55:66",
        model="Lite",
        room="Bedroom",
    )
    assert result.room == "Bedroom"


@pytest.mark.asyncio
async def test_register_device_stores_in_storage(device_manager, mock_storage):
    await device_manager.register_device(
        name="Test", mac_address="AA:BB:CC:DD:EE:FF", model="S4"
    )
    mock_storage.create_device.assert_called_once()


@pytest.mark.asyncio
async def test_register_device_unknown_model_defaults_to_base_tion(device_manager):
    result = await device_manager.register_device(
        name="Unknown", mac_address="FF:FF:FF:FF:FF:FF", model="Unknown"
    )
    assert result is not None


@pytest.mark.asyncio
async def test_delete_device_calls_storage(device_manager, mock_storage):
    mock_storage.get_device.return_value = DeviceInfo(
        id="test-id", name="Test", type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF", model="S3", is_paired=False
    )
    result = await device_manager.delete_device("test-id")
    assert result is True
    mock_storage.delete_device.assert_called_once_with("test-id")


def test_get_devices_returns_list(device_manager, mock_storage):
    mock_storage.get_devices.return_value = [
        DeviceInfo(id="id1", name="Dev1", type="TionS3",
                   mac_address="AA:BB:CC:DD:EE:FF", model="S3")
    ]
    devices = device_manager.get_devices()
    assert len(devices) == 1
    assert devices[0].name == "Dev1"


def test_get_device_returns_none_for_unknown(device_manager, mock_storage):
    mock_storage.get_device.return_value = None
    result = device_manager.get_device("non-existent")
    assert result is None


def test_get_device_capabilities_s3(device_manager, mock_storage):
    mock_storage.get_device.return_value = DeviceInfo(
        id="id1", name="Dev1", type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF", model="S3"
    )
    caps = device_manager.get_device_capabilities("id1")
    assert caps["heater_control"] is True
    assert caps["light_control"] is False


def test_get_device_capabilities_lite(device_manager, mock_storage):
    mock_storage.get_device.return_value = DeviceInfo(
        id="id2", name="Dev2", type="TionLite",
        mac_address="11:22:33:44:55:66", model="Lite"
    )
    caps = device_manager.get_device_capabilities("id2")
    assert caps["light_control"] is True
    assert caps["heater_control"] is False


def test_get_connected_devices_filters_active_and_paired(device_manager, mock_storage):
    mock_storage.get_devices.return_value = [
        DeviceInfo(id="id1", name="Dev1", type="TionS3",
                   mac_address="AA:BB:CC:DD:EE:FF", model="S3",
                   is_active=True, is_paired=True),
        DeviceInfo(id="id2", name="Dev2", type="TionS3",
                   mac_address="11:22:33:44:55:66", model="S3",
                   is_active=True, is_paired=False),
    ]
    connected = device_manager.get_connected_devices()
    assert "id1" in connected
    assert "id2" not in connected
```

### Критерии готовности
- `tests/unit/test_device_manager.py` содержит минимум 10 тестов
- Все тесты проходят без реального BLE-оборудования
- Покрытие `DeviceManager` увеличивается

---

## Task-7: Удалить yandex_api_integration.py

### Файлы
- `yandex_api_integration.py` — удалить
- `tests/unit/test_yandex_api_integration.py` — удалить
- `pyproject.toml` — удалить секцию `[[tool.mypy.overrides]]` для `yandex_api_integration`

### Конкретные изменения

**pyproject.toml строки 85–87:** удалить секцию:
```toml
[[tool.mypy.overrides]]
module = ["yandex_api_integration"]
ignore_errors = true
```

**Удаление файлов:**
```bash
git rm yandex_api_integration.py
git rm tests/unit/test_yandex_api_integration.py
```

### Что нужно проверить перед удалением

Убедиться, что нет импортов `yandex_api_integration` в других файлах:
```bash
grep -r "yandex_api_integration" . --include="*.py"
```

Убедиться, что ни один файл не импортирует функции из этого модуля напрямую.

### Что НЕ теряется при удалении

- Функциональность Яндекс Smart Home полностью реализована в `api/routes/yandex.py`
- OAuth validation реализована в `api/middleware/auth.py`
- `MODE_MAPPING` при необходимости можно перенести в `api/routes/yandex.py` или `api/schemas.py`

### Критерии готовности
- `yandex_api_integration.py` отсутствует в репозитории
- `tests/unit/test_yandex_api_integration.py` отсутствует
- `pyproject.toml` не содержит override для `yandex_api_integration`
- `pytest` проходит без ошибок после удаления
- `mypy` не скрывает ошибки через override

---

## Зависимости между задачами

```
Task-1 (CI)           — независима, выполнять первой
Task-7 (удалить Flask) — независима, можно параллельно с Task-1
Task-5 (testpaths)    — независима, можно параллельно с Task-1 и Task-7

Task-2 (register_device сигнатура) — зависит от: Task-3 (оба в devices.py)
Task-3 (await delete)              — зависит от: Task-2 (оба в devices.py)

Task-4 (except Exception) — независима
Task-6 (тесты)            — зависит от Task-2 (тесты должны использовать новую сигнатуру)
```

**Параллельные блоки:**
- Блок A (независимые): Task-1, Task-4, Task-5, Task-7
- Блок B (последовательные): Task-2 → Task-3
- Блок C (после B): Task-6

**Рекомендуемый порядок:**
1. Task-1 (CI) — первым, чтобы не сломать CI для остальных PR
2. Task-7 (Flask удалить) — вторым, убирает мёртвый код
3. Task-4 (except Exception) — третьим, изолированное изменение
4. Task-5 (testpaths) — четвёртым, конфигурационное изменение
5. Task-2 (register_device) — пятым, ядро TION-001
6. Task-3 (await delete) — шестым, вместе с Task-2 (один PR)
7. Task-6 (тесты) — последним, после Task-2

---

## Файлы затронутые изменениями

| Файл | Tasks | Тип изменения |
|---|---|---|
| `.github/workflows/tests.yml` | Task-1 | modify |
| `tion_btle/domain/device_manager/device_manager.py` | Task-2 | modify |
| `api/routes/devices.py` | Task-2, Task-3 | modify |
| `tion_btle/operator.py` | Task-4 | modify |
| `pyproject.toml` | Task-5, Task-7 | modify |
| `tests/unit/test_device_manager.py` | Task-6 | write |
| `yandex_api_integration.py` | Task-7 | delete |
| `tests/unit/test_yandex_api_integration.py` | Task-7 | delete |
| `tion_btle/domain/device_manager/models.py` | Task-2 | modify (если нет поля room) |

---

## Риски и ограничения

### Риск 1: Двойная инициализация DeviceManager
`api/app.py` создаёт `DeviceManager`, а `Operator.__init__` создаёт свой. Это значит два независимых экземпляра с разными `SQLiteDeviceStorage`. Запись через `app.state.device_manager` не видна `operator.device_manager`. Это архитектурная проблема, выходящая за рамки данного плана (Фаза 0/1).

**Временное решение:** убедиться, что `api/routes/devices.py` всегда использует `_get_device_manager(request)` (из `app.state.device_manager`), а не `operator.device_manager`. Это корректно в текущем коде после удаления строк 94–100 из `register_device` endpoint.

### Риск 2: models.py поле room
`DeviceInfo` в `tion_btle/domain/device_manager/models.py` может не содержать поле `room`. Перед выполнением Task-2 нужно проверить модель и добавить `room: str | None = None` если отсутствует.

### Риск 3: Domain tests могут не проходить
После добавления domain tests в `testpaths` (Task-5) может оказаться, что часть тестов в `tion_btle/domain/device_manager/tests/` использует устаревшую сигнатуру `register_device(device: BLEDevice)`. Эти тесты нужно обновить после Task-2.

---

## Статус
Ожидает утверждения
