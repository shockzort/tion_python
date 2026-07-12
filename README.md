# Easy Breezy

Локальный сервис управления бризерами **Tion S4** без облака Tion и базовой станции:
BLE-управление с Linux-сервера (Raspberry Pi), голос через **Умный дом Яндекса**,
единый веб-интерфейс (**PWA** — браузер, телефон, Android APK), автоматизация по
времени и датчикам CO₂, задел под локальную LLM.

> Приватный проект. Статус: **MVP работает** (фазы 0–7 и 9 в master) —
> BLE-управление, PWA, сценарии/расписания/триггеры, датчики CO₂
> (MagicAir cloud, MQTT), текстовые интенты, web push, бэкапы, APK.
> Текущий план — `docs/status.md`, история фаз — `docs/history.md`.

## Архитектура

Один asyncio-процесс (FastAPI + BLE + автоматизация) под systemd; React-PWA
раздаётся сервером; наружу — frp-туннель до VPS с nginx/TLS (для Яндекса).
Подсистемы общаются через внутренний event bus; команды идут через command bus
с идемпотентностью и per-device очередями.

```text
server/   Python 3.12 (uv): FastAPI, Bleak, SQLAlchemy async, structlog
ui/       React 19 + TypeScript + Vite + Tailwind v4 + PWA
mobile/   Android APK — TWA-обёртка PWA (bubblewrap)
deploy/   docker compose + ansible (целевой сервер), systemd, nginx (VPS), frp
docs/     статус/план, история, BLE-протокол, ADR, runbook, Яндекс
context/  требования (requirements.md)
```

## Разработка

Требуются `uv` и Node 22+.

```bash
cd server && uv sync          # зависимости сервера (+dev)
cd ui && npm install          # зависимости UI

make dev      # сервер: http://localhost:8000 (health: /api/system/health)
make dev-ui   # UI с прокси на сервер: http://localhost:5173
make test     # pytest (гейт покрытия ≥80 %) + vitest
make lint     # ruff + black + isort + mypy strict + oxlint + tsc
make fmt      # автоформатирование
make build-ui # прод-сборка UI (ui/dist, раздаётся сервером)
make apk      # Android APK → mobile/easy-breezy-<версия>.apk
```

Конфигурация — `.env` (см. `.env.example`), переменные с префиксом `EB_`.

Развёртывание на целевой сервер (Raspberry Pi): `make provision` (разово),
затем `make release VERSION=x.y.z && make deploy VERSION=x.y.z` —
см. `deploy/ansible/README.md`.

## Документы

- `docs/status.md` — точки входа в контекст и текущий план.
- `docs/history.md` — выполненные фазы и принятые решения.
- `docs/runbook.md` — стенд, возобновление работы, установка на Pi,
  бэкапы, диагностика BLE, APK.
- `docs/protocol/tion-s4-ble.md` — BLE-протокол Tion S4/Lite/S3 (clean-room
  спецификация; golden-векторы в `server/tests/golden/`).
- `docs/adr/` — архитектурные решения (ADR 0001–0007).
- `docs/yandex-setup.md` — настройка Яндекса и внешнего доступа.
- `context/requirements.md` — консолидированные требования.
- `mobile/README.md` — сборка APK, ключи, диагностика установки.
- `CLAUDE.md` — конвенции разработки.
- `deploy/ansible/README.md` — развёртывание на целевой сервер
  (docker compose + ansible, версии, откат).
- `deploy/` — остальные файлы развёртывания (systemd/docker/nginx/frp)
  с инструкциями в шапках.
