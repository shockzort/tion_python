#!/bin/sh
# Доставка TLS-сертификата на NUC для LAN-входа (deploy/nginx/easy-breezy-lan.conf).
# Выпускает и продлевает серт certbot на VPS (ADR-0006) — второй ACME-аккаунт
# заводить незачем; сюда копия приезжает по ssh с forced command: ключ на той
# стороне умеет ровно одно — отдать fullchain+privkey (см. deploy/ansible/README.md).
# Вызывается easy-breezy-cert-sync.timer раз в сутки; nginx перезагружается
# только когда файлы реально изменились (продление раз в ~60 дней).
set -eu

: "${EB_CERT_SSH_HOST:=root@195.133.20.205}"
: "${EB_CERT_SSH_PORT:=1962}"
: "${EB_CERT_SSH_KEY:=/root/.ssh/eb-cert}"
: "${EB_TLS_DIR:=/opt/easy-breezy/tls}"
: "${EB_NGINX_CONTAINER:=easy-breezy-nginx-1}"

WARN_DAYS=20

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Предупреждение о протухающей копии — единственный сигнал о сломавшемся
# продлении на VPS: писем Let's Encrypt больше не шлёт, а до отказа TLS
# остаётся месяц тишины. Юнит падает, значит видно в systemctl --failed.
check_local_expiry() {
    cert="$EB_TLS_DIR/fullchain.pem"
    [ -f "$cert" ] || { logger -t eb-cert-sync "серта нет: $cert"; return 1; }
    if openssl x509 -in "$cert" -noout -checkend $((WARN_DAYS * 86400)) >/dev/null 2>&1; then
        return 0
    fi
    logger -t eb-cert-sync \
        "серт истекает меньше чем через $WARN_DAYS дн. — проверьте certbot на VPS"
    return 1
}

if ! ssh -i "$EB_CERT_SSH_KEY" -p "$EB_CERT_SSH_PORT" \
        -o BatchMode=yes -o ConnectTimeout=15 \
        "$EB_CERT_SSH_HOST" >"$tmp/bundle.tgz" 2>"$tmp/ssh.err"; then
    logger -t eb-cert-sync "VPS недоступен: $(tr '\n' ' ' <"$tmp/ssh.err")"
    # нет интернета — старая копия ещё валидна, это не авария
    check_local_expiry && exit 0
    exit 1
fi

tar xzf "$tmp/bundle.tgz" -C "$tmp" fullchain.pem privkey.pem

# Битая пара до nginx не доезжает: рабочий старый серт важнее свежего.
if ! openssl x509 -in "$tmp/fullchain.pem" -noout -checkend 0 >/dev/null 2>&1; then
    logger -t eb-cert-sync "серт с VPS просрочен или не парсится — пропуск"
    exit 1
fi
cert_pub=$(openssl x509 -in "$tmp/fullchain.pem" -noout -pubkey 2>/dev/null || true)
priv_pub=$(openssl pkey -in "$tmp/privkey.pem" -pubout 2>/dev/null || true)
if [ -z "$cert_pub" ] || [ "$cert_pub" != "$priv_pub" ]; then
    logger -t eb-cert-sync "ключ не подходит к сертификату — пропуск"
    exit 1
fi

if cmp -s "$tmp/fullchain.pem" "$EB_TLS_DIR/fullchain.pem" \
        && cmp -s "$tmp/privkey.pem" "$EB_TLS_DIR/privkey.pem"; then
    check_local_expiry && exit 0   # продления не было — обычный день
    exit 1
fi

install -d -m 0700 "$EB_TLS_DIR"
install -m 0644 "$tmp/fullchain.pem" "$EB_TLS_DIR/fullchain.pem"
install -m 0600 "$tmp/privkey.pem" "$EB_TLS_DIR/privkey.pem"
logger -t eb-cert-sync "серт обновлён, годен до $(
    openssl x509 -in "$EB_TLS_DIR/fullchain.pem" -noout -enddate | cut -d= -f2)"

if docker exec "$EB_NGINX_CONTAINER" nginx -s reload >/dev/null 2>&1; then
    logger -t eb-cert-sync "nginx перезагружен"
else
    logger -t eb-cert-sync "nginx не перезагружен (контейнер не запущен?)"
fi
check_local_expiry && exit 0
exit 1
