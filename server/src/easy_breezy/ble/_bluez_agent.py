"""JustWorks-агент BlueZ для сопряжения (org.bluez.Agent1).

Модуль сознательно БЕЗ ``from __future__ import annotations``: dbus-fast
читает сигнатуры D-Bus из сырых аннотаций методов (``'o'``, ``'u'``, ``'s'``),
а postponed evaluation превращает их в неразбираемые строки. Стиль аннотаций
здесь диктует dbus-fast, а не конвенции проекта.
"""

import structlog
from dbus_fast.service import ServiceInterface, method

log = structlog.get_logger("easy_breezy.ble")

AGENT_PATH = "/easy_breezy/agent"
AGENT_CAPABILITY = "NoInputNoOutput"


class JustWorksAgent(ServiceInterface):
    """Минимальный агент BlueZ: одобряет пейринг без взаимодействия.

    Регистрируется транспортом на время сопряжения — без агента и
    ``Pairable: yes`` bluetoothd заваливает SMP (полевой факт: сопряжение
    падало с ``AuthenticationFailed``, спека §1.7).
    """

    def __init__(self) -> None:
        super().__init__("org.bluez.Agent1")

    @method()
    def Release(self):  # type: ignore[no-untyped-def]
        log.debug("pairing_agent_released")

    @method()
    def Cancel(self):  # type: ignore[no-untyped-def]
        log.debug("pairing_agent_cancelled")

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):  # type: ignore[no-untyped-def,name-defined]  # noqa: F821
        log.debug("pairing_confirm_auto", device=str(device))

    @method()
    def RequestAuthorization(self, device: "o"):  # type: ignore[no-untyped-def,name-defined]  # noqa: F821
        log.debug("pairing_authorize_auto", device=str(device))

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):  # type: ignore[no-untyped-def,name-defined]  # noqa: F821
        log.debug("pairing_service_auto", device=str(device), uuid=str(uuid))
