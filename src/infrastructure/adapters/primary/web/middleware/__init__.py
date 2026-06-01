"""
Web middleware module.

This module provides centralized middleware components for the FastAPI application,
including exception handling, request logging, and security middleware.
"""

from src.infrastructure.adapters.primary.web.middleware.api_logging import (
    install_api_access_log_middleware,
)
from src.infrastructure.adapters.primary.web.middleware.exception_handlers import (
    configure_exception_handlers,
)

__all__ = [
    "configure_exception_handlers",
    "install_api_access_log_middleware",
]
