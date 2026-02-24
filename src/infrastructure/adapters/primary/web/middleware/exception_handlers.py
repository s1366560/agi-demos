"""
Centralized exception handlers for FastAPI application.

This module provides a unified approach to handling domain exceptions,
mapping them to appropriate HTTP responses with consistent error format.

Usage:
    from src.infrastructure.adapters.primary.web.middleware import configure_exception_handlers

    app = FastAPI()
    configure_exception_handlers(app)
"""

import logging
import traceback
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Domain exceptions
from src.domain.exceptions.repository_exceptions import (
    ConnectionError as RepositoryConnectionError,
    DuplicateEntityError,
    EntityNotFoundError,
    OptimisticLockError,
    RepositoryError,
    TransactionError,
)
from src.domain.llm_providers.llm_types import RateLimitError as LLMRateLimitError
from src.domain.llm_providers.models import NoActiveProviderError
from src.domain.model.sandbox.exceptions import (
    SandboxConnectionError,
    SandboxError,
    SandboxHealthCheckError,
    SandboxResourceError,
    SandboxStateTransitionError,
    SandboxTimeoutError,
    SandboxValidationError,
)
from src.domain.ports.services.distributed_lock_port import (
    LockAcquisitionError,
    LockError,
    LockReleaseError,
)
from src.domain.shared_kernel import DomainException

logger = logging.getLogger(__name__)


class ErrorResponse:
    """Standard error response format."""

    def __init__(
        self,
        status_code: int,
        error_type: str,
        message: str,
        error_id: str | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        self.status_code = status_code
        self.error_type = error_type
        self.message = message
        self.error_id = error_id or str(uuid.uuid4())
        self.details = details or {}
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON response."""
        response = {
            "error": {
                "type": self.error_type,
                "message": self.message,
                "error_id": self.error_id,
                "retryable": self.retryable,
            }
        }
        if self.details:
            response["error"]["details"] = self.details
        return response

    def to_response(self) -> JSONResponse:
        """Create FastAPI JSONResponse."""
        return JSONResponse(
            status_code=self.status_code,
            content=self.to_dict(),
        )


# ==============================================================================
# Repository Exception Handlers
# ==============================================================================


async def entity_not_found_handler(request: Request, exc: EntityNotFoundError) -> JSONResponse:
    """Handle entity not found errors - 404."""
    error_id = str(uuid.uuid4())
    logger.warning(
        "Entity not found: %s[%s] - error_id=%s, path=%s",
        exc.entity_type,
        exc.entity_id,
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=404,
        error_type="EntityNotFound",
        message=str(exc),
        error_id=error_id,
        details={"entity_type": exc.entity_type, "entity_id": exc.entity_id},
    ).to_response()


async def duplicate_entity_handler(request: Request, exc: DuplicateEntityError) -> JSONResponse:
    """Handle duplicate entity errors - 409 Conflict."""
    error_id = str(uuid.uuid4())
    logger.warning(
        "Duplicate entity: %s - error_id=%s, path=%s",
        exc.message,
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=409,
        error_type="DuplicateEntity",
        message=str(exc),
        error_id=error_id,
        details=exc.details,
    ).to_response()


async def optimistic_lock_handler(request: Request, exc: OptimisticLockError) -> JSONResponse:
    """Handle optimistic lock errors - 409 Conflict."""
    error_id = str(uuid.uuid4())
    logger.warning(
        "Optimistic lock conflict: %s - error_id=%s, path=%s",
        exc.message,
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=409,
        error_type="ConcurrentModification",
        message="The resource was modified by another request. Please retry.",
        error_id=error_id,
        retryable=True,
    ).to_response()


async def transaction_error_handler(request: Request, exc: TransactionError) -> JSONResponse:
    """Handle transaction errors - 500."""
    error_id = str(uuid.uuid4())
    logger.error(
        "Transaction error: %s - error_id=%s, path=%s",
        exc.message,
        error_id,
        request.url.path,
        exc_info=True,
    )
    return ErrorResponse(
        status_code=500,
        error_type="TransactionError",
        message="A database transaction error occurred. Please try again.",
        error_id=error_id,
        retryable=True,
    ).to_response()


async def repository_connection_handler(
    request: Request, exc: RepositoryConnectionError
) -> JSONResponse:
    """Handle repository connection errors - 503 Service Unavailable."""
    error_id = str(uuid.uuid4())
    logger.error(
        "Database connection error: %s - error_id=%s, path=%s",
        exc.message,
        error_id,
        request.url.path,
        exc_info=True,
    )
    return ErrorResponse(
        status_code=503,
        error_type="ServiceUnavailable",
        message="Database service is temporarily unavailable. Please try again later.",
        error_id=error_id,
        retryable=True,
    ).to_response()


async def repository_error_handler(request: Request, exc: RepositoryError) -> JSONResponse:
    """Handle generic repository errors - 500."""
    error_id = str(uuid.uuid4())
    logger.error(
        "Repository error: %s - error_id=%s, path=%s",
        exc.message,
        error_id,
        request.url.path,
        exc_info=True,
    )
    return ErrorResponse(
        status_code=500,
        error_type="RepositoryError",
        message="A data access error occurred. Please try again.",
        error_id=error_id,
        retryable=True,
    ).to_response()


# ==============================================================================
# Sandbox Exception Handlers
# ==============================================================================


async def sandbox_not_found_handler(request: Request, exc: SandboxError) -> JSONResponse:
    """Handle sandbox not found - 404."""
    error_id = str(uuid.uuid4())
    logger.warning(
        "Sandbox error: %s - error_id=%s, path=%s",
        exc.message,
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=404,
        error_type="SandboxNotFound",
        message=exc.message,
        error_id=error_id,
        details=exc.to_dict() if hasattr(exc, "to_dict") else {},
    ).to_response()


async def sandbox_connection_handler(request: Request, exc: SandboxConnectionError) -> JSONResponse:
    """Handle sandbox connection errors - 503."""
    error_id = str(uuid.uuid4())
    logger.error(
        "Sandbox connection error: %s - error_id=%s, path=%s",
        exc.message,
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=503,
        error_type="SandboxConnectionError",
        message=exc.message,
        error_id=error_id,
        details={"endpoint": exc.endpoint} if hasattr(exc, "endpoint") else {},
        retryable=getattr(exc, "retryable", True),
    ).to_response()


async def sandbox_timeout_handler(request: Request, exc: SandboxTimeoutError) -> JSONResponse:
    """Handle sandbox timeout - 504 Gateway Timeout."""
    error_id = str(uuid.uuid4())
    logger.warning(
        "Sandbox timeout: %s - error_id=%s, path=%s",
        exc.message,
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=504,
        error_type="SandboxTimeout",
        message=exc.message,
        error_id=error_id,
        details={"timeout_seconds": exc.timeout_seconds} if exc.timeout_seconds else {},
        retryable=True,
    ).to_response()


async def sandbox_resource_handler(request: Request, exc: SandboxResourceError) -> JSONResponse:
    """Handle sandbox resource exhaustion - 503."""
    error_id = str(uuid.uuid4())
    logger.warning(
        "Sandbox resource error: %s - error_id=%s, path=%s",
        exc.message,
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=503,
        error_type="SandboxResourceExhausted",
        message=exc.message,
        error_id=error_id,
        details={"resource_type": exc.resource_type, "available": exc.available},
        retryable=False,
    ).to_response()


async def sandbox_validation_handler(request: Request, exc: SandboxValidationError) -> JSONResponse:
    """Handle sandbox validation errors - 400 Bad Request."""
    error_id = str(uuid.uuid4())
    logger.warning(
        "Sandbox validation error: %s - error_id=%s, path=%s",
        exc.message,
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=400,
        error_type="SandboxValidationError",
        message=exc.message,
        error_id=error_id,
        details={"field": exc.field, "value": str(exc.value)} if exc.field else {},
        retryable=False,
    ).to_response()


async def sandbox_state_transition_handler(
    request: Request, exc: SandboxStateTransitionError
) -> JSONResponse:
    """Handle invalid sandbox state transitions - 409 Conflict."""
    error_id = str(uuid.uuid4())
    logger.warning(
        "Sandbox state transition error: %s -> %s - error_id=%s, path=%s",
        exc.current_state,
        exc.target_state,
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=409,
        error_type="InvalidStateTransition",
        message=exc.message,
        error_id=error_id,
        details={
            "current_state": exc.current_state,
            "target_state": exc.target_state,
        },
        retryable=False,
    ).to_response()


async def sandbox_health_check_handler(
    request: Request, exc: SandboxHealthCheckError
) -> JSONResponse:
    """Handle sandbox health check failures - 503."""
    error_id = str(uuid.uuid4())
    logger.warning(
        "Sandbox health check failed: %s - error_id=%s, path=%s",
        exc.message,
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=503,
        error_type="SandboxHealthCheckFailed",
        message=exc.message,
        error_id=error_id,
        details={"health_check_type": exc.health_check_type} if exc.health_check_type else {},
        retryable=True,
    ).to_response()


async def sandbox_error_handler(request: Request, exc: SandboxError) -> JSONResponse:
    """Handle generic sandbox errors - 500."""
    error_id = str(uuid.uuid4())
    logger.error(
        "Sandbox error: %s - error_id=%s, path=%s",
        exc.message,
        error_id,
        request.url.path,
        exc_info=True,
    )
    return ErrorResponse(
        status_code=500,
        error_type="SandboxError",
        message=exc.message,
        error_id=error_id,
        details=exc.to_dict() if hasattr(exc, "to_dict") else {},
        retryable=getattr(exc, "retryable", False),
    ).to_response()


# ==============================================================================
# LLM/Provider Exception Handlers
# ==============================================================================


async def llm_rate_limit_handler(request: Request, exc: LLMRateLimitError) -> JSONResponse:
    """Handle LLM rate limit - 429 Too Many Requests."""
    error_id = str(uuid.uuid4())
    logger.warning(
        "LLM rate limit exceeded: %s - error_id=%s, path=%s",
        str(exc),
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=429,
        error_type="RateLimitExceeded",
        message="LLM rate limit exceeded. Please wait and try again.",
        error_id=error_id,
        retryable=True,
    ).to_response()


async def no_active_provider_handler(request: Request, exc: NoActiveProviderError) -> JSONResponse:
    """Handle no active LLM provider - 503."""
    error_id = str(uuid.uuid4())
    logger.error(
        "No active LLM provider: %s - error_id=%s, path=%s",
        str(exc),
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=503,
        error_type="NoActiveProvider",
        message="No active LLM provider available. Please configure a provider.",
        error_id=error_id,
    ).to_response()


# ==============================================================================
# Lock Exception Handlers
# ==============================================================================


async def lock_acquisition_handler(request: Request, exc: LockAcquisitionError) -> JSONResponse:
    """Handle lock acquisition failures - 409 Conflict."""
    error_id = str(uuid.uuid4())
    logger.warning(
        "Lock acquisition failed: %s - error_id=%s, path=%s",
        str(exc),
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=409,
        error_type="LockAcquisitionFailed",
        message="Resource is currently locked. Please try again later.",
        error_id=error_id,
        retryable=True,
    ).to_response()


async def lock_release_handler(request: Request, exc: LockReleaseError) -> JSONResponse:
    """Handle lock release failures - 500."""
    error_id = str(uuid.uuid4())
    logger.error(
        "Lock release failed: %s - error_id=%s, path=%s",
        str(exc),
        error_id,
        request.url.path,
        exc_info=True,
    )
    return ErrorResponse(
        status_code=500,
        error_type="LockReleaseFailed",
        message="Failed to release resource lock.",
        error_id=error_id,
    ).to_response()


async def lock_error_handler(request: Request, exc: LockError) -> JSONResponse:
    """Handle generic lock errors - 500."""
    error_id = str(uuid.uuid4())
    logger.error(
        "Lock error: %s - error_id=%s, path=%s",
        str(exc),
        error_id,
        request.url.path,
        exc_info=True,
    )
    return ErrorResponse(
        status_code=500,
        error_type="LockError",
        message="A lock operation failed.",
        error_id=error_id,
    ).to_response()


# ==============================================================================
# Generic Exception Handlers
# ==============================================================================


async def domain_exception_handler(request: Request, exc: DomainException) -> JSONResponse:
    """Handle generic domain exceptions - 400 Bad Request."""
    error_id = str(uuid.uuid4())
    logger.warning(
        "Domain exception: %s - error_id=%s, path=%s",
        str(exc),
        error_id,
        request.url.path,
    )
    return ErrorResponse(
        status_code=400,
        error_type="DomainError",
        message=str(exc),
        error_id=error_id,
    ).to_response()


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled exceptions - 500 Internal Server Error."""
    error_id = str(uuid.uuid4())
    logger.error(
        "Unhandled exception: %s - error_id=%s, path=%s\n%s",
        str(exc),
        error_id,
        request.url.path,
        traceback.format_exc(),
    )
    return ErrorResponse(
        status_code=500,
        error_type="InternalServerError",
        message="An unexpected error occurred. Please try again later.",
        error_id=error_id,
        retryable=True,
    ).to_response()


# ==============================================================================
# Configuration Function
# ==============================================================================


def configure_exception_handlers(app: FastAPI) -> None:
    """
    Configure all exception handlers for the FastAPI application.

    This function registers handlers for domain exceptions, mapping them
    to appropriate HTTP status codes with consistent error format.

    Args:
        app: The FastAPI application instance

    Example:
        app = FastAPI()
        configure_exception_handlers(app)
    """
    # Repository exceptions (order matters - specific before generic)
    app.add_exception_handler(EntityNotFoundError, entity_not_found_handler)
    app.add_exception_handler(DuplicateEntityError, duplicate_entity_handler)
    app.add_exception_handler(OptimisticLockError, optimistic_lock_handler)
    app.add_exception_handler(TransactionError, transaction_error_handler)
    app.add_exception_handler(RepositoryConnectionError, repository_connection_handler)
    app.add_exception_handler(RepositoryError, repository_error_handler)

    # Sandbox exceptions (specific before generic)
    app.add_exception_handler(SandboxConnectionError, sandbox_connection_handler)
    app.add_exception_handler(SandboxTimeoutError, sandbox_timeout_handler)
    app.add_exception_handler(SandboxResourceError, sandbox_resource_handler)
    app.add_exception_handler(SandboxValidationError, sandbox_validation_handler)
    app.add_exception_handler(SandboxStateTransitionError, sandbox_state_transition_handler)
    app.add_exception_handler(SandboxHealthCheckError, sandbox_health_check_handler)
    app.add_exception_handler(SandboxError, sandbox_error_handler)

    # LLM/Provider exceptions
    app.add_exception_handler(LLMRateLimitError, llm_rate_limit_handler)
    app.add_exception_handler(NoActiveProviderError, no_active_provider_handler)

    # Lock exceptions
    app.add_exception_handler(LockAcquisitionError, lock_acquisition_handler)
    app.add_exception_handler(LockReleaseError, lock_release_handler)
    app.add_exception_handler(LockError, lock_error_handler)

    # Generic domain exception (catch-all for domain errors)
    app.add_exception_handler(DomainException, domain_exception_handler)

    logger.info("Configured %d exception handlers", 21)
