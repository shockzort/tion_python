# Подключение к Умному дому Яндекса

Пошаговая настройка внешнего доступа и навыка. Код готов (Фаза 4);
здесь — инфраструктура и регистрация, выполняется владельцем один раз.

Архитектура: `Pi (easy-breezy :8000) → frpc → VPS (frps :18000, localhost)
→ nginx (TLS :443) → интернет → Яндекс`.

## Шаг 0. TLS: IP-сертификат, DuckDNS или свой домен (план §6)

**Решение владельца (ADR-0006): путь B — DuckDNS.** A и C оставлены как
альтернативы на будущее.

Яндексу нужен публичный HTTPS с валидным сертификатом. Три пути:

**Путь A — IP-сертификат Let's Encrypt (без домена).**
Let's Encrypt выдаёт короткоживущие (~6 дней) сертификаты на голый IP
(профиль `shortlived`, требуется certbot ≥ 4.0 с поддержкой ACME-профилей):

```bash
certbot certonly --nginx --preferred-profile shortlived -d <IP-VPS>
```

Перед выбором пути A — проверка в консоли Диалогов: создайте черновик навыка
(шаг 3) и попробуйте сохранить Endpoint URL вида `https://203.0.113.7/v1.0`.
Если консоль принимает URL с IP — путь A рабочий; если требует домен — B или C.

**Путь B — бесплатный поддомен DuckDNS (выбран).**

1. <https://www.duckdns.org> → вход (через GitHub/Google) → в поле
   «sub domain» создать поддомен `<имя>.duckdns.org` → в его строке вписать
   IP VPS в «current ip» → update ip. Проверка:

   ```bash
   dig +short <имя>.duckdns.org   # должен ответить IP VPS
   ```

2. Обновлятор IP не нужен (VPS статичен); если IP сменится — поправить в
   личном кабинете или cron с их curl-строкой.
3. Выпуск сертификата и продление — внутри шага 1 (сначала ставится nginx).

**Путь C — собственный (платный) домен: самый надёжный.**

1. Купите домен у любого регистратора (REG.RU, Timeweb, Namecheap, …).
2. В DNS-панели регистратора создайте **A-запись** на IP VPS — на весь домен
   (`@` → `203.0.113.7`) или на поддомен (`breezy` → `203.0.113.7`, получится
   `breezy.мойдомен.ru` — удобно, если домен нужен и для другого). Поле NS/
   nameservers не трогайте — правится только A-запись. Дождитесь
   распространения (обычно минуты):

   ```bash
   dig +short breezy.мойдомен.ru   # должен ответить IP VPS
   ```

3. Выпишите сертификат. Проверка HTTP-01 приходит на порт 80 — он должен быть
   открыт в файрволе VPS, а nginx уже установлен (шаг 1; certbot допишет пути
   сертификата в конфиг и перезагрузит nginx сам):

   ```bash
   sudo certbot --nginx -d breezy.мойдомен.ru
   ```

4. Продление автоматическое (сертификат на 90 дней, certbot ставит
   systemd-таймер при установке). Проверьте:

   ```bash
   systemctl list-timers | grep certbot
   sudo certbot renew --dry-run
   ```

С собственным доменом развилка A/B отпадает: консоль Диалогов принимает домен
без вопросов, сертификаты обычные 90-дневные, ничего короткоживущего.

Дальше `<host>` = `<имя>.duckdns.org` (путь B принят — ADR-0006).

## Шаг 1. VPS: nginx + сертификат + frps

Команды для Ubuntu/Debian (на CentOS/Alma — `dnf install nginx certbot
python3-certbot-nginx`, остальное так же).

**1.1. Установка nginx и certbot:**

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
sudo systemctl enable --now nginx
curl -I http://localhost        # HTTP/1.1 200 — nginx жив
```

**1.2. Файрвол** — открыть 80, 443 (nginx) и 7000 (frp); у многих VPS это
панель провайдера, при ufw:

```bash
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 7000/tcp
```

Порт 18000 наружу НЕ открывать — он слушается только на localhost,
наружу смотрит nginx :443.

**1.3. Сертификат** (поддомен DuckDNS уже указывает на VPS — шаг 0; выпуск
`certonly`, чтобы certbot не правил наш конфиг — пути пропишем сами):

```bash
sudo certbot certonly --nginx -d <имя>.duckdns.org
sudo certbot renew --dry-run    # автопродление (таймер ставится при установке)
```

**1.4. Наш конфиг** (после сертификата — иначе `nginx -t` упадёт на путях):

```bash
sudo cp deploy/nginx/easy-breezy.conf.example /etc/nginx/conf.d/easy-breezy.conf
# в конфиге: server_name → <имя>.duckdns.org, пути сертификата →
#   /etc/letsencrypt/live/<имя>.duckdns.org/fullchain.pem и privkey.pem
sudo rm -f /etc/nginx/sites-enabled/default   # дефолтный сайт не нужен
sudo nginx -t && sudo systemctl reload nginx
```

**1.5. frps (сервер туннеля):**

```bash
curl -LO https://github.com/fatedier/frp/releases/latest/download/frp_*_linux_amd64.tar.gz
tar xzf frp_*.tar.gz && sudo cp frp_*/frps /usr/local/bin/
sudo mkdir -p /etc/frp && sudo cp deploy/frp/frps.toml.example /etc/frp/frps.toml
# в frps.toml задать auth.token (openssl rand -hex 16)
sudo systemctl enable --now frps   # юнит по аналогии с deploy/frp/frpc.service
```

Проверка TLS сразу после 1.4 (frpc ещё нет — ждём 502, но по HTTPS):

```bash
curl -sI https://<имя>.duckdns.org | head -1   # HTTP/2 502 — TLS работает
```

## Шаг 2. Pi: frpc

```bash
sudo cp frp_*/frpc /usr/local/bin/
sudo mkdir -p /etc/frp && sudo cp deploy/frp/frpc.toml.example /etc/frp/frpc.toml
# serverAddr = IP VPS, auth.token = тот же секрет
sudo cp deploy/frp/frpc.service /etc/systemd/system/
sudo systemctl enable --now frpc
```

Проверка сквозного пути: `curl https://<host>/api/system/health` → `{"status":"ok"}`.

## Шаг 3. Регистрация навыка (dev.dialogs.yandex.ru)

1. Консоль разработчика → «Создать диалог» → **Умный дом**.
2. Название произвольное («Easy Breezy»), навык **приватный** — публикация
   не нужна, работает на аккаунте владельца.
3. **Endpoint URL**: `https://<host>` — **без** `/v1.0`: платформа сама
   добавляет `/v1.0/...` к адресу (проверка доступности — `HEAD <host>/v1.0`,
   запросы — `<host>/v1.0/user/devices` и т.д.).
4. **Связка аккаунтов (OAuth)**:
   - идентификатор приложения: придумать → `EB_YANDEX_CLIENT_ID`;
   - секрет приложения: `openssl rand -hex 24` → `EB_YANDEX_CLIENT_SECRET`;
   - URL авторизации: `https://<host>/oauth/authorize`;
   - URL получения токена: `https://<host>/oauth/token`;
   - URL обновления токена: тот же `/oauth/token`.
5. Сохранить черновик. Из консоли выписать:
   - **skill_id** (идентификатор навыка из URL консоли) → `EB_YANDEX_SKILL_ID`;
   - **OAuth-токен для Callback API** (в консоли Диалогов; токен с правом
     нотификаций навыка) → `EB_YANDEX_CALLBACK_TOKEN`.

## Шаг 4. .env на Pi и рестарт

```bash
EB_YANDEX_CLIENT_ID=...
EB_YANDEX_CLIENT_SECRET=...
EB_YANDEX_SKILL_ID=...
EB_YANDEX_CALLBACK_TOKEN=...
# EB_YANDEX_REDIRECT_URI менять не нужно (брокер Яндекса, значение по умолчанию)
sudo systemctl restart easy-breezy
# в логе должно появиться yandex_callbacks_started (не ..._disabled)
```

## Шаг 5. Линковка и голосовой чек-лист (план §14)

Приложение «Дом с Алисой» → «+» → «Устройство умного дома» → найти свой
навык → откроется наша страница логина → войти учёткой Easy Breezy →
устройства появятся в списке.

Чек-лист приёмки:

- [ ] «Алиса, включи бризер в спальне» — включается, < 3 с
- [ ] «скорость три» — вентилятор слышно, UI показывает 3
- [ ] «включи обогрев», «22 градуса» — нагрев и целевая температура
- [ ] «выключи звук» / «включи подсветку» — тумблеры
- [ ] повтор команды (ретрай Яндекса) не даёт второй записи в журнале
      (`/api/commands`: одна команда на X-Request-Id)
- [ ] обесточить бризер → «устройство недоступно»; подать питание →
      реконнект < 90 с, состояние в «Доме с Алисой» оживает
- [ ] изменить скорость с самого бризера/из PWA → «Дом с Алисой» видит
      новое состояние без опроса (callback state)

## Отладка

- `502` от Яндекса — сервис на Pi недоступен через туннель: `systemctl
  status frpc` на Pi, `frps` на VPS, `curl https://<host>/api/system/health`.
- Линковка падает на логине — смотреть журнал: `journalctl -u easy-breezy |
  grep oauth`; частое — client_id/secret в консоли и .env не совпадают.
- Callbacks не доходят (состояние в Алисе стареет) — в логе
  `yandex_callback_failed`: проверить skill_id и callback-токен.
- Сертификат пути A живёт ~6 дней — убедиться, что таймер certbot активен:
  `systemctl list-timers | grep certbot`.
