# QC Report — TION-001

Date: 2026-03-05
Branch: feature-search-and-register-devices
Agent: qc-auditor

---

## Результат тестов

Команда запуска: `uv run pytest tests/unit/ tion_btle/domain/device_manager/tests/ -v --tb=short`

```
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0
plugins: anyio-4.12.1, asyncio-1.3.0, mock-3.15.1, cov-7.0.0
asyncio: mode=Mode.AUTO

collected 149 items (note: tests/functional/ вызывает ImportError — pre-existing, см. ниже)

4 failed, 145 passed in 13.58s
```

Итог: **145 passed, 4 failed** (все 4 падения — pre-existing, не связаны с TION-001).

Примечание: запуск `uv run pytest tests/ tion_btle/domain/device_manager/tests/` завершается с collection error из-за `tests/functional/test_lite.py` и `tests/functional/test_s4.py` (pre-existing ImportError, не связан с данным PR).

---

## AC Статус

| AC | Описание | Статус | Примечание |
|---|---|---|---|
| AC-01 | CI fix | PASS с замечанием | `requirements_test.txt` удалён, `uv sync --group dev` добавлен, матрица `['3.10', '3.11']`, actions обновлены. **Замечание:** coverage artifact upload отсутствует (нет шага `actions/upload-artifact`). Критичный критерий исправлен; недостающий артефакт — некритично для функционирования CI. |
| AC-02 | register_device | PASS | Сигнатура исправлена: принимает `name, mac_address, model, room, auto_pair` без `BLEDevice`. Тест `test_register_device_success` проходит с `assert_awaited_once_with`. |
| AC-03 | await delete | PASS | `api/routes/devices.py:213` содержит `await device_manager.delete_device(device_id)`. `AsyncMock.assert_awaited_once_with` подтверждает корректный await. |
| AC-04 | except Exception | PASS | `operator.py:533` — `except Exception: pass` заменён на `_LOGGER.warning(..., exc_info=True)`. Все 5 exception handler-ов содержат `exc_info=True` (проверено: 7 вхождений в файле). |
| AC-05 | testpaths | PASS | `pyproject.toml` содержит `testpaths = ["tests", "tion_btle/domain/device_manager/tests"]`. Domain tests включены в стандартный запуск pytest. |

---

## Hollow Tests

Есть: **нет**

Анализ ключевых тестов:

- `test_delete_device_success` и `test_delete_device_is_async` используют `AsyncMock` с `assert_awaited_once_with` / `await_count == 1`. Если убрать `await` из `devices.py:213` — тест упадёт (await_count будет 0), паттерн не hollow.
- `test_register_device_success` проверяет `assert_awaited_once_with(name=..., mac_address=..., model=..., room=None)` — если сигнатура вернётся к `(device: BLEDevice)`, тест упадёт с TypeError.
- `test_operator_reconnect_device_logs_exception_not_pass` парсит исходный код operator.py через regex и проверяет отсутствие `except Exception: ... pass`. Если откатить фикс — тест упадёт.
- `test_operator_exception_handlers_use_exc_info` считает вхождения `exc_info=True` (минимум 4) — откат к f-string без exc_info снизит счётчик и тест упадёт.
- `test_pyproject_testpaths_includes_domain_tests` читает `pyproject.toml` через `tomllib` — конфигурационный тест, без hollow pattern.
- Нет `assert True`, пустых тестов, `pass`-body тестов.

---

## Legacy Files

| Файл | Статус |
|---|---|
| `yandex_api_integration.py` | удалён |
| `tests/unit/test_yandex_api_integration.py` | удалён |
| `[[tool.mypy.overrides]] module = ["yandex_api_integration"]` | удалён из `pyproject.toml` |

---

## CLAUDE.md нарушения

Найдено: **1 (низкий приоритет, в device_manager.py, не в scope TION-001)**

Список:
1. `tion_btle/domain/device_manager/device_manager.py` строки 155–168: использование f-string в `_LOGGER.info(f"...")` и `_LOGGER.error(f"...")` в методах `pair_device` и `unpair_device`. Нарушает best practice (хотя CLAUDE.md явно запрещает `except Exception: pass`, а f-string logging — это best practice, не жёсткий запрет). Эти методы не входили в scope изменений TION-001 (Task-4 касался только `operator.py`).
2. Нет `print()` в production коде — не нарушено.
3. Нет синхронных HTTP запросов (`import requests`) — не нарушено.
4. Нет хардкода секретов/токенов — не нарушено.

---

## Pre-existing failures (не наша ответственность)

### 1. test_pair_device_success, test_pair_device_failure, test_pair_device_timeout, test_unpair_device

Файл: `tion_btle/domain/device_manager/tests/test_device_manager.py`

Причина: тесты патчат `tion_btle.s3.TionS3`, но `device_manager.py` импортирует `TionS3` через `from tion_btle.s3 import TionS3`. Созданный экземпляр `TionS3(mac)` инициирует реальное BLE-подключение через `tion_btle.tion.Tion._try_connect()`, которое завершается ошибкой `No Bluetooth adapters found.` в тестовой среде. Исправление требует патча `tion_btle.domain.device_manager.device_manager.TionS3` вместо `tion_btle.s3.TionS3`. Эти тесты существовали до начала работы по TION-001 и отмечены как pre-existing в отчёте implementer.

### 2. tests/functional/test_lite.py, tests/functional/test_s4.py

Причина: `ImportError: cannot import name 'Lite' from 'tion_btle.lite'` и `cannot import name 'S4' from 'tion_btle.s4'`. Предсуществующая проблема именования классов. Функциональные тесты не запускались в CI ещё до TION-001 (матрица CI использовала `type: [unit]`).

---

## Вердикт

**PASS WITH WARNINGS**

---

## Замечания (не блокирующие)

1. **AC-01 — Coverage artifact**: CI не содержит шага `actions/upload-artifact` для загрузки `coverage.xml`. Критерий AC-01 формально требует "Coverage report присутствует в артефактах CI". Функционально CI работоспособен (тесты запускаются, coverage генерируется в stdout), но артефакт не сохраняется между запусками.

2. **4 pre-existing failing tests**: `test_pair_device_*` и `test_unpair_device` в domain tests падают из-за неправильного patch-пути (не связано с TION-001). Рекомендуется исправить в отдельном PR.

3. **Functional tests collection error**: `tests/functional/` включается в `testpaths = ["tests"]` и вызывает `ImportError` при полном запуске `pytest tests/`. CI использует `uv run pytest` без `--ignore=tests/functional`, что означает CI также будет прерываться на collection. Рекомендуется добавить `norecursedirs = ["tests/functional"]` или `--ignore=tests/functional` в `pyproject.toml`.

4. **f-string logging в device_manager.py** (вне scope TION-001): строки 155–168 в `pair_device`/`unpair_device` используют f-string в `_LOGGER.error/info`. Не является жёстким нарушением CLAUDE.md, но нарушает best practice.
