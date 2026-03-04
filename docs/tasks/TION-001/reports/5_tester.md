# Tester Report — TION-001

Date: 2026-03-05
Branch: feature-search-and-register-devices
Agent: tester (e2e-test-writer)

---

## Тестовые файлы

- `/home/shockzor/work/repos/tion_python/tests/unit/test_api_devices.py` — **новый файл**, 17 тестов

---

## AC → тест маппинг

| AC | Тест | Статус |
|---|---|---|
| AC-01 (CI testpaths) | `test_pyproject_testpaths_includes_domain_tests` | OK |
| AC-02 (register_device — success) | `test_register_device_success` | OK |
| AC-02 (register_device — с room) | `test_register_device_with_room` | OK |
| AC-02 (register_device — 422 при missing fields) | `test_register_device_missing_fields` | OK |
| AC-02 (register_device — 500 при exception) | `test_register_device_manager_raises_returns_500` | OK |
| AC-03 (delete_device — await вызов) | `test_delete_device_success` | OK |
| AC-03 (delete_device — async верификация) | `test_delete_device_is_async` | OK |
| AC-03 (delete_device — 404 не найдено) | `test_delete_device_not_found` | OK |
| AC-04 (except Exception: pass устранён) | `test_operator_reconnect_device_logs_exception_not_pass` | OK |
| AC-04 (exc_info=True в exception handlers) | `test_operator_exception_handlers_use_exc_info` | OK |
| AC-05 (domain tests в testpaths) | `test_pyproject_testpaths_includes_domain_tests` | OK |
| AC-12 (discover — пустой список) | `test_discover_devices_returns_empty_list` | OK |
| AC-12 (discover — с BLE mock) | `test_discover_devices_with_ble_mock` | OK |
| AC-12 (discover — 500 при BLE exception) | `test_discover_devices_ble_exception_returns_500` | OK |
| (GET /api/devices) | `test_get_devices_list` | OK |
| (GET /api/devices — пустой список) | `test_get_devices_empty_list` | OK |
| (GET /api/devices/{id}) | `test_get_device_by_id` | OK |
| (GET /api/devices/{id} — 404) | `test_get_device_by_id_not_found` | OK |

---

## Результат запуска

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- .venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/shockzor/work/repos/tion_python
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, mock-3.15.1, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False

collected 17 items

tests/unit/test_api_devices.py::test_register_device_success PASSED      [  5%]
tests/unit/test_api_devices.py::test_register_device_with_room PASSED    [ 11%]
tests/unit/test_api_devices.py::test_register_device_missing_fields PASSED [ 17%]
tests/unit/test_api_devices.py::test_register_device_manager_raises_returns_500 PASSED [ 23%]
tests/unit/test_api_devices.py::test_delete_device_success PASSED        [ 29%]
tests/unit/test_api_devices.py::test_delete_device_not_found PASSED      [ 35%]
tests/unit/test_api_devices.py::test_delete_device_is_async PASSED       [ 41%]
tests/unit/test_api_devices.py::test_get_devices_list PASSED             [ 47%]
tests/unit/test_api_devices.py::test_get_devices_empty_list PASSED       [ 52%]
tests/unit/test_api_devices.py::test_get_device_by_id PASSED             [ 58%]
tests/unit/test_api_devices.py::test_get_device_by_id_not_found PASSED   [ 64%]
tests/unit/test_api_devices.py::test_discover_devices_returns_empty_list PASSED [ 70%]
tests/unit/test_api_devices.py::test_discover_devices_with_ble_mock PASSED [ 76%]
tests/unit/test_api_devices.py::test_discover_devices_ble_exception_returns_500 PASSED [ 82%]
tests/unit/test_api_devices.py::test_pyproject_testpaths_includes_domain_tests PASSED [ 88%]
tests/unit/test_api_devices.py::test_operator_reconnect_device_logs_exception_not_pass PASSED [ 94%]
tests/unit/test_api_devices.py::test_operator_exception_handlers_use_exc_info PASSED [100%]

============================== 17 passed in 0.22s ==============================
```

---

## Команда запуска

```bash
uv run pytest tests/unit/test_api_devices.py -v --tb=short
```

---

## Техническое описание

### Подход к тестированию

Тесты используют `httpx.AsyncClient` с `ASGITransport` для отправки реальных HTTP-запросов в FastAPI приложение без запуска реального сервера.

Для изоляции от BLE, SQLite и Yandex OAuth:
- `DeviceManager` полностью заменён на `MagicMock` с `AsyncMock` методами
- `Operator` заменён на `MagicMock`
- Auth dependency `get_current_user` переопределён через `app.dependency_overrides` — возвращает фиксированный `"test_user_id"`
- FastAPI app создаётся через минимальную фабрику без lifespan (без реального BLE-подключения)

### Паттерны тестирования

**AC-02 (register_device):**
- Проверяет HTTP 200 при корректном теле запроса
- Проверяет точную сигнатуру вызова `register_device(name=..., mac_address=..., model=..., room=...)`
- Проверяет HTTP 422 при отсутствии обязательных полей (Pydantic validation)
- Проверяет HTTP 500 при внутренней ошибке device_manager

**AC-03 (delete_device):**
- Использует `AsyncMock` для `delete_device` — `assert_awaited_once_with` подтверждает, что coroutine был awaited
- Если бы endpoint не использовал `await`, `AsyncMock.await_count` был бы 0

**AC-04 (except Exception):**
- Парсит исходный код `operator.py` через regex
- Проверяет отсутствие паттерна `except Exception:` + `pass` (без логирования)
- Проверяет наличие `exc_info=True` в теле `reconnect_device` функции

**AC-05 (testpaths):**
- Читает `pyproject.toml` через `tomllib` (stdlib Python 3.11+)
- Проверяет что `["tool"]["pytest"]["ini_options"]["testpaths"]` содержит оба пути

---

## Статус

Все 17 тестов проходят.

### Замечания

1. **operator.py содержит f-string в _LOGGER.error() на строках 415, 432, 436, 527** — эти вызовы не относятся к exception handlers (это валидационные проверки без `except`). AC-04 требует только исправления `except Exception: pass` — что выполнено. Тест проверяет только exception handler-ы, но не все вызовы `_LOGGER.error`.

2. **4 теста в `tion_btle/domain/device_manager/tests/test_device_manager.py` падают** (`test_pair_device_*`) — это предсуществующая проблема, не связанная с данным PR (неправильный patch-путь для TionS3 в тестах без BLE). Эти тесты существовали до начала работы по TION-001.
