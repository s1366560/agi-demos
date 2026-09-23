"""Failure diagnostics that never include transport values or exception messages."""

import logging
import traceback

logger = logging.getLogger(__name__)


def log_marketplace_failure(error: Exception) -> None:
    frames = [
        (frame.filename, frame.name, frame.lineno)
        for frame in traceback.extract_tb(error.__traceback__)
    ]
    logger.warning("Marketplace operation failed type=%s frames=%s", type(error).__name__, frames)
