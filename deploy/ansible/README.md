# Easy Breezy — развёртывание (ansible + docker compose)

Целевой сервер (Raspberry Pi 4, Raspberry Pi OS/Debian) получает
версионированные docker-образы с dev-машины по ssh — без registry.
Управляет сервисом systemd-юнит поверх `docker compose`; самолечение —
таймер с health-чеком (`deploy/systemd/`).

## Разово

```bash
cp deploy/ansible/inventory.example.yml deploy/ansible/inventory.yml  # и заполнить
make provision        # docker, каталоги, юниты, заготовки конфигов
# на хосте: заполнить /opt/easy-breezy/.env (обязательно EB_TIMEZONE!)
#           и /opt/easy-breezy/frpc.toml (токен VPS)
```

## Каждый релиз

```bash
make release VERSION=x.y.z   # bump версии (pyproject + __init__), uv.lock,
                             # коммит + тег vx.y.z
make deploy VERSION=x.y.z    # build-ui → buildx arm64 → save|ssh|load →
                             # переключение версии → health-гейт → автооткат
```

Откат руками — деплой предыдущей версии: `make deploy VERSION=<прежняя>`
(образ уже загружен на хосте, сборка и доставка пройдут быстро, load —
идемпотентен).

## Раскладка на сервере

```text
/opt/easy-breezy/
├── docker-compose.yml   # копия deploy/docker/docker-compose.yml
├── deploy.env           # EB_IMAGE_VERSION=x.y.z + COMPOSE_PROFILES=tunnel,lan
├── .env                 # конфигурация приложения (EB_*)
├── frpc.toml            # туннель до VPS (профиль tunnel)
├── nginx/               # конфиг LAN-входа (профиль lan)
├── tls/                 # копия боевого серта, 0700 (eb-cert-sync.sh)
└── data/                # БД, бэкапы, VAPID-ключи (bind-mount в контейнер)
```

## LAN без интернета

Домашние устройства ходят на тот же домен, но напрямую в NUC: приложение
работает, пока жива локальная сеть, — интернет нужен только облачному CO₂,
пушам и голосу Яндекса. Два условия, оба разовые.

**1. DNS.** На роутере — статическая запись `easy-breezy.duckdns.org` → IP
NUC (MikroTik: `/ip dns static add name=easy-breezy.duckdns.org
address=<IP>`). Запись нужна на том устройстве, которое раздаёт DNS
телефонам; если точка доступа своя, то и на ней. Снаружи домен
по-прежнему резолвится в VPS — origin один, cookie и кэш PWA общие.

**2. Сертификат.** Самоподписанный не подойдёт: на домене HSTS, Chrome не
даст обойти ошибку, а TWA не запустится. Серт выпускает certbot на VPS
(ADR-0006), NUC забирает копию по ssh — ключ на VPS умеет ровно одно:

```bash
# на NUC (root): ключ только для этой задачи
ssh-keygen -t ed25519 -N "" -C eb-cert-sync@nuc -f /root/.ssh/eb-cert
ssh-keyscan -p <порт> <VPS> >> /root/.ssh/known_hosts

# на VPS: скрипт выдачи и forced command в authorized_keys
install -m 0755 /dev/stdin /usr/local/bin/eb-cert-dump <<'SH'
#!/bin/sh
set -eu
exec tar czhf - -C /etc/letsencrypt/live/easy-breezy.duckdns.org \
    fullchain.pem privkey.pem
SH
echo 'command="/usr/local/bin/eb-cert-dump",restrict ssh-ed25519 AAAA…' \
    >> ~/.ssh/authorized_keys
```

`restrict` запрещает ключу всё остальное — ни шелла, ни проброса портов;
`-h` в tar разыменовывает симлинки `live/`. Дальше на NUC:

```bash
systemctl start easy-breezy-cert-sync.service   # первая доставка
journalctl -t eb-cert-sync -n 5
systemctl restart easy-breezy.service           # поднимет nginx-контейнер
curl --resolve easy-breezy.duckdns.org:443:<IP NUC> \
    https://easy-breezy.duckdns.org/api/system/health
```

Таймер `easy-breezy-cert-sync.timer` ходит за сертом раз в сутки и
перезагружает nginx только при изменении файлов. Если копия протухает
(< 20 дней) или VPS недоступен со старым сертом — юнит падает и виден в
`systemctl --failed`: это единственный сигнал о сломавшемся продлении,
писем Let's Encrypt больше не шлёт.

BLE: контейнер в host-сети с монтированием `/var/run/dbus` — работает
через BlueZ хоста; бонды бризеров живут на хосте (сопрягать после переезда).
