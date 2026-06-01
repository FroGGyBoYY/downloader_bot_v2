import logging
import sys
from logging.handlers import RotatingFileHandler

from app.config import Settings


def setup_logging(settings: Settings) -> None:
    logs_dir = settings.base_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, settings.log_level, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Чтобы при перезапуске не плодились одинаковые handlers
    root_logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s:%(lineno)d | %(message)s"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    bot_file_handler = RotatingFileHandler(
        logs_dir / "bot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    bot_file_handler.setLevel(level)
    bot_file_handler.setFormatter(formatter)

    error_file_handler = RotatingFileHandler(
        logs_dir / "errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(bot_file_handler)
    root_logger.addHandler(error_file_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("telegram.ext").setLevel(logging.INFO)
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)