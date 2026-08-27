from __future__ import annotations

import logging
import logging.config


_REDACTED = "[REDACTED SENSITIVE LOG MESSAGE]"
_SENSITIVE_SUBSTRINGS = ("Bearer ", "TREND_VISION_ONE_API_TOKEN", "Authorization", "ANTHROPIC_API_KEY", "api_key")


class SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        if any(s in msg for s in _SENSITIVE_SUBSTRINGS):
            record.msg = _REDACTED
            record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"secret": {"()": SecretFilter}},
            "formatters": {
                "default": {
                    "format": "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["secret"],
                }
            },
            "root": {"level": level, "handlers": ["console"]},
        }
    )
