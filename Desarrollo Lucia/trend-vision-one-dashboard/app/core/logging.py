from __future__ import annotations

import logging
from logging.config import dictConfig


class SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = str(record.getMessage())
        for marker in ("Bearer ", "TREND_VISION_ONE_API_TOKEN", "Authorization"):
            if marker in message:
                record.msg = "[REDACTED SENSITIVE LOG MESSAGE]"
                record.args = ()
                break
        return True


def configure_logging(level: str = "INFO") -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"secret_filter": {"()": SecretFilter}},
            "formatters": {
                "standard": {
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                }
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "filters": ["secret_filter"],
                }
            },
            "root": {"handlers": ["default"], "level": level},
        }
    )

