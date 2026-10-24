#!/bin/sh
# Ночной бэкап всей инсталляции на VPS (запускает easy-breezy-backup.timer).
#
# Архив: свежий снапшот БД (его в 03:30 делает сам сервис), .env и прочие
# конфиги /opt/easy-breezy, ключи пушей, TLS, учётки брокера, ключ cert-sync
# и сопряжения BlueZ — всё, что нужно, чтобы поднять NUC с нуля без
# повторного сопряжения бризеров. Шифруется age (ключ — backup/age.key на
# NUC и копия у владельца), хранится EB_BACKUP_KEEP последних копий локально
# в backups/offsite и зеркалится на VPS. ssh-ключ на той стороне умеет ровно
# одно — rrsync -wo в свой каталог (deploy/ansible/README.md, «Бэкап на VPS»).
#
# Сбой виден в systemctl --failed и journalctl -t eb-backup.
set -eu

: "${EB_ROOT:=/opt/easy-breezy}"
: "${EB_BACKUP_SSH_HOST:?задаётся в backup-offsite.env (make provision)}"
: "${EB_BACKUP_SSH_PORT:=22}"
: "${EB_BACKUP_SSH_KEY:=/root/.ssh/eb-backup}"
: "${EB_BACKUP_KEEP:=7}"

KEY="$EB_ROOT/backup/age.key"
OUTBOX="$EB_ROOT/backups/offsite"
SNAPSHOT_MAX_AGE=$((30 * 3600))

log() { logger -t eb-backup "$*"; echo "$*"; }

umask 077
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

[ -s "$KEY" ] || { log "нет ключа шифрования $KEY — прогоните provision"; exit 1; }
recipient=$(age-keygen -y "$KEY")

# Снапшот БД согласован (VACUUM INTO в сервисе); живой файл с WAL не берём.
snapshot=$(ls -1t "$EB_ROOT"/data/backups/easy_breezy-*.db.gz 2>/dev/null | head -n 1 || true)
[ -n "$snapshot" ] || { log "нет снапшота БД в $EB_ROOT/data/backups"; exit 1; }
stale=0
if [ $(($(date +%s) - $(stat -c %Y "$snapshot"))) -gt "$SNAPSHOT_MAX_AGE" ]; then
    stale=1   # конфиги всё равно увозим, но прогон помечаем сбойным
fi

# Пути от корня; чего нет на этом хосте — пропускаем.
paths=""
for p in \
    "$EB_ROOT/.env" "$EB_ROOT/deploy.env" "$EB_ROOT/docker-compose.yml" \
    "$EB_ROOT/cert-sync.env" "$EB_ROOT/backup-offsite.env" "$EB_ROOT/frpc.toml" \
    "$EB_ROOT/nginx" "$EB_ROOT/tls" "$EB_ROOT/mosquitto/config" \
    "$EB_ROOT/data/vapid_private.pem" "$snapshot" \
    /var/lib/bluetooth /root/.ssh/eb-cert /root/.ssh/eb-cert.pub; do
    if [ -e "$p" ]; then paths="$paths ${p#/}"; fi
done

name="easy-breezy-$(hostname -s)-$(date +%Y%m%d-%H%M%S).tar.gz.age"
mkdir -p "$OUTBOX"
# shellcheck disable=SC2086  # список путей без пробелов, разбиение намеренное
tar -czf - -C / $paths | age -r "$recipient" -o "$tmp/$name"

# Архив, который не расшифровывается, хуже отсутствующего — проверяем сразу.
age -d -i "$KEY" "$tmp/$name" | tar -tzf - >/dev/null
mv "$tmp/$name" "$OUTBOX/$name"

# Ротация по имени (в нём дата) — mtime переживает копирование хуже.
ls -1 "$OUTBOX"/easy-breezy-*.tar.gz.age | sort -r | tail -n +$((EB_BACKUP_KEEP + 1)) \
    | while read -r old; do rm -f "$old"; done

if ! rsync -a --delete --timeout=120 \
        -e "ssh -i $EB_BACKUP_SSH_KEY -p $EB_BACKUP_SSH_PORT -o BatchMode=yes -o ConnectTimeout=20" \
        "$OUTBOX/" "$EB_BACKUP_SSH_HOST:" 2>"$tmp/rsync.err"; then
    log "VPS недоступен, копия только локально: $(tr '\n' ' ' <"$tmp/rsync.err")"
    exit 1
fi

size=$(du -h "$OUTBOX/$name" | cut -f1)
if [ "$stale" = 1 ]; then
    log "увезён $name ($size), но снапшот БД старше 30 ч: $(basename "$snapshot")"
    exit 1
fi
log "увезён $name ($size), на VPS $(ls -1 "$OUTBOX" | wc -l) копий"
