"""Запуск сервиса: ``python -m easy_breezy``."""

from __future__ import annotations

import uvicorn

from easy_breezy.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "easy_breezy.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_config=None,  # логирование настраивает create_app
    )


if __name__ == "__main__":
    main()
