"""
Agent Container gRPC Server.

This module implements the gRPC server that runs inside each isolated
agent container (HOT tier). It provides:

- Initialize: Load agent with configuration
- Execute: Handle chat requests with streaming response
- Pause/Resume: Lifecycle control
- Shutdown: Graceful termination
- GetStatus: Status monitoring
- HealthCheck: Health monitoring

Usage:
    python -m src.infrastructure.agent.pool.container.server
"""

import asyncio
import logging
import os
import signal
import sys
import time
from collections.abc import AsyncIterator
from concurrent import futures
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# gRPC imports will be generated from proto
# For now, we'll use a simple HTTP/JSON-based approach as fallback

logger = logging.getLogger(__name__)


@dataclass
class AgentContainerConfig:
    """Container agent configuration."""

    instance_id: str = ""
    tenant_id: str = ""
    project_id: str = ""
    agent_mode: str = "chat"
    grpc_port: int = 50051
    health_port: int = 8080
    max_concurrent_requests: int = 50
    memory_limit_mb: int = 2048
    idle_timeout_seconds: int = 3600
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "AgentContainerConfig":
        """Create config from environment variables."""
        return cls(
            instance_id=os.environ.get("AGENT_INSTANCE_ID", ""),
            tenant_id=os.environ.get("AGENT_TENANT_ID", ""),
            project_id=os.environ.get("AGENT_PROJECT_ID", ""),
            agent_mode=os.environ.get("AGENT_MODE", "chat"),
            grpc_port=int(os.environ.get("GRPC_PORT", "50051")),
            health_port=int(os.environ.get("HEALTH_PORT", "8080")),
            max_concurrent_requests=int(os.environ.get("MAX_CONCURRENT_REQUESTS", "50")),
            memory_limit_mb=int(os.environ.get("MEMORY_LIMIT_MB", "2048")),
            idle_timeout_seconds=int(os.environ.get("IDLE_TIMEOUT_SECONDS", "3600")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )


@dataclass
class ExecutionMetrics:
    """Execution metrics tracking."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    total_tokens: int = 0
    total_cost: float = 0.0
    latencies: list = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests

    @property
    def p99_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]


class AgentContainerServer:
    """
    gRPC server for isolated agent container.

    This server runs inside each HOT tier container and handles
    all agent operations via gRPC.
    """

    def __init__(self, config: AgentContainerConfig) -> None:
        self.config = config
        self._agent: Any | None = None  # Will be ProjectReActAgent
        self._lifecycle_state = "created"
        self._is_initialized = False
        self._is_paused = False
        self._start_time: datetime | None = None
        self._last_request_time: datetime | None = None
        self._error_message: str | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._active_requests = 0
        self._metrics = ExecutionMetrics()
        self._shutdown_event = asyncio.Event()
        self._grpc_server: Any | None = None
        self._health_server: Any | None = None

    @property
    def uptime_seconds(self) -> int:
        if self._start_time is None:
            return 0
        return int((datetime.now(UTC) - self._start_time).total_seconds())

    @property
    def is_healthy(self) -> bool:
        """Check if agent is healthy."""
        if self._lifecycle_state == "error":
            return False
        return self._lifecycle_state in ("ready", "executing", "paused")

    async def start(self) -> None:
        """Start the gRPC server."""
        self._start_time = datetime.now(UTC)
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
        self._lifecycle_state = "initializing"

        logger.info(
            f"Starting Agent Container Server: instance_id={self.config.instance_id}, "
            f"grpc_port={self.config.grpc_port}"
        )

        # Start health check HTTP server
        await self._start_health_server()

        # Start gRPC server
        await self._start_grpc_server()

        # Initialize the agent
        await self._initialize_agent()

        logger.info("Agent Container Server started successfully")

    async def stop(self, graceful: bool = True) -> None:
        """Stop the server."""
        self._lifecycle_state = "shutting_down"
        logger.info(f"Stopping Agent Container Server (graceful={graceful})")

        if graceful:
            # Wait for active requests to complete
            timeout = 30
            start = time.time()
            while self._active_requests > 0 and (time.time() - start) < timeout:
                await asyncio.sleep(0.5)
                logger.info(f"Waiting for {self._active_requests} active requests...")

        # Stop servers
        if self._grpc_server:
            await self._stop_grpc_server()
        if self._health_server:
            await self._stop_health_server()

        # Cleanup agent
        if self._agent:
            try:
                await self._agent.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down agent: {e}")

        self._shutdown_event.set()
        logger.info("Agent Container Server stopped")

    async def _start_grpc_server(self) -> None:
        """Start the gRPC server."""
        try:
            # Try to import gRPC
            from grpc import aio

            # Create gRPC server
            self._grpc_server = aio.server(
                futures.ThreadPoolExecutor(max_workers=10),
                options=[
                    ("grpc.max_send_message_length", 100 * 1024 * 1024),  # 100MB
                    ("grpc.max_receive_message_length", 100 * 1024 * 1024),
                ],
            )

            # TODO: Add generated servicer when proto is compiled
            # agent_pool_pb2_grpc.add_AgentWorkerServiceServicer_to_server(
            #     AgentWorkerServicer(self), self._grpc_server
            # )

            # Add insecure port (in production, use TLS)
            self._grpc_server.add_insecure_port(f"[::]:{self.config.grpc_port}")
            await self._grpc_server.start()
            logger.info(f"gRPC server started on port {self.config.grpc_port}")

        except ImportError:
            logger.warning("gRPC not available, skipping gRPC server")
            self._grpc_server = None

    async def _stop_grpc_server(self) -> None:
        """Stop the gRPC server."""
        if self._grpc_server:
            await self._grpc_server.stop(grace=5)
            logger.info("gRPC server stopped")

    async def _start_health_server(self) -> None:
        """Start the health check HTTP server."""
        from aiohttp import web

        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/status", self._handle_status)
        app.router.add_get("/metrics", self._handle_metrics)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.config.health_port)
        await site.start()
        self._health_server = runner
        logger.info(f"Health server started on port {self.config.health_port}")

    async def _stop_health_server(self) -> None:
        """Stop the health check server."""
        if self._health_server:
            await self._health_server.cleanup()
            logger.info("Health server stopped")

    async def _handle_health(self, request) -> Any:
        """Handle health check request."""
        from aiohttp import web

        status = "healthy" if self.is_healthy else "unhealthy"
        return web.json_response(
            {
                "status": status,
                "lifecycle_state": self._lifecycle_state,
                "uptime_seconds": self.uptime_seconds,
                "active_requests": self._active_requests,
            }
        )

    async def _handle_status(self, request) -> Any:
        """Handle status request."""
        from aiohttp import web

        return web.json_response(self._get_status_dict())

    async def _handle_metrics(self, request) -> Any:
        """Handle metrics request."""
        from aiohttp import web

        return web.json_response(
            {
                "total_requests": self._metrics.total_requests,
                "successful_requests": self._metrics.successful_requests,
                "failed_requests": self._metrics.failed_requests,
                "avg_latency_ms": self._metrics.avg_latency_ms,
                "p99_latency_ms": self._metrics.p99_latency_ms,
                "total_tokens": self._metrics.total_tokens,
                "total_cost": self._metrics.total_cost,
            }
        )

    async def _initialize_agent(self) -> None:
        """Initialize the agent."""
        try:
            from src.infrastructure.agent.core import ProjectReActAgent

            # Create agent instance
            self._agent = ProjectReActAgent(
                tenant_id=self.config.tenant_id,
                project_id=self.config.project_id,
                agent_mode=self.config.agent_mode,
            )

            # Initialize agent
            await self._agent.initialize()

            self._is_initialized = True
            self._lifecycle_state = "ready"
            logger.info(
                f"Agent initialized: tools={getattr(self._agent, 'tool_count', 0)}"
            )

        except Exception as e:
            self._lifecycle_state = "error"
            self._error_message = str(e)
            logger.error(f"Failed to initialize agent: {e}", exc_info=True)
            raise

    def _get_status_dict(self) -> dict[str, Any]:
        """Get status as dictionary."""
        return {
            "instance_id": self.config.instance_id,
            "lifecycle_state": self._lifecycle_state,
            "is_healthy": self.is_healthy,
            "is_initialized": self._is_initialized,
            "is_paused": self._is_paused,
            "uptime_seconds": self.uptime_seconds,
            "error_message": self._error_message,
            "resources": {
                "active_requests": self._active_requests,
                "max_concurrent": self.config.max_concurrent_requests,
                "memory_limit_mb": self.config.memory_limit_mb,
            },
            "metrics": {
                "total_requests": self._metrics.total_requests,
                "successful_requests": self._metrics.successful_requests,
                "failed_requests": self._metrics.failed_requests,
                "avg_latency_ms": self._metrics.avg_latency_ms,
            },
        }

    # =========================================================================
    # gRPC Service Methods
    # =========================================================================

    async def Initialize(
        self,
        instance_id: str,
        tenant_id: str,
        project_id: str,
        agent_mode: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Initialize the agent with configuration."""
        self.config.instance_id = instance_id
        self.config.tenant_id = tenant_id
        self.config.project_id = project_id
        self.config.agent_mode = agent_mode

        if config:
            if "max_concurrent_requests" in config:
                self.config.max_concurrent_requests = config["max_concurrent_requests"]
                self._semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)

        await self._initialize_agent()

        return {
            "success": True,
            "message": "Agent initialized successfully",
            "tool_count": getattr(self._agent, "tool_count", 0),
            "skill_count": 0,
        }

    async def Execute(
        self,
        conversation_id: str,
        message: str,
        context: dict[str, str] | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a chat request with streaming response."""
        if not self._is_initialized:
            yield {"event_type": "error", "error": {"message": "Agent not initialized"}}
            return

        if self._is_paused:
            yield {"event_type": "error", "error": {"message": "Agent is paused"}}
            return

        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)

        start_time = time.time()
        self._metrics.total_requests += 1
        self._active_requests += 1
        self._last_request_time = datetime.now(UTC)
        self._lifecycle_state = "executing"

        try:
            async with self._semaphore:
                # Execute via agent
                async for event in self._agent.stream(
                    conversation_id=conversation_id,
                    message=message,
                    context=context or {},
                ):
                    yield event

            self._metrics.successful_requests += 1

        except Exception as e:
            self._metrics.failed_requests += 1
            yield {
                "event_type": "error",
                "error": {"message": str(e), "recoverable": True},
            }

        finally:
            self._active_requests -= 1
            if self._active_requests == 0:
                self._lifecycle_state = "ready"

            # Record latency
            latency_ms = (time.time() - start_time) * 1000
            self._metrics.total_latency_ms += latency_ms
            self._metrics.latencies.append(latency_ms)
            # Keep only last 1000 latencies for p99 calculation
            if len(self._metrics.latencies) > 1000:
                self._metrics.latencies = self._metrics.latencies[-1000:]

    async def Pause(
        self, drain_requests: bool = True, timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """Pause the agent."""
        self._is_paused = True
        self._lifecycle_state = "paused"

        if drain_requests:
            start = time.time()
            while self._active_requests > 0 and (time.time() - start) < timeout_seconds:
                await asyncio.sleep(0.5)

        return {
            "success": True,
            "message": "Agent paused",
            "pending_requests": self._active_requests,
        }

    async def Resume(self) -> dict[str, Any]:
        """Resume the agent."""
        self._is_paused = False
        self._lifecycle_state = "ready" if self._active_requests == 0 else "executing"
        return {"success": True, "message": "Agent resumed"}

    async def Shutdown(
        self, graceful: bool = True, timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """Shutdown the agent."""
        await self.stop(graceful=graceful)
        return {"success": True, "message": "Agent shutdown"}

    async def GetStatus(self) -> dict[str, Any]:
        """Get current status."""
        return self._get_status_dict()

    async def HealthCheck(self, include_details: bool = False) -> dict[str, Any]:
        """Health check."""
        status = "healthy" if self.is_healthy else "unhealthy"
        response = {
            "status": status,
            "timestamp": int(time.time() * 1000),
        }

        if include_details:
            response["components"] = [
                {
                    "name": "agent",
                    "status": "healthy" if self._is_initialized else "unhealthy",
                    "message": self._error_message or "OK",
                },
                {
                    "name": "grpc",
                    "status": "healthy" if self._grpc_server else "unavailable",
                },
            ]

        return response

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()


# =============================================================================
# Main Entry Point
# =============================================================================


async def main() -> None:
    """Main entry point for the agent container server."""
    # Configure logging
    config = AgentContainerConfig.from_env()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(f"Starting Agent Container with config: {config}")

    # Create and start server
    server = AgentContainerServer(config)

    # Handle shutdown signals
    loop = asyncio.get_event_loop()

    def handle_signal(sig) -> None:
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(server.stop(graceful=True))

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))

    try:
        await server.start()
        await server.wait_for_shutdown()
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
