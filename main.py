"""Entry point for the Tion breezer control service."""
from __future__ import annotations

import logging
import os
import signal
import sys

import uvicorn
from dotenv import load_dotenv

# Load environment variables before any other imports
load_dotenv()


def setup_logging() -> None:
    """Configure JSON-format logging with rotation.

    Sets up root logger with structured output. Uses python-json-logger
    if available, otherwise falls back to standard formatting.
    """
    log_level = logging.DEBUG if os.getenv("DEBUG", "false").lower() == "true" else logging.INFO
    log_dir = os.getenv("LOG_DIR", "")

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_dir:
        import os as _os

        _os.makedirs(log_dir, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        app_handler = RotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
        )
        ble_handler = RotatingFileHandler(
            os.path.join(log_dir, "ble.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        )
        handlers.append(app_handler)

        # BLE-specific handler
        ble_logger = logging.getLogger("tion_btle")
        ble_logger.addHandler(ble_handler)
        ble_logger.setLevel(logging.DEBUG)

    try:
        from pythonjsonlogger import jsonlogger  # type: ignore[import-untyped]

        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s"
        )
    except ImportError:
        formatter = logging.Formatter(  # type: ignore[assignment]
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=log_level, handlers=handlers)


def main() -> None:
    """Run the Tion service.

    Starts uvicorn server with the FastAPI application.
    Handles SIGTERM and SIGINT for graceful shutdown.
    """
    setup_logging()

    logger = logging.getLogger(__name__)
    logger.info("Starting Tion Breezer Control Service")

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("DEBUG", "false").lower() == "true"

    # Import here after load_dotenv() has run
    from api.app import app

    # Register signal handlers for graceful shutdown
    def _handle_signal(signum: int, frame: object) -> None:
        logger.info("Received signal %d, shutting down...", signum)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="debug" if debug else "info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
