# Конвенции разработки — Easy Breezy

## Проект

Локальный сервис управления бризерами Tion S4 по BLE: Умный дом Яндекса (голос),
веб-PWA, автоматизация (сценарии/расписания/триггеры), датчики CO₂. Сервер — Linux
(Raspberry Pi 4). Монорепозиторий: `server/` (Python) + `ui/` (React PWA).

Ключевые документы: `context/requirements.md` (требования),
`docs/protocol/tion-s4-ble.md` (спецификация BLE-протокола),
`server/tests/golden/` (эталонные кадры протокола — данные, не менять руками).

## Структура

```text
server/src/easy_breezy/
├── ble/            # протокол (чистые кодеки) + транспорт + драйверы + супервизор
├── core/           # event bus, реестр, command bus, state cache, телеметрия
├── automation/     # сценарии, планировщик (croniter), триггеры
├── integrations/   # yandex/, mqtt/, magicair/, intents/
├── api/            # REST (/api/**), WebSocket, зависимости авторизации
└── storage/        # SQLAlchemy async, репозитории, Alembic, бэкапы
ui/                 # React 19 + TS + Vite + Tailwind v4 + PWA
deploy/             # systemd, docker, nginx, frp
```

## Технологии и инструменты

- Python 3.12, uv (зависимости и venv: `cd server && uv sync`).
- FastAPI + uvicorn, Pydantic v2, SQLAlchemy 2 async + aiosqlite + Alembic,
  Bleak (BLE), structlog (JSON-логи), croniter.
- UI: React 19, TypeScript strict, Vite, Tailwind v4, oxlint.
- Проверки: `make lint` (ruff, black, isort, mypy strict, oxlint, tsc),
  `make test` (pytest). Формат: `make fmt`.

## Стиль кода

- `black` (88), `isort` (profile black), `ruff`, `mypy --strict` — без исключений.
- Аннотации типов обязательны; `from __future__ import annotations`;
  `X | None` вместо `Optional[X]`.
- Докстринги Google-style на русском для публичных модулей/классов/функций.
- Именование: `snake_case` / `PascalCase` / `UPPER_SNAKE_CASE`; исключения — суффикс
  `Error`; булевы — префиксы `is_/has_/can_`; async-функции без префикса `async_`.

## Правила asyncio и BLE

- Все I/O — асинхронные. Блокирующие вызовы (`time.sleep`, синхронный `sqlite3`,
  `requests`) в event loop запрещены; CPU-bound — через `asyncio.to_thread`.
- Таймауты обязательны на каждую BLE- и сетевую операцию.
- `BleakError` и подклассы перехватывать явно; голый `except Exception` без
  re-raise/логирования запрещён.
- Переподключение — экспоненциальный backoff 1→60 с с джиттером (супервизор).
- Кодеки протокола (`ble/protocol/`) — чистые функции без I/O и без случайности
  (nonce инжектируется); обязаны проходить golden-тесты байт-в-байт.
- Никакого глобального mutable-состояния: зависимости передаются явно
  (фабрика приложения, DI через lifespan).

## Тестирование

- pytest + pytest-asyncio (`asyncio_mode=auto`), httpx ASGI для API.
- BLE-железо и сеть в тестах запрещены: FakeTransport, мокирование внешних API.
- Время в автоматизации — только через инжектируемый `Clock` (time-travel тесты).
- Целевое покрытие ≥ 80 % (гейт включается в Фазе 8).

## Логирование

- structlog, JSON-строки; уровни: DEBUG — детали BLE, INFO — события,
  WARNING — нештатное, ERROR — сбои. `print()` в продакшен-коде запрещён.
- BLE-события — логгер `easy_breezy.ble` (отдельный файл, Фаза 1).

## Git

- Формат коммита: `тип(область): описание` — типы: feat, fix, improvement,
  refactor, test, docs.
- Ветки: `feature/<описание>`, `fix/<описание>`; PR на фазу → `master`.
  Прямые коммиты в `master` запрещены; `master` всегда зелёный.

## Безопасность

- Секреты — только `.env` (см. `.env.example`); в git не попадают.
- Пароли/токены в БД — только хэши (argon2id / sha256 для opaque-токенов).
- Внешний доступ — только HTTPS (VPS: nginx + frp, `deploy/`).
