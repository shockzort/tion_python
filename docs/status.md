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
| 3. UI MVP (дашборд, сопряжение) | ⏳ следующая |
| 4. Яндекс + внешний доступ (frp/nginx/TLS) = **MVP** | — |
| 5–8. Автоматизация, датчики, интенты, полировка | — |

**Железо:** все три бризера сопряжены с ноутбуком (bonding, разово на хост):
`EC:82:9F:A4:90:14` ближний · `D0:60:0E:F7:EA:D4` средний · `EB:B5:4E:13:31:B5`
дальний. У D0 и EB ресурс фильтра на нуле (владельцу — заменить/сбросить).
Хвост смоука (не блокирует): строки ⏳ в таблице runbook + бонд после
power-cycle. На боевом RPi сопряжение нужно будет повторить (бонд per-host).

## План дальнейшей разработки

### Фаза 3 — UI MVP (ветка `feature/phase-3-ui`, разработка на `EB_FAKE_DEVICES=3`)

Объём (план §11, §14):

- Бэкенд-хвост для мастера сопряжения: REST скана (15 с, фильтр `Tion Breezer*`)
  и пейринга (`transport.pair()` уже самодостаточен, ADR-0003) + прогресс по WS.
- Логин/setup-экран (cookie уже в API), PWA-shell (vite-plugin-pwa, русский).
- Дашборд: карточки устройств — статус, слайдер скорости 1–6, нагрев + целевая
  температура, приток/рециркуляция, звук/подсветка, фильтр в днях, бейджи
  «нет связи»/«ручное управление до HH:MM» (+ кнопка снятия hold).
- Устройства: мастер сопряжения, переименование, комнаты, группы, удаление.
- WS-мост: `событие → setQueryData` (TanStack Query), optimistic updates
  с откатом по `command.finished(error)`.
- vitest (карточка, мастер) + tsc/oxlint в CI; ручной чек-лист на телефоне:
  установка PWA, управление тремя бризерами из LAN.

Сложившийся API (Фаза 2): `/api/auth/*` (setup по токену из лога, login-cookie,
api-токены), `/api/devices` CRUD + `POST …/command` (Idempotency-Key; 200 done
или 202 pending + финал по WS) + `DELETE …/hold`, `/api/rooms`, `/api/groups`
(+ веерная команда), `/api/commands` (журнал), `/api/system/health|stats`,
WS `/api/ws` (`{"topic","data"}`: device.state_changed / device.connection_changed
/ device.list_changed / command.finished).

### Фаза 4 — Яндекс + внешний доступ = MVP
OAuth-заглушка + устройства/капабилити Умного дома, frp + nginx + TLS на VPS.

### Фазы 5–8
Автоматизация (сценарии/расписания/триггеры), датчики CO₂ (MagicAir cloud →
свой контроль, вывод MagicAir — ADR-0005), интенты, полировка + покрытие ≥80 %.

## Как возобновить

```bash
cd server && uv sync          # зависимости
make test && make lint        # 95 тестов, ruff/black/isort/mypy strict, oxlint/tsc
EB_FAKE_DEVICES=3 make dev    # dev-режим на эмуляторах: :8000, setup-токен в логе
uv run breezy state EC:82:9F:A4:90:14   # CLI по протоколу (бонд уже есть)
```

Первый вход: `POST /api/auth/setup {setup_token, username, password}` — токен
печатается в лог при старте без пользователей; дальше login-cookie или
api-токен (`POST /api/tokens`) с `Authorization: Bearer`.

Локальные ветки `feature/rewrite-phase-0`, `feature/phase-1-ble`,
`feature/phase-2-core-api` влиты в master — можно удалить;
`feature-search-and-register-devices` — легаси, тоже можно удалить.
