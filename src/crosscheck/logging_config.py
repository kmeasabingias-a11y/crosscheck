"""Logging setup for CrossCheck, built on Loguru.

A single :func:`configure_logging` call, made once at startup, replaces Loguru's
default handler with one whose level comes from the settings panel (config.py).
Structured/JSON output and per-LLM-call tracing are deliberately later-phase
concerns and are not pulled forward here.
"""

import sys

from loguru import logger

from crosscheck.config import Settings

_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DDTHH:mm:ss}</green> "
    "<level>{level: <8}</level> "
    "<cyan>{name}</cyan> | <level>{message}</level>"
)


def configure_logging(settings: Settings) -> None:
    """Configure Loguru from settings. Call once at application startup.

    Removes Loguru's default handler and installs a single stderr sink whose
    minimum level is ``settings.log_level``. Idempotent: repeated calls reset to
    one handler rather than stacking duplicates.

    Args:
        settings: The application settings; ``log_level`` sets the sink threshold.
    """
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level.upper(),
        format=_CONSOLE_FORMAT,
        backtrace=False,
        diagnose=False,
    )
