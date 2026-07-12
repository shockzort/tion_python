"""Уведомления systemd (Type=notify, WatchdogSec) без внешних зависимостей.

Вне systemd (dev, docker без NOTIFY_SOCKET) все вызовы — тихий no-op.
"""

from __future__ import annotations

import os
import socket

READY = "READY=1"
WATCHDOG = "WATCHDOG=1"
STOPPING = "STOPPING=1"


def sd_notify(state: str) -> bool:
    """Шлёт датаграмму в NOTIFY_SOCKET; False — сокета нет или недоступен."""
    path = os.environ.get("NOTIFY_SOCKET")
    if not path:
        return False
    if path.startswith("@"):  # abstract namespace
        path = "\0" + path[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(path)
            sock.send(state.encode())
        return True
    except OSError:
        return False
