"""Общие мелочи репозиториев."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, Result


def rowcount(result: Result[Any]) -> int:
    """Число затронутых строк DML.

    ``AsyncSession.execute`` типизирован как ``Result``, но для DML фактически
    возвращает ``CursorResult`` — сужаем тип явно.
    """
    return cast("CursorResult[Any]", result).rowcount
