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
| 2. Storage + core (event/command bus) + REST/WS + auth | ✅ master; смоук на фейках и железе через REST |
| 3. UI MVP (дашборд, устройства, мастер сопряжения, PWA) | ✅ master; ⏳ ручной чек-лист на телефоне |
| 4. Яндекс + внешний доступ = **MVP** | ✅ код в master; ⏳ VPS/линковка/голос — `docs/yandex-setup.md` |
| 5–8. Автоматизация, датчики, интенты, полировка | ⏳ следующая — Фаза 5 |

**Железо:** все три бризера сопряжены с ноутбуком (bonding, разово на хост):
`EC:82:9F:A4:90:14` ближний · `D0:60:0E:F7:EA:D4` средний · `EB:B5:4E:13:31:B5`
дальний. У D0 и EB ресурс фильтра на нуле (владельцу — заменить/сбросить).
Хвост смоука (не блокирует): строки ⏳ в таблице runbook + бонд после
power-cycle. На боевом RPi сопряжение нужно будет повторить (бонд per-host).

## План дальнейшей разработки

**Хвосты в руках владельца (не блокируют разработку):**

- Фаза 3: чек-лист PWA на телефоне из LAN (установка, логин, управление тремя
  бризерами, мастер на реальном бризере). `make build-ui && make dev`.
- Фаза 4 = **гейт MVP**: VPS (frps+nginx+TLS по пути A/B), frpc на хосте,
  регистрация приватного навыка, линковка, голосовой чек-лист — пошагово в
  `docs/yandex-setup.md`. Код и contract-тесты готовы.

### Фаза 5 — автоматизация + телеметрия (ветка `feature/phase-5-automation`)

Объём (план §9, §14):

- `automation/clock.py` — инжектируемое время (time-travel тесты).
- `automation/scenarios.py` — именованные списки действий (device|group →
  дельта); исполнение через command bus (source=scenario).
- `automation/scheduler.py` — один task, `next = min(croniter)` по включённым
  расписаниям, TZ из settings, пробуждение по CRUD-событию; рестарт: опоздание
  < 5 мин — выполнить, иначе пропустить с логом.
- REST/UI: CRUD сценариев и расписаний (конструктор «время + дни»), плитки
  сценариев и «Все выкл» на дашборде, бейдж hold уже есть.
- Телеметрия: `GET /api/telemetry` (raw/агрегаты), графики recharts
  (CO₂ появится в Фазе 6, пока температуры/скорость).
- Тесты: time-travel (DST, рестарт, missed-fire), e2e на fake
  «23:00 → все на скорость 1», hold блокирует расписание.

Сложившийся API: `/api/auth/*` (+ status), `/api/devices` CRUD + command +
hold, `/api/rooms`, `/api/groups`, `/api/commands`, `/api/pairing/*`,
`/api/system/*`, WS `/api/ws`; `/oauth/authorize|token` (линковка),
`/v1.0/*` (Bearer нашего OAuth; query из кэша; action → шина с дедупом по
X-Request-Id, оптимистичный DONE, DEVICE_UNREACHABLE > 120 с офлайна);
callbacks state/discovery — `yandex_callbacks_started` в логе при
заполненных EB_YANDEX_SKILL_ID/CALLBACK_TOKEN.

### Фазы 5–8
Автоматизация (сценарии/расписания/триггеры), датчики CO₂ (MagicAir cloud →
свой контроль, вывод MagicAir — ADR-0005), интенты, полировка + покрытие ≥80 %.

## Как возобновить

```bash
cd server && uv sync && cd ../ui && npm install   # зависимости
make test && make lint        # 99 pytest + 10 vitest; ruff/mypy strict/oxlint/tsc
EB_FAKE_DEVICES=3 make dev    # сервер :8000 (+ PWA из ui/dist, если собран)
make dev-ui                   # vite :5173 с прокси на :8000 (горячая замена)
uv run breezy state EC:82:9F:A4:90:14   # CLI по протоколу (бонд уже есть)
```

Первый вход: `POST /api/auth/setup {setup_token, username, password}` — токен
печатается в лог при старте без пользователей; дальше login-cookie или
api-токен (`POST /api/tokens`) с `Authorization: Bearer`.

Локальные ветки `feature/rewrite-phase-0`, `feature/phase-1-ble`,
`feature/phase-2-core-api`, `feature/phase-3-ui` влиты в master — можно
удалить; `feature-search-and-register-devices` — легаси, тоже можно удалить.
