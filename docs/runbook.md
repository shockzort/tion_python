# Runbook Easy Breezy

Процедуры эксплуатации и разработки. Статус и план — `docs/status.md`,
история фаз — `docs/history.md`.

## Возобновление разработки

```bash
cd server && uv sync && cd ../ui && npm install   # зависимости
make test && make lint        # pytest (покрытие ≥80 %) + vitest, линтеры
EB_FAKE_DEVICES=3 make dev    # dev на эмуляторах: :8000 (+ PWA из ui/dist)
make dev-ui                   # vite :5173 с прокси на :8000 (горячая замена)
uv run breezy state EC:82:9F:A4:90:14   # CLI по протоколу (бонд уже есть)
```

Смоук-сервис для ручной проверки поднимать на **другом порту и data_dir**
(`EB_PORT=8010 EB_DATA_DIR=/tmp/... EB_SESSION_COOKIE_SECURE=false`), гасить
по сохранённому PID — `pkill -f easy_breezy` убивает и стендовый сервис.

Первый вход: `POST /api/auth/setup {setup_token, username, password}` — токен
печатается в лог при старте без пользователей; дальше login-cookie или
api-токен (`POST /api/tokens`) с `Authorization: Bearer`.

## Отладочный стенд MVP (ноутбук)

Внешний доступ: `https://easy-breezy.duckdns.org` → VPS `195.133.20.205`
(nginx TLS + frps, юниты systemd) → frpc на ноутбуке → сервис :8000.

- Сервис: из `server/` командой `uv run python -m easy_breezy` в фоне
  (лог — scratchpad `eb-stand.log`); данные в `server/data/easy_breezy.db`;
  секреты в `server/.env` (client-креды Яндекса, Secure-cookie).
- frpc: `~/.local/opt/frp/frpc -c ~/.local/opt/frp/frpc.toml` (токен VPS внутри).
- Проверка: `curl https://easy-breezy.duckdns.org/api/system/health`.
- Учётка: `admin` (пароль у владельца).
- Бризеры (бонды на этом ноутбуке): `EC:82:9F:A4:90:14` Гостиная ·
  `D0:60:0E:F7:EA:D4` Детская · `EB:B5:4E:13:31:B5` Спальня.
  На боевом RPi сопряжение повторить (бонд per-host); у Детской/Спальни
  ресурс фильтра на нуле — владельцу заменить/сбросить.
- Датчики: `EB_MAGICAIR_EMAIL`/`EB_MAGICAIR_PASSWORD` (учётка приложения
  Tion) и/или `EB_MQTT_URL` в `server/.env`.
- Пока сервис держит соединения, MagicAir/Tion Remote к бризерам не
  подключаются (ADR-0005).

## Hardware-смоук Фазы 1 (реальный Tion S4, машина с BLE-адаптером)

Установка: `cd server && uv sync`, команды — через `uv run breezy …`
(или `breezy` после `uv tool install .`). Флаг `-v` включает DEBUG-логи BLE.

Прогон 2026-07-11 на EC:82:9F:A4:90:14 (ноутбук, Intel AX211): шаги 1–3, 5–8 (частично),
11, 12 — ✓; детали в спеке §5. Перед SET-тестами учитывать **MagicAir**: его
CO₂-автоуправление откатывает mode/heater/temp в течение минут (спека §1.6) —
«откатившийся SET» не является багом.

| # | Шаг | Ожидание | Статус / уточняем в спеке |
|---|---|---|---|
| 1 | `breezy scan` (бризер включён) | бризер виден: имя, MAC, RSSI | ✓ §1.1 |
| 2 | бризер в режим сопряжения (**кнопка ~5 с до синего мигания**; надёжнее всего из выключенного состояния: выключить → зажать — полевой опыт владельца; индикацию можно включить в приложении Tion) → `breezy pair <MAC> --wait 30` | «Сопряжение выполнено» + вывод состояния | ✓ все три (EC, EB, D0; через Device1.Pair; Page Timeout до нажатия кнопки → мгновенный успех в режиме сопряжения) §1.7/§5 |
| 3 | после бонда: `bluetoothctl` → `connect <MAC>` → `menu gatt` → `list-attributes` | сервис `98f00001-…`, характеристики `…0002`/`…0003` | ✓ §1.1 (handles 0x000f/0x0011) |
| 4 | `breezy state <MAC>`; рядом открыть приложение Tion | все поля совпадают с приложением | ⏳ (приложение забирает соединение — сверять по очереди) |
| 5 | `breezy set <MAC> --fan N` для N=1…6 | смена оборотов на слух, подтверждение в выводе | ✓ для N=2,3 (программно); полный ряд на слух — ⏳ |
| 6 | `breezy set <MAC> --heater`, затем `--no-heater` | инверсия бита записи (спека §1.5/1.6) | ✓ физикой: out_temp 22→24 °C; сверка с приложением — ⏳ |
| 7 | `breezy set <MAC> --temp 22` | цель в приложении | ✓ программно (25 °C применилась) |
| 8 | `breezy set <MAC> --mode recirculation`, затем `--mode outside` | заслонка слышна/видна | ✓ программно (mode=1 принят); на слух — ⏳; MagicAir откатывает |
| 9 | `breezy set <MAC> --sound --light`, затем `--no-sound --no-light` | реакция устройства | ⏳ |
| 10 | `breezy monitor <MAC>` → выдернуть питание бризера → подать | `[нет связи]` → `[на связи]` < 90 с, без перезапуска команды | удержание+опрос ✓ (80 с, интервал 20 с, без разрывов; занятый бризер — корректный ретрай); реконнект после обрыва питания — ⏳ |
| 11 | `breezy -v set <MAC> --fan 3` несколько раз | p95 «запись→кадр состояния» < 2 с | ✓ ~0.15 с |
| 12 | в `-v` логах после SET | state-кадр без запроса (§1.6); нет `crc_mismatch` (§4 п.3–4) | ✓ оба |

Результаты внесены в `docs/protocol/tion-s4-ble.md`; оставшиеся ⏳ — при следующем
подходе к железу (+ бонд-персистентность после power-cycle, §4 п. 0).

## Диагностика BLE-подключения (Linux/BlueZ)

Симптом: скан находит бризер, но `Connect()` падает мгновенно или соединение
поднимается и тут же рвётся с `org.bluez.Error.Failed: le-connection-abort-by-local`
(HCI `0x3E` «Connection Failed to be Established»).

`0x3E` = контроллер отправил `CONNECT_IND`, но **не получил от периферии ни одного
пакета** за 6 интервалов соединения. Хост тут может быть ни при чём: периферия либо
не услышала, либо **молча проигнорировала** запрос.

**Сначала — контрольный эксперимент** (2 минуты, отличает «сломан адаптер» от
«устройство нас отвергает»): подключиться тем же адаптером к 2–3 другим LE-устройствам
в эфире (телевизоры, колонки — короткий connect/disconnect безвреден). Чужие
подключаются, целевое — нет → адаптер исправен, причина на стороне устройства (п. 1).
Не подключается никто → смотреть хост (п. 2–6).

1. **Устройство принимает соединения только от сопряжённых центральных** (accept-list
   в прошивке): `CONNECT_IND` от незнакомого адреса игнорируется молча, детерминированно,
   при отличном RSSI. **Tion 4S: молчаливый игнор незнакомого центрального подтверждён
   полевым экспериментом 2026-07-11** (0/N на простаивающем адаптере, контрольные
   LE-устройства — 3/3). Разблокировка — режим сопряжения (кнопка ~5 с до синего
   мигания) + бонд; так работают esphome-tion/HA-tion («перед первым использованием
   переведите бризер в режим сопряжения»). Живое подтверждение сопряжения — см. §5 спеки.
2. **Активный скан во время connect.** Нельзя одновременно сканировать и
   инициировать LE-соединение. Частый источник — **открытое окно настроек Bluetooth**
   (GNOME/KDE держат непрерывный discovery, пока панель видима) или незакрытый
   `BleakScanner`. Проверка: `bluetoothctl show | grep Discovering` должно быть `no`
   перед connect. Лечение: закрыть настройки BT; в коде — connect только при
   остановленном скане (наш транспорт так и делает).
3. **Устаревшая запись в кэше BlueZ** (`Trusted: yes` при `Paired: no`) даёт ложный
   `Page Timeout`. Лечение: `bluetoothctl remove <mac>`.
4. **Фоновый авто-реконнект сопряжённых LE-устройств** (BLE мышь/клавиатура): ядро
   ведёт passive-скан для них (в `Discovering` не виден) и может ронять чужое
   соединение. Лечение: подключить/убрать эти устройства.
5. **Подвисший контроллер / драйвер адаптера.** `bluetoothctl power off/on` НЕ делает
   полный сброс. Реальный сброс: `sudo btmgmt power off && sudo btmgmt power on`
   или `sudo hciconfig hci0 reset`; сброс на уровне ОС (тумблер Bluetooth = rfkill).
6. **Багованный/зашумлённый адаптер** (дешёвые combo, WiFi/BT coexistence, активный
   A2DP-поток на том же радио). Даёт **вероятностные** сбои (часть попыток проходит),
   не детерминированный 0/N — отличать контрольным экспериментом. Лечение: разгрузить
   адаптер (пауза аудио), при стойких проблемах — известно-хороший USB BT-донгл.

Точный HCI-диагноз: `sudo btmon` во время попытки connect (нужен root; из-под
инструментов без TTY sudo не аутентифицируется — запускать в своём терминале).

## Установка на Raspberry Pi (docker compose + ansible)

Полное описание — `deploy/ansible/README.md`. Кратко, с dev-машины:

```bash
cp deploy/ansible/inventory.example.yml deploy/ansible/inventory.yml  # адрес Pi
make provision                  # docker, юниты, заготовки конфигов
# на Pi: заполнить /opt/easy-breezy/.env (обязательно EB_TIMEZONE — в
#        контейнере системная TZ = UTC) и /opt/easy-breezy/frpc.toml
make deploy VERSION=x.y.z       # выкат (см. «Обновление версии»)
journalctl -u easy-breezy -f    # setup-токен первого старта — в docker logs
```

Разово на dev-машине для кросс-сборки arm64:
`docker run --privileged --rm tonistiigi/binfmt --install arm64`.

Бонды BLE живут per-host (BlueZ хоста, контейнер ходит в его DBus):
после переезда с ноутбука на Pi бризеры сопрячь заново из мастера UI
(кнопка на бризере ~5 с до синего мигания).

## Бэкапы и восстановление (NFR-7)

Автоматика: ежедневно в 03:30 локальной TZ сервис делает `VACUUM INTO`
+ gzip в `data/backups/easy_breezy-YYYYMMDD-HHMMSS.db.gz`, хранит 7 штук;
провал уходит web push'ем и в лог (`backup_failed`).

Ручной снапшот (сервис можно не останавливать — WAL; на Pi данные лежат
в `/opt/easy-breezy/data`, sqlite3 ставит provision):

```bash
cd /opt/easy-breezy   # на стендовом ноутбуке: server/
sqlite3 data/easy_breezy.db "VACUUM INTO 'data/backups/manual.db'" && gzip data/backups/manual.db
```

Восстановление:

```bash
sudo systemctl stop easy-breezy
gunzip -c data/backups/easy_breezy-<дата>.db.gz > data/easy_breezy.db
rm -f data/easy_breezy.db-wal data/easy_breezy.db-shm
sudo systemctl start easy-breezy   # миграции докатятся сами
```

Проверенная процедура — тест `test_backup_and_restore_roundtrip`.

## Watchdog и самолечение BLE (NFR-4)

- Все сопряжённые бризеры офлайн > 10 мин → сервис делает power-cycle
  BLE-адаптера (BlueZ D-Bus, `ble_adapter_power_cycled` в логе).
- Ещё 10 мин тишины → сервис завершает себя (`watchdog_restart_service`),
  контейнер поднимает docker (`restart: unless-stopped`).
- Зависание event loop ловит health-watchdog хоста:
  `easy-breezy-watchdog.timer` раз в 30 с дёргает `/api/system/health`,
  4 провала подряд (~2 мин) → `systemctl restart easy-breezy`
  (лог — `journalctl -t eb-watchdog`). Внутри контейнера sd_notify — no-op
  (`core/sdnotify.py`), прежний systemd WatchdogSec заменён этим таймером.
- Ручная эскалация, если адаптер не ожил и после рестарта:
  `sudo btmgmt power off && sudo btmgmt power on` (полный сброс контроллера,
  Powered-цикл BlueZ его не делает), дальше — reboot хоста.

## Уведомления (web push)

Включаются на каждом устройстве отдельно: Настройки → «Уведомления»
(нужен установленный PWA или Chrome; iOS Safari — только PWA с экрана
«Домой»). VAPID-ключи генерируются в `data/vapid_private.pem` при первом
старте; `EB_PUSH_CONTACT` — контакт для пуш-сервисов (https-URL или mailto).

## Android APK

`make apk` → `mobile/easy-breezy-<версия>.apk` (TWA-обёртка PWA: обновления
приходят с сервера, пересборка нужна только под смену домена/иконки/имени;
промежуточные артефакты сборка удаляет). Детали, ключи, структура и
диагностика «не удалось установить» — `mobile/README.md`. Отпечаток подписи
раздаётся сервером (`/.well-known/assetlinks.json`) — без него TWA
открывается с адресной строкой.

## Обновление версии

С dev-машины, из корня репозитория (детали — `deploy/ansible/README.md`):

```bash
make release VERSION=x.y.z   # bump версии (pyproject + __init__ + uv.lock),
                             # коммит + тег vx.y.z
make deploy VERSION=x.y.z    # build-ui → buildx arm64 → save|ssh|load →
                             # переключение версии → health-гейт → автооткат
```

Откат = деплой предыдущей версии тем же `make deploy` (образ уже на хосте).
Миграции БД применяются на старте сервиса автоматически.
