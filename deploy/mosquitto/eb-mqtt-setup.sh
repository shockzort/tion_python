#!/bin/sh
# Учётки брокера датчиков из /opt/easy-breezy/.env (вызывает provision.yml).
#
# Идемпотентно: недостающие пароли генерируются и дописываются в .env,
# существующие не меняются (датчики уже настроены на них). passwd
# пересобирается только при изменении паролей; хэши — mosquitto_passwd.
#
#   EB_MQTT_URL=mqtt://easy-breezy:<пароль>@127.0.0.1:1883   — сервис
#   EB_MQTT_DEVICE_PASSWORD=<пароль>                          — датчики (qingping)
set -eu

ROOT=${EB_ROOT:-/opt/easy-breezy}
ENV_FILE="$ROOT/.env"
CONF="$ROOT/mosquitto/config"
IMAGE=${EB_MOSQUITTO_IMAGE:-eclipse-mosquitto:2.0.20}

gen() { tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24; }
get() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; }

changed=0
url=$(get EB_MQTT_URL)
if [ -z "$url" ]; then
    url="mqtt://easy-breezy:$(gen)@127.0.0.1:1883"
    printf '\nEB_MQTT_URL=%s\n' "$url" >>"$ENV_FILE"
    changed=1
fi
device=$(get EB_MQTT_DEVICE_PASSWORD)
if [ -z "$device" ]; then
    device=$(gen)
    printf 'EB_MQTT_DEVICE_PASSWORD=%s\n' "$device" >>"$ENV_FILE"
    changed=1
fi
service=$(printf '%s' "$url" | sed -n 's|^mqtt://easy-breezy:\([^@]*\)@.*|\1|p')
if [ -z "$service" ]; then
    echo "EB_MQTT_URL должен быть вида mqtt://easy-breezy:<пароль>@127.0.0.1:1883" >&2
    exit 1
fi

stamp=$(printf '%s:%s' "$service" "$device" | sha256sum | cut -c1-64)
if [ -f "$CONF/passwd" ] && [ "$(cat "$CONF/.passwd.sha256" 2>/dev/null)" = "$stamp" ]; then
    echo "unchanged"
    exit 0
fi
docker run --rm -v "$CONF:/c" "$IMAGE" sh -c \
    "rm -f /c/passwd && touch /c/passwd \
     && mosquitto_passwd -b /c/passwd qingping '$device' \
     && mosquitto_passwd -b /c/passwd easy-breezy '$service'"
chown 1883:1883 "$CONF/passwd"
chmod 0600 "$CONF/passwd"
printf '%s' "$stamp" >"$CONF/.passwd.sha256"
chmod 0600 "$CONF/.passwd.sha256"
echo "changed"
[ "$changed" = 1 ] && echo "env-updated"
exit 0
