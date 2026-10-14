import json
import logging
import sys
from logging.handlers import RotatingFileHandler

from cortex.config import BASE_DIR, settings

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "module": record.module,
                "message": record.getMessage(),
            },
            ensure_ascii=False,
        )


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    root.handlers.clear()

    formatter = JsonFormatter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(LOG_DIR / "cortex.log", maxBytes=10_000_000, backupCount=5)
    file_handler.setFormatter(formatter)

    root.addHandler(console)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"cortex.{name}")
