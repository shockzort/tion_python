# Easy Breezy — статус проекта

Живой документ состояния. Обновляется в конце каждой сессии/фазы.
Последнее обновление: **2026-07-11**, ветка `master`.

План целиком: `/home/shockzor/.claude/plans/rosy-tickling-moonbeam.md`.
Требования: `context/requirements.md`. Протокол: `docs/protocol/tion-s4-ble.md`.

## Общий прогресс

| Фаза | Статус |
|---|---|
| 0. Reset, спецификация, требования, каркас, CI | ✅ готово, на master |
| 1. BLE-библиотека (кодек S4, транспорт, драйвер, супервизор) + CLI | ✅ код готов, на master; ⚠️ живой смоук заблокирован железом (см. ниже) |
| 2. Storage + core (event/command bus) + REST/WS + auth | ⏳ следующая |
| 3. UI MVP (дашборд, сопряжение) | — |
| 4. Яндекс + внешний доступ (frp/nginx/TLS) = **MVP** | — |
| 5–8. Автоматизация, датчики, интенты, полировка | — |

## Сделано (Фазы 0–1)

**Каркас (Фаза 0):** монорепо `server/` (Python 3.12, uv, FastAPI, `/api/system/health`,
structlog JSON) + `ui/` (Vite/React 19/TS/Tailwind v4/PWA) + `deploy/` (systemd, docker,
nginx, frp) + CI (GitHub Actions). `make lint` / `make test` — зелёные.

**BLE-библиотека (Фаза 1)** в `server/src/easy_breezy/ble/`:
- `protocol/framing.py` — кадрирование Lite-семейства, `Reassembler`, split, CRC-16/CCITT-FALSE
  (генерация + мягкая валидация). `protocol/s4.py` — `S4State`, decode/encode, инжектируемый nonce.
- `transport.py` — `BleTransport` + `BleakTransport` (find_device_by_address → connect по объекту,
  стадии connect/notify разнесены, таймауты). `fake.py` — `FakeS4Device`/`FakeTransport` с
  инъекцией сбоев (тесты и будущий dev-режим).
- `driver.py` — `S4Driver`: слушатель нотификаций, get/set с подтверждением кадром состояния
  и fallback-запросом, per-device сериализация.
- `supervisor.py` — `DeviceSupervisor`: реконнект с backoff 1→60 с + джиттер, опрос 30 с,
  деградация после 3 промахов, scan-gate. Время инжектируется (time-travel тесты).
- `scanner.py` — скан с фильтром имени. `cli.py` — `breezy scan/pair/unpair/state/set/monitor`.
- Тесты: 46 (golden-векторы байт-в-байт, framing, драйвер на fake, супервизор). mypy strict.

**Ключевые файлы для ориентации:** `docs/protocol/tion-s4-ble.md` (спецификация + §5 полевые
наблюдения + раздел диагностики BLE в `docs/runbook.md`), `server/tests/golden/*.json`.

## Ключевые находки сессии

### Подтверждено на живом железе (3× Tion S4 в квартире)
- Имя в эфире: **`Breezer 4S`** (без «Tion»), адрес **random-static**, реклама **ADV_IND
  (connectable)**, manufacturer data company `0xffff` = `<mac> 03 80 00 00 00`.
- **Сервисный UUID `98f00001-3788-83ea-453e-f52244709ddb` подтверждён** (в рекламе). Write/notify
  UUID (`…0002`/`…0003`) — пока не подтверждены (нужна GATT-таблица через соединение).
- **Сопряжение не требуется** — бризер пускает подключение без бонда (как аппаратные пульты).
- Протокольный кодек не проверен на живом обмене (не дошли из-за блокера ниже), но golden-векторы
  байт-в-байт корректны.

### Блокер живого смоука: HCI 0x3E на адаптере ноутбука
- Симптом: скан находит все 3 бризера, но **connect падает с HCI `0x3E` "Connection Failed to be
  Established"** — `Connection Complete: Success` → сразу `Disconnect reason 0x3E`. Детерминированно,
  ~0/30, на обоих проверенных бризерах (EC:82:9F:A4:90:14, D0:60:0E:F7:EA:D4).
- Диагноз снят через `btmon` (HCI-захват был в `/tmp/eb.snoop`).
- **Исключено:** наш код (три способа подключения дали то же), бризеры (оба, connectable,
  power-cycle не помог), устаревший кэш BlueZ, активный скан GNOME-настроек (реальная помеха,
  устранена), Realtek, сброс контроллера.
- Адаптер — **Intel AX211** (combo WiFi+BT, одна антенна). Ведущая версия: **WiFi/BT coexistence**
  сбивает тайминг установления BLE-соединения при активном WiFi-трафике (WiFi на 5 ГГц, но combo
  делит радио и между диапазонами).
- Подробности: память `ble-adapter-0x3e-issue`, раздел диагностики в `docs/runbook.md`.

## План дальнейших действий

### Разблокировать железо (параллельно, вне кода) — выбор владельца
1. **USB BT-донгл** (Intel/CSR8510, ~500 ₽) — основная рекомендация, она же для боевого RPi.
2. Тест с выключенным WiFi (нужна альтернативная связь — ethernet/хотспот) — подтвердит coexistence.
3. Проверка с другой машины/RPi.
> Как только адаптер рабочий — прогнать hardware-чек-лист `docs/runbook.md` (скан→пейринг→state
> сверить с приложением Tion→скорости→**нагрев: инверсия бита**→реконнект→латентность) и внести
> результаты в спецификацию (статусы [u]/[?] → [✓]).

### Фаза 2 — можно начинать без железа (dev-режим на FakeS4)
Ветка `feature/phase-2-core-api` от master. Объём (план §5, §8):
- `storage/` — SQLAlchemy 2.0 async + aiosqlite + Alembic; таблицы devices/groups/commands/
  scenarios/schedules/triggers/sensors/telemetry/users/sessions/oauth/settings (модель — план §5).
- `core/events.py` — event bus (in-process async pub/sub).
- `core/registry.py`, `core/state.py` — реестр устройств + кэш последнего состояния.
- `core/bus.py` — command bus: идемпотентность по ключу, per-device очереди, приоритеты, журнал,
  дедуп ретраев (план §8). `core/holds.py` — manual-override окна.
- `core/telemetry.py` — рекордер + downsampler.
- `api/rest/*` (devices, groups, commands, system) + `api/ws.py` (WS-хаб) + `api/deps.py` (auth).
- Авторизация: локальный админ (argon2id), сессии-cookie, api-токены.
- **dev-режим `EB_FAKE_DEVICES=3`** — поднять 3 фейковых бризера на `FakeS4Device`, чтобы весь
  сервис и UI Фазы 3 разрабатывались без BLE-железа.
- Тесты: дедуп/сериализация/таймауты/hold, httpx ASGI «POST command → WS event» на fake,
  alembic upgrade.

## Как возобновить

```bash
cd server && uv sync          # зависимости
make test                     # 46 тестов зелёные
make lint                     # ruff+black+isort+mypy strict, oxlint+tsc
uv run breezy scan            # найдёт бризеры (подключение упрётся в 0x3E до смены адаптера)
make dev                      # сервер :8000, /api/system/health
```

Локальные ветки `feature/rewrite-phase-0`, `feature/phase-1-ble` уже влиты в master — можно
удалить. Старая `feature-search-and-register-devices` — легаси, тоже можно удалить.
