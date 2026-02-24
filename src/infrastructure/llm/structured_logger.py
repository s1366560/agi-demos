"""
Structured Logging for LLM Operations.

Provides structured logging utilities for LLM calls with support for:
- Consistent log formatting across all LLM operations
- Rich context capture (provider, model, tokens, latency)
- Integration with observability platforms (Langfuse, Prometheus)
- Performance metrics tracking

Usage:
    from src.infrastructure.llm.structured_logger import get_llm_logger
    
    logger = get_llm_logger()
    logger.log_call_start(request_id="req-123", provider="dashscope", model="qwen-max")
    logger.log_call_end(request_id="req-123", tokens=150, latency_ms=450)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LLMMetrics:
    """
    Metrics for a single LLM call.
    
    Captures all relevant information for observability and cost tracking.
    """
    
    request_id: str
    provider: str
    model: str
    operation: str = "completion"  # completion, embedding, rerank, stream
    
    # Timing
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    latency_ms: float | None = None
    
    # Token usage
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    
    # Request metadata
    tenant_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    
    # Response metadata
    finish_reason: str | None = None
    tool_calls: int = 0
    has_error: bool = False
    error_type: str | None = None
    error_message: str | None = None
    
    # Cost tracking (if available)
    estimated_cost: float | None = None
    currency: str = "USD"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "request_id": self.request_id,
            "provider": self.provider,
            "model": self.model,
            "operation": self.operation,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "finish_reason": self.finish_reason,
            "tool_calls": self.tool_calls,
            "has_error": self.has_error,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "estimated_cost": self.estimated_cost,
            "currency": self.currency,
        }


class StructuredLLMLogger:
    """
    Structured logger for LLM operations.
    
    Provides consistent logging across all LLM calls with support
    for metrics tracking and observability integration.
    
    Example:
        logger = StructuredLLMLogger()
        
        # Start tracking
        request_id = logger.log_call_start(
            provider="dashscope",
            model="qwen-max",
            tenant_id="tenant-1",
        )
        
        try:
            # ... make LLM call ...
            logger.log_call_end(
                request_id=request_id,
                input_tokens=100,
                output_tokens=50,
                latency_ms=450,
            )
        except Exception as e:
            logger.log_call_error(
                request_id=request_id,
                error=e,
            )
    """
    
    def __init__(self, base_logger: logging.Logger | None = None) -> None:
        """
        Initialize structured LLM logger.
        
        Args:
            base_logger: Base logger instance (uses 'llm' logger if None)
        """
        self._logger = base_logger or logging.getLogger("llm")
        self._active_calls: dict[str, LLMMetrics] = {}
    
    def _get_extra(self, metrics: LLMMetrics) -> dict[str, Any]:
        """
        Get extra fields for structured logging.
        
        Args:
            metrics: LLM metrics
        
        Returns:
            Dictionary of extra fields
        """
        return {
            "llm_request_id": metrics.request_id,
            "llm_provider": metrics.provider,
            "llm_model": metrics.model,
            "llm_operation": metrics.operation,
            **metrics.to_dict(),
        }
    
    def log_call_start(
        self,
        provider: str,
        model: str,
        operation: str = "completion",
        request_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Log start of LLM call.
        
        Args:
            provider: LLM provider name
            model: Model name
            operation: Operation type (completion, embedding, rerank, stream)
            request_id: Optional request ID (generated if not provided)
            tenant_id: Tenant identifier
            user_id: User identifier
            project_id: Project identifier
            conversation_id: Conversation identifier
            **kwargs: Additional metadata
            
        Returns:
            Request ID for tracking
        """
        import uuid
        
        request_id = request_id or str(uuid.uuid4())
        
        metrics = LLMMetrics(
            request_id=request_id,
            provider=provider,
            model=model,
            operation=operation,
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            conversation_id=conversation_id,
        )
        
        # Store for later completion
        self._active_calls[request_id] = metrics
        
        self._logger.info(
            f"LLM call started: {provider}/{model} ({operation})",
            extra=self._get_extra(metrics),
        )
        
        return request_id
    
    def log_call_end(
        self,
        request_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        reasoning_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        latency_ms: float | None = None,
        finish_reason: str | None = None,
        tool_calls: int = 0,
        estimated_cost: float | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Log end of LLM call.
        
        Args:
            request_id: Request ID from log_call_start
            input_tokens: Input token count
            output_tokens: Output token count
            total_tokens: Total token count
            reasoning_tokens: Reasoning token count
            cache_read_tokens: Cache read token count
            cache_write_tokens: Cache write token count
            latency_ms: Call latency in milliseconds
            finish_reason: Finish reason from LLM
            tool_calls: Number of tool calls
            estimated_cost: Estimated cost in USD
            **kwargs: Additional metadata
        """
        metrics = self._active_calls.get(request_id)
        
        if metrics is None:
            self._logger.warning(f"LLM call end without start: {request_id}")
            return
        
        # Update metrics
        metrics.input_tokens = input_tokens
        metrics.output_tokens = output_tokens
        metrics.total_tokens = total_tokens
        metrics.reasoning_tokens = reasoning_tokens
        metrics.cache_read_tokens = cache_read_tokens
        metrics.cache_write_tokens = cache_write_tokens
        metrics.latency_ms = latency_ms
        metrics.finish_reason = finish_reason
        metrics.tool_calls = tool_calls
        metrics.estimated_cost = estimated_cost
        metrics.end_time = time.time()
        
        # Calculate latency if not provided
        if latency_ms is None:
            metrics.latency_ms = (metrics.end_time - metrics.start_time) * 1000
        
        # Remove from active calls
        del self._active_calls[request_id]
        
        # Log with level based on finish reason
        if finish_reason == "error":
            level = logging.WARNING
        else:
            level = logging.INFO
        
        self._logger.log(
            level,
            f"LLM call completed: {metrics.provider}/{metrics.model} "
            f"(tokens={total_tokens}, latency={metrics.latency_ms:.0f}ms)",
            extra=self._get_extra(metrics),
        )
    
    def log_call_error(
        self,
        request_id: str,
        error: Exception,
        input_tokens: int = 0,
        **kwargs: Any,
    ) -> None:
        """
        Log LLM call error.
        
        Args:
            request_id: Request ID from log_call_start
            error: Exception that occurred
            input_tokens: Input token count (if known)
            **kwargs: Additional metadata
        """
        metrics = self._active_calls.get(request_id)
        
        if metrics is None:
            self._logger.error(
                f"LLM call error without start: {request_id}, error={error}"
            )
            return
        
        # Update metrics
        metrics.has_error = True
        metrics.error_type = type(error).__name__
        metrics.error_message = str(error)
        metrics.input_tokens = input_tokens
        metrics.end_time = time.time()
        metrics.latency_ms = (metrics.end_time - metrics.start_time) * 1000
        
        # Remove from active calls
        del self._active_calls[request_id]
        
        self._logger.error(
            f"LLM call failed: {metrics.provider}/{metrics.model} "
            f"({metrics.error_type}: {metrics.error_message})",
            extra=self._get_extra(metrics),
        )
    
    def log_stream_event(
        self,
        request_id: str,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> None:
        """
        Log streaming event.
        
        Args:
            request_id: Request ID from log_call_start
            event_type: Type of stream event
            event_data: Event data
        """
        metrics = self._active_calls.get(request_id)
        
        if metrics is None:
            return
        
        extra = self._get_extra(metrics)
        extra["stream_event_type"] = event_type
        if event_data:
            extra["stream_event_data"] = event_data
        
        self._logger.debug(
            f"Stream event: {event_type}",
            extra=extra,
        )
    
    def cleanup_stale_calls(self, max_age_seconds: float = 300) -> int:
        """
        Clean up stale active calls.
        
        Args:
            max_age_seconds: Maximum age of active calls
            
        Returns:
            Number of cleaned up calls
        """
        current_time = time.time()
        stale_requests = []
        
        for request_id, metrics in self._active_calls.items():
            age = current_time - metrics.start_time
            if age > max_age_seconds:
                stale_requests.append(request_id)
        
        for request_id in stale_requests:
            metrics = self._active_calls[request_id]
            self._logger.warning(
                f"Cleaning up stale LLM call: {request_id} "
                f"(age={current_time - metrics.start_time:.0f}s)"
            )
            del self._active_calls[request_id]
        
        return len(stale_requests)


# Global logger instance
_global_logger: StructuredLLMLogger | None = None


def get_llm_logger() -> StructuredLLMLogger:
    """
    Get or create global structured LLM logger.
    
    Returns:
        Global StructuredLLMLogger instance
    """
    global _global_logger
    if _global_logger is None:
        _global_logger = StructuredLLMLogger()
    return _global_logger


def log_llm_call(
    provider: str,
    model: str,
    operation: str = "completion",
    **kwargs: Any,
) -> tuple[str, StructuredLLMLogger]:
    """
    Convenience function to log LLM call start.
    
    Args:
        provider: LLM provider name
        model: Model name
        operation: Operation type
        **kwargs: Additional metadata
        
    Returns:
        Tuple of (request_id, logger)
    """
    logger_instance = get_llm_logger()
    request_id = logger_instance.log_call_start(
        provider=provider,
        model=model,
        operation=operation,
        **kwargs,
    )
    return request_id, logger_instance
