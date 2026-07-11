# ADR-0001. Монорепозиторий и технологический стек

Дата: 2026-07-11. Статус: принято (Фаза 0).

## Контекст

Легаси `tion_btle` переписывается с нуля: локальный сервис управления
бризерами Tion S4 (BLE) с Умным домом Яндекса, веб-PWA и автоматизацией.
Боевая платформа — Raspberry Pi 4, соло-разработка.

## Решение

- Монорепозиторий: `server/` (Python) + `ui/` (React PWA) + `deploy/`
  (systemd/docker/nginx/frp) + `docs/` + `context/`.
- Сервер: Python 3.12, uv, FastAPI + uvicorn, Pydantic v2, SQLAlchemy 2 async
  + aiosqlite + Alembic, Bleak (BLE), structlog (JSON), croniter.
- UI: React 19, TypeScript strict, Vite, Tailwind v4, PWA; линт — oxlint.
- Качество: mypy strict без исключений, black/isort/ruff, pytest
  (`asyncio_mode=auto`), golden-тесты протокола; CI GitHub Actions.
- Git: `тип(область): описание`, работа в `feature/*`, merge в зелёный master.

## Последствия

- Один репозиторий = атомарные изменения протокола+сервиса+UI.
- Строгая типизация и golden-векторы — цена входа для любого кода протокола.
