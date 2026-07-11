# Easy Breezy — статус проекта

Живой документ: точки входа в контекст + план дальнейшей разработки.
Полевые факты живут в спеке, решения — в ADR, процедуры — в runbook.
Последнее обновление: **2026-07-11**, ветка `master`.

## Точки входа в контекст

| Что | Где |
|---|---|
| Утверждённый план (9 фаз, архитектура, модель данных, маппинг Яндекса) | `~/.claude/plans/rosy-tickling-moonbeam.md` |
| Требования | `context/requirements.md` |
| Спецификация BLE-протокола + полевые факты (§5) | `docs/protocol/tion-s4-ble.md` |
| Архитектурные решения (ADR 0001–0005) | `docs/adr/` |
| Runbook: смоук-чек-лист, диагностика BLE, пейринг | `docs/runbook.md` |
| Golden-векторы протокола (данные, руками не менять) | `server/tests/golden/` |
| Конвенции разработки | `CLAUDE.md` |

## Прогресс

| Фаза | Статус |
|---|---|
| 0. Каркас, спецификация, требования, CI | ✅ master |
| 1. BLE-библиотека (кодек, транспорт, драйвер, супервизор) + CLI | ✅ master; живой смоук пройден |
| 2. Storage + core (event/command bus) + REST/WS + auth | ⏳ следующая |
| 3. UI MVP (дашборд, сопряжение) | — |
| 4. Яндекс + внешний доступ (frp/nginx/TLS) = **MVP** | — |
| 5–8. Автоматизация, датчики, интенты, полировка | — |

**Железо:** все три бризера сопряжены с ноутбуком (bonding, разово на хост):
`EC:82:9F:A4:90:14` ближний · `D0:60:0E:F7:EA:D4` средний · `EB:B5:4E:13:31:B5`
дальний. У D0 и EB ресурс фильтра на нуле (владельцу — заменить/сбросить).
Хвост смоука (не блокирует): строки ⏳ в таблице runbook + бонд после
power-cycle. На боевом RPi сопряжение нужно будет повторить (бонд per-host).

## План дальнейшей разработки

### Фаза 2 — storage + core + API (ветка `feature/phase-2-core-api`, железо не нужно)

Объём (план §5, §8):

- `storage/` — SQLAlchemy 2.0 async + aiosqlite + Alembic; таблицы devices/groups/
  commands/scenarios/schedules/triggers/sensors/telemetry/users/sessions/oauth/settings.
- `core/events.py` — event bus (in-process async pub/sub).
- `core/registry.py`, `core/state.py` — реестр устройств + кэш последнего состояния.
- `core/bus.py` — command bus: идемпотентность по ключу, per-device очереди,
  приоритеты, журнал, дедуп ретраев; сверка «применилось ли» после записи (ADR-0004).
- `core/holds.py` — manual-override окна (ADR-0005).
- `core/telemetry.py` — рекордер + downsampler.
- `api/rest/*` (devices, groups, commands, system) + `api/ws.py` + `api/deps.py`.
- Авторизация: локальный админ (argon2id), сессии-cookie, api-токены.
- Dev-режим `EB_FAKE_DEVICES=3` на `FakeS4Device` — сервис и UI без железа.
- Тесты: дедуп/сериализация/таймауты/hold, httpx ASGI «POST command → WS event»,
  alembic upgrade.

### Фаза 3 — UI MVP
Дашборд состояния, управление (скорость/нагрев/режим), мастер сопряжения.

### Фаза 4 — Яндекс + внешний доступ = MVP
OAuth-заглушка + устройства/капабилити Умного дома, frp + nginx + TLS на VPS.

### Фазы 5–8
Автоматизация (сценарии/расписания/триггеры), датчики CO₂ (MagicAir cloud →
свой контроль, вывод MagicAir — ADR-0005), интенты, полировка + покрытие ≥80 %.

## Как возобновить

```bash
cd server && uv sync          # зависимости
make test && make lint        # 46 тестов, ruff/black/isort/mypy strict, oxlint/tsc
uv run breezy scan            # бризеры в эфире (занятый другим централом не виден)
uv run breezy state EC:82:9F:A4:90:14   # чтение по протоколу (бонд уже есть)
make dev                      # сервер :8000, /api/system/health
```

Локальные ветки `feature/rewrite-phase-0`, `feature/phase-1-ble` влиты в master —
можно удалить; `feature-search-and-register-devices` — легаси, тоже можно удалить.
