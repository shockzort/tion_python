"""Репозитории: тонкие обёртки запросов; транзакция — у вызывающего.

Каждый метод предполагает активную сессию ``Database.session()``; репозитории
не делают commit — границы транзакций задаёт владелец операции.
"""

from easy_breezy.storage.repos.auth import ApiTokenRepo, SessionRepo, UserRepo
from easy_breezy.storage.repos.automation import ScenarioRepo, ScheduleRepo
from easy_breezy.storage.repos.commands import CommandRepo
from easy_breezy.storage.repos.devices import DeviceRepo, RoomRepo
from easy_breezy.storage.repos.groups import GroupRepo
from easy_breezy.storage.repos.settings import SettingsRepo
from easy_breezy.storage.repos.telemetry import TelemetryPoint, TelemetryRepo

__all__ = [
    "ApiTokenRepo",
    "CommandRepo",
    "DeviceRepo",
    "GroupRepo",
    "RoomRepo",
    "ScenarioRepo",
    "ScheduleRepo",
    "SessionRepo",
    "SettingsRepo",
    "TelemetryPoint",
    "TelemetryRepo",
    "UserRepo",
]
