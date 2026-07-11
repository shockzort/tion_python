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
| 4. Яндекс + внешний доступ (frp/nginx/TLS) = **MVP** | ⏳ следующая |
| 5–8. Автоматизация, датчики, интенты, полировка | — |

**Железо:** все три бризера сопряжены с ноутбуком (bonding, разово на хост):
`EC:82:9F:A4:90:14` ближний · `D0:60:0E:F7:EA:D4` средний · `EB:B5:4E:13:31:B5`
дальний. У D0 и EB ресурс фильтра на нуле (владельцу — заменить/сбросить).
Хвост смоука (не блокирует): строки ⏳ в таблице runbook + бонд после
power-cycle. На боевом RPi сопряжение нужно будет повторить (бонд per-host).

## План дальнейшей разработки

**Хвост Фазы 3 (руки владельца, не блокирует):** на телефоне из LAN — установка
PWA (иконка, standalone), логин, управление тремя бризерами с дашборда, мастер
сопряжения на реальном бризере (кнопка ~5 с → скан → бонд), поведение при
обрыве WS. Запуск: `make build-ui && EB_FAKE_DEVICES=3 make dev` или боевой BLE.

### Фаза 4 — Яндекс + внешний доступ = MVP (ветка `feature/phase-4-yandex`)

Объём (план §6, §12–14):

- Решение TLS за 15 минут в консоли Диалогов: IP-сертификат Let's Encrypt
  (путь A, предпочтение владельца) vs поддомен DuckDNS (путь B) — план §6.
- OAuth-провайдер: `GET /oauth/authorize` (standalone HTML-логин, не SPA),
  `POST /oauth/token` (authorization_code + refresh_token); таблицы уже в схеме.
- `/v1.0/*`: HEAD ping, devices (маппинг §6: on_off, mode fan_speed one…six,
  thermostat heat/fan_only, range temperature 10–30, mute/backlight, property
  температура притока), query (только из state cache), action → command bus
  (дедуп по X-Request-Id), unlink. Bearer — только наш OAuth.
- Callbacks: state с дебаунсом 1 с и схлопыванием по устройству, discovery
  при изменении списка; ретраи с backoff.
- Деплой: frps/frpc + nginx + TLS на VPS, systemd-юниты на Pi (`deploy/`),
  `docs/yandex-setup.md`; регистрация приватного навыка, креды в `.env`.
- Contract-тесты на golden-JSON пар запрос/ответ; голосовой чек-лист §14
  (включи/скорость три/обогрев/22 градуса; обесточенный → «недоступно»);
  замер голос→действие < 3 с.

Сложившийся API: `/api/auth/*` (+ `GET /api/auth/status`), `/api/devices` CRUD
+ `POST …/command` (Idempotency-Key; 200 done или 202 pending + финал по WS) +
`DELETE …/hold`, `/api/rooms`, `/api/groups` (+ веерная команда),
`/api/commands`, `/api/pairing/scan|pair` (+ WS pairing.progress),
`/api/system/health|stats`, WS `/api/ws`. Сервер раздаёт `ui/dist` (SPA,
`EB_UI_DIST`); dev UI — vite на :5173 с прокси.

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
