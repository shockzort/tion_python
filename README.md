# Easy Breezy

Локальный сервис управления бризерами **Tion S4** без облака Tion и базовой станции:
BLE-управление с Linux-сервера (Raspberry Pi), голос через **Умный дом Яндекса**,
единый веб-интерфейс (**PWA** — браузер, телефон, Android APK), автоматизация по
времени и датчикам CO₂, задел под локальную LLM.

> Лицензия: [PolyForm Noncommercial 1.0.0](LICENSE) — свободное
> некоммерческое использование. Статус: **MVP работает** (фазы 0–7 и 9 в master) —
> BLE-управление, PWA, сценарии/расписания/триггеры, датчики воздуха
> (MagicAir cloud, Qingping по Wi-Fi/BLE, MQTT), текстовые интенты, web push,
> бэкапы, APK.
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

## Датчики воздуха

Датчики добавляются в интерфейсе: **Устройства → Датчики → Добавить датчик** →
тип → поиск (или адрес вручную) → комната и имя. Мастер показывает, что
датчик умеет измерять (CO₂, температура, влажность, PM2.5/PM10, заряд);
по этим показателям доступны карточки, графики и правила автоматики.

| Тип | Как подключается | Что нужно |
|---|---|---|
| Tion MagicAir | облако Tion, появляются сами | `EB_MAGICAIR_EMAIL/PASSWORD` в `.env` |
| **Qingping Air Monitor Lite (CGDN1) · Wi-Fi** — рекомендуемый | датчик шлёт данные на брокер сервиса раз в минуту | разовая настройка на портале Qingping — ниже |
| Qingping Air Monitor Lite · Bluetooth | пассивный приём BLE-рекламы | датчик в радиусе Bluetooth сервера |
| MQTT-датчик | JSON или числа в свой топик | брокер сервиса (`EB_MQTT_URL`) |

### Qingping CGDN1 по Wi-Fi (MQTT)

Брокер Mosquitto ставится вместе с сервисом (`make provision`, профиль
`mqtt`) и сам заводит пароли — см. `deploy/ansible/README.md`.

1. Привяжите датчик к приложению **Qingping+** (или Qingping IoT), он должен
   быть в домашнем Wi-Fi. Прошивка — не ниже 4.1.8 (проверено на 4.8.5).
2. На компьютере откройте **https://developer.qingping.co** → войдите той же
   учёткой → **Private Access Config → Configurations → Add**:
   - Device Model — *Qingping Air Monitor Lite*, Private Type — *Self-built MQTT*;
   - в «Self-built MQTT Information» (`<MAC>` — MAC Wi-Fi датчика
     ЗАГЛАВНЫМИ без двоеточий, виден в приложении):

     ```text
     host=<IP сервера в LAN>
     port=1883
     username=qingping
     password=<EB_MQTT_DEVICE_PASSWORD из /opt/easy-breezy/.env>
     clientId=qingping-<MAC>
     topicUp=qingping/<MAC>/up
     topicDown=qingping/<MAC>/down
     ```

   - Interval of Uploading и Interval of Recording — **1 minute** (данные
     старше 5 минут сервис считает устаревшими).
3. **Private Access Config → Devices → Add** — выберите датчик и назначьте
   ему конфигурацию.
4. Перезагрузите датчик (долгое нажатие кнопки → выключить → включить).
   На датчике *Settings → Private Cloud* должен показать подключение;
   из Qingping+ он, скорее всего, пропадёт — это ожидаемо.
5. В Easy Breezy: **Добавить датчик → Qingping · Wi-Fi** — датчик найдётся
   сам в течение минуты; выберите комнату и имя.

Дальше сервис сам держит датчик в режиме «показания раз в минуту», отвечает
на его служебные запросы (синхронизация часов) и подтверждает историю.
Изменить настройки на портале можно только со сбросом датчика к заводским.
Подробности и диагностика — `docs/qingping.md`.

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
