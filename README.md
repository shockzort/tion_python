# Easy Breezy

Локальный сервис управления бризерами **Tion S4** без облака Tion и базовой станции:
BLE-управление с Linux-сервера (Raspberry Pi), голос через **Умный дом Яндекса**,
единый веб-интерфейс (**PWA** — браузер и телефон), автоматизация по времени и
датчикам CO₂, задел под локальную LLM.

> Приватный проект. Статус: **Фаза 0** — каркас, спецификация протокола, требования.
> Дорожная карта: `context/requirements.md` §5 и план фаз в PR фазы 0.

## Архитектура

Один asyncio-процесс (FastAPI + BLE + автоматизация) под systemd; React-PWA
раздаётся сервером; наружу — frp-туннель до VPS с nginx/TLS (для Яндекса).
Подсистемы общаются через внутренний event bus; команды идут через command bus
с идемпотентностью и per-device очередями.

```text
server/   Python 3.12 (uv): FastAPI, Bleak, SQLAlchemy async, structlog
ui/       React 19 + TypeScript + Vite + Tailwind v4 + PWA
deploy/   systemd, docker-compose, nginx (VPS), frp
docs/     спецификация BLE-протокола Tion, runbook (по фазам)
context/  требования (requirements.md)
```

## Разработка

Требуются `uv` и Node 22+.

```bash
cd server && uv sync          # зависимости сервера (+dev)
cd ui && npm install          # зависимости UI

make dev      # сервер: http://localhost:8000 (health: /api/system/health)
make dev-ui   # UI с прокси на сервер: http://localhost:5173
make test     # pytest
make lint     # ruff + black + isort + mypy strict + oxlint + tsc
make fmt      # автоформатирование
make build-ui # прод-сборка UI (ui/dist, раздаётся сервером)
```

Конфигурация — `.env` (см. `.env.example`), переменные с префиксом `EB_`.

## Документы

- `context/requirements.md` — консолидированные требования и принятые решения.
- `docs/protocol/tion-s4-ble.md` — BLE-протокол Tion S4/Lite/S3 (clean-room
  спецификация; golden-векторы в `server/tests/golden/`).
- `CLAUDE.md` — конвенции разработки.
- `deploy/` — файлы развёртывания (systemd/docker/nginx/frp) с инструкциями в шапках.

## Фазы

0. ✅ Каркас, спецификация, требования, CI
1. BLE-библиотека (кодек S4, транспорт, супервизор) + CLI `breezy`
2. Хранилище, event/command bus, REST+WS, авторизация
3. UI: дашборд, управление, мастер сопряжения (PWA)
4. Умный дом Яндекса + внешний доступ (frp/nginx/TLS) — **MVP**
5. Автоматизация (сценарии/расписания) + телеметрия/графики
6. Датчики (MagicAir cloud, MQTT) + триггеры по CO₂
7. Текстовые интенты (rule-based → локальная LLM)
8. Полировка: web push, бэкапы, runbook, soak-тест
