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

## Боевой сервер (NUC, docker compose)

Хост: `ssh nuc-minisforum-wifi` (Ubuntu, x86_64), раскладка
`/opt/easy-breezy` — см. `deploy/ansible/README.md`. Переезд со
стендового ноутбука — 2026-07-12 (данные и конфиги перенесены).

Внешний доступ: `https://easy-breezy.duckdns.org` → VPS `195.133.20.205`
(nginx TLS + frps, юниты systemd) → frpc-контейнер на NUC → сервис :8000.

Локальный доступ: тот же домен, но прямо в NUC — nginx-контейнер (профиль
`lan`) слушает 443 с копией боевого серта. Работает, пока жива LAN, даже
без интернета. Условие — статическая DNS-запись `easy-breezy.duckdns.org`
→ IP NUC на том устройстве, которое раздаёт DNS телефонам (домашние
клиенты приходят NAT'ом от `192.168.88.3`, то есть DNS у них оттуда же).
Проверка: `curl --resolve easy-breezy.duckdns.org:443:192.168.88.248
https://easy-breezy.duckdns.org/api/system/health`. Настройка с нуля —
`deploy/ansible/README.md`, раздел «LAN без интернета».

- Серт: выпускает и продлевает certbot на VPS, NUC забирает копию суточным
  таймером `easy-breezy-cert-sync.timer` (лог — `journalctl -t eb-cert-sync`)
  и перезагружает nginx только при изменении файлов. Юнит **падает**, если
  копия истекает меньше чем через 20 дней — это единственный сигнал о
  сломавшемся продлении на VPS (писем Let's Encrypt не шлёт). Смотреть в
  `systemctl --failed`.
- Без интернета не работают: облачный CO₂ (MagicAir), пуши, голос Яндекса.
  Расписания, сценарии, BLE — работают.
- Стабильность BLE упирается в RSSI (`sudo btmgmt conn-info -t 2 <MAC>`):
  −72 dBm — связь без разрывов, на −88 dBm бризер был офлайн половину
  времени.
  Супервизорный таймаут поднят с дефолтных 420 мс до 5 с — разбор и цифры
  замера в `deploy/ansible/README.md`, «BLE: радио и супервизорный таймаут».
- Управление: `sudo systemctl {start|stop|restart} easy-breezy`
  (юнит поверх `docker compose`); новая версия — `make release` +
  `make deploy` с dev-машины (раздел «Обновление версии»).
- Логи: `sudo docker logs -f easy-breezy-easy-breezy-1`; watchdog —
  `journalctl -t eb-watchdog`; статус контейнеров — `sudo docker ps`.
- Проверка: `curl https://easy-breezy.duckdns.org/api/system/health`.
- Секреты: `/opt/easy-breezy/.env` (креды Яндекса, MagicAir,
  `EB_TIMEZONE` — обязателен, в контейнере системная TZ = UTC);
  токен туннеля — `/opt/easy-breezy/frpc.toml`.
- Учётка: `admin` (пароль у владельца; БД перенесена со стенда).
- Бризеры: `EC:82:9F:A4:90:14` Гостиная · `D0:60:0E:F7:EA:D4` Детская ·
  `EB:B5:4E:13:31:B5` Спальня. Бонды BLE — per-host: после переезда
  сопрячь заново из мастера UI (кнопка ~5 с до синего мигания);
  у Детской/Спальни ресурс фильтра на нуле — заменить/сбросить.
- Датчики: `EB_MAGICAIR_EMAIL`/`EB_MAGICAIR_PASSWORD` (учётка приложения
  Tion) и/или `EB_MQTT_URL` в `.env`.
- Пока сервис держит соединения, MagicAir/Tion Remote к бризерам не
  подключаются (ADR-0005).
- BLE в контейнере: host-сеть + `/var/run/dbus` + `apparmor=unconfined`
  (полевой факт 2026-07-12: профиль docker-default на Ubuntu режет
  D-Bus-вызовы к BlueZ — `AccessDenied ... AppArmor policy prevents`,
  уже учтено в compose).

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

Сначала сопоставить журналы приложения, BlueZ и пассивную HCI-трассу.
Код HCI сам по себе не устанавливает виновника: нужны этап, адрес,
направление disconnect и время. Связь с другими **своими** устройствами
помогает сузить поиск, но не доказывает исправность адаптера во всех режимах.

1. **Приложение.** Ищем `device_search_failed`, `transport_start_failed`
   (connect/start_notify), `state_response_timeout`, `poll_missed`,
   `device_session_failed`, `reconnect_backoff`. Сравниваем адрес, попытку,
   request_id, длительность. После ошибки или отмены start частичное
   соединение закрывается до освобождения scan gate.
2. **Конкуренция за радио.** Поддержка одновременного сканирования и соединений
   зависит от адаптера ([BleakClient](https://bleak.readthedocs.io/en/latest/api/client.html)).
   Наш gate сериализует поиск/подключение; Qingping уступает им адаптер.
   Он действует внутри процесса: `breezy scan`, `breezy pair` и другие
   диагностические CLI не запускать параллельно боевому сервису. Использовать
   мастер UI/API и пассивный `sudo btmon`. Проверить открытые Bluetooth-панели
   и другие приложения, затем `bluetoothctl show` / `Discovering`.
3. **Сопряжение.** `Trusted` и `Paired` — разные свойства. Их сочетание не
   доказывает повреждённый кэш. `bluetoothctl remove` удаляет также бонд,
   поэтому это не первый шаг диагностики. При первичной настройке S4 нужен
   режим сопряжения (кнопка около 5 секунд до синего мигания; подробнее §5 спеки).
4. **Радиоканал.** Снять RSSI своих подключённых бризеров:
   `sudo btmgmt conn-info -t 2 <MAC>`, сравнить задержки GET и разрывы.
   Проверить расположение антенн, расстояние, другие нагрузки на радио.
   Низкий RSSI — фактор риска, а не доказанная причина конкретного сбоя.
5. **Хост.** Сохранить `journalctl -u bluetooth` и `journalctl -k`, проверить
   HCI/USB errors, `rfkill list`, версии ядра, BlueZ и firmware. Настройки
   энергосбережения менять только после сопоставления suspend с инцидентом.
   `ConnectionSupervisionTimeout=500` в BlueZ — запрошенные 5 секунд;
   фактические параметры конкретного соединения проверяются по HCI.
6. **Ручное восстановление.** После сохранения evidence начать с штатного
   рестарта приложения. `bluetoothctl power off/on` и `btmgmt power off/on`
   оба используют MGMT Set Powered: второй не гарантирует более глубокий
   аппаратный reset. Перезапуск BlueZ/адаптера затрагивает все его устройства;
   выбирать его только при подтверждённом общем сбое.

С 0.3.1 журнал сохраняется в `/opt/easy-breezy/data/logs/easy-breezy.log`
с пятью архивами по 10 MiB (до 60 MiB вместе). Он переживает `compose down`.
`shutdown_started` / `shutdown_complete` позволяют проверить штатную остановку;
Docker ждёт её до 60 секунд. При выкате доставляются и образ, и compose,
при провале health откатываются оба. Подробности проверки гипотез:
[исследование Bluetooth](tasks/bluetooth-investigation-2026-10-08/reports/0_investigation.md).

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

### Ночной бэкап всей инсталляции на VPS

Снапшот БД живёт на том же диске, что и сама БД, поэтому раз в ночь
(`easy-breezy-backup.timer`, ~04:15, после снапшота 03:30) хост собирает
**всю инсталляцию** в один архив, шифрует его и увозит на VPS:

| В архиве | Зачем |
|---|---|
| свежий `data/backups/easy_breezy-*.db.gz` | устройства, комнаты, датчики, автоматика, пользователи, телеметрия |
| `.env`, `deploy.env`, `docker-compose.yml`, `frpc.toml`, `cert-sync.env`, `backup-offsite.env` | конфигурация и секреты |
| `data/vapid_private.pem` | без него подписки на пуши придётся оформлять заново |
| `tls/`, `nginx/`, `mosquitto/config/` | LAN-вход и учётки брокера датчиков |
| `/root/.ssh/eb-cert*` | ключ доставки сертификата с VPS |
| `/var/lib/bluetooth` | сопряжения бризеров — без них каждый 4S сопрягать заново |

- Шифрование — [age](https://age-encryption.org). Ключ в двух местах:
  на NUC `/opt/easy-breezy/backup/age.key` (root, 0600) и у владельца
  `~/.config/easy-breezy/backup-age.key` (provision кладёт копию на
  машину, с которой запускается). **Сохраните копию ключа ещё и в
  менеджер паролей**: без ключа архивы не прочесть. Сам ключ в архив не
  входит.
- Хранение: последние 7 копий (`EB_BACKUP_KEEP`) в
  `/opt/easy-breezy/backups/offsite/`, то же зеркало на VPS в
  `/srv/eb-backup/` (rsync `--delete`). Копия ≈ 7 МБ.
- Доступ NUC → VPS: пользователь `eb-backup`, ключ `/root/.ssh/eb-backup`
  с forced command `rrsync -wo /srv/eb-backup` — только запись в свой
  каталог, ни шелла, ни чтения. Скачивать копии с VPS — под админом VPS.
- Всё ставит `make provision` (группа `backup_vps` в inventory,
  см. `deploy/ansible/inventory.example.yml`).
- Сбой (VPS недоступен, снапшот БД старше 30 ч, архив не расшифровался)
  — юнит падает: `systemctl --failed`, `journalctl -t eb-backup`.

Проверка и ручной запуск (на NUC):

```bash
sudo systemctl start easy-breezy-backup.service
journalctl -t eb-backup -n 5
systemctl list-timers easy-breezy-backup.timer
```

Восстановление на чистый хост:

```bash
# 1. скачать архив с VPS (под админом VPS) и расшифровать там, где есть ключ
scp -P 1962 root@<VPS>:/srv/eb-backup/easy-breezy-<host>-<дата>.tar.gz.age .
age -d -i ~/.config/easy-breezy/backup-age.key easy-breezy-*.tar.gz.age > restore.tar.gz

# 2. make provision на новый хост (ключ age вернётся на NUC из копии владельца),
#    затем на хосте — распаковать поверх (пути в архиве от корня):
sudo systemctl stop easy-breezy bluetooth
sudo tar -xzf restore.tar.gz -C /
sudo systemctl start bluetooth

# 3. БД из снапшота в архиве — как в разделе выше
cd /opt/easy-breezy
gunzip -c data/backups/easy_breezy-<дата>.db.gz > data/easy_breezy.db
rm -f data/easy_breezy.db-wal data/easy_breezy.db-shm

# 4. выкатить версию (make deploy VERSION=x.y.z) — сервис поднимется сам
```

Сопряжения BlueZ привязаны к MAC адаптера (`/var/lib/bluetooth/<MAC>/`):
на другом железе каталог надо переименовать под новый адаптер
(`bluetoothctl list`) до запуска bluetooth.

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
- Операции watchdog ограничены временем; отмена power-cycle всё равно
  пытается вернуть `Powered=true`. Неудача отражается в журнале.
- Ручная эскалация — по диагностике выше. Общий сброс адаптера не применяется
  автоматически при недоступности одного бризера.

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
