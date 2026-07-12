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
├── deploy.env           # EB_IMAGE_VERSION=x.y.z + COMPOSE_PROFILES=tunnel
├── .env                 # конфигурация приложения (EB_*)
├── frpc.toml            # туннель до VPS (профиль tunnel)
└── data/                # БД, бэкапы, VAPID-ключи (bind-mount в контейнер)
```

BLE: контейнер в host-сети с монтированием `/var/run/dbus` — работает
через BlueZ хоста; бонды бризеров живут на хосте (сопрягать после переезда).
