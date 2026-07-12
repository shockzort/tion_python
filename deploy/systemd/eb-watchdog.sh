#!/bin/sh
# Health-watchdog Easy Breezy: серия провалов /api/system/health → рестарт
# сервиса (docker compose пересоздаст контейнер). Вызывается таймером
# easy-breezy-watchdog.timer раз в 30 с; порог 4 ≈ 2 минуты тишины —
# симметрично прежнему systemd WatchdogSec. Зависший event loop не отвечает
# на HTTP, так что кейс «процесс жив, но мёртв» тоже ловится.
set -eu

URL="http://127.0.0.1:8000/api/system/health"
STATE=/run/easy-breezy-watchdog.fails
THRESHOLD=4

if curl -fsS -m 10 "$URL" >/dev/null 2>&1; then
    rm -f "$STATE"
    exit 0
fi

fails=$(($(cat "$STATE" 2>/dev/null || echo 0) + 1))
echo "$fails" >"$STATE"
logger -t eb-watchdog "health-чек провален ($fails/$THRESHOLD)"

if [ "$fails" -ge "$THRESHOLD" ]; then
    rm -f "$STATE"
    logger -t eb-watchdog "серия провалов — перезапуск easy-breezy"
    systemctl restart easy-breezy.service
fi
