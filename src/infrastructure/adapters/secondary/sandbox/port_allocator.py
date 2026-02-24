"""Port Allocator - Thread-safe atomic port reservation for sandbox services.

This module provides a robust port allocation mechanism that:
- Uses atomic reservation with lock protection
- Supports Docker automatic port assignment (port 0)
- Cleans up stale reservations
- Handles port conflicts gracefully

This fixes the race condition issue where multiple sandboxes could
potentially get the same port under high concurrency.
"""

import asyncio
import logging
import socket
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PortReservation:
    """Represents a port reservation with metadata."""

    port: int
    sandbox_id: str
    service_type: str  # 'mcp', 'desktop', 'terminal'
    reserved_at: float
    expires_at: float | None = None  # None means never expires

    def is_expired(self) -> bool:
        """Check if this reservation has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


@dataclass
class PortAllocationResult:
    """Result of a port allocation request."""

    mcp_port: int
    desktop_port: int
    terminal_port: int
    reservation_id: str  # Unique ID to release all ports together

    def to_list(self) -> list[int]:
        """Return all ports as a list."""
        return [self.mcp_port, self.desktop_port, self.terminal_port]


class PortAllocator:
    """
    Thread-safe port allocator for sandbox services.

    This class provides atomic port allocation with the following features:
    - Lock-protected allocation to prevent race conditions
    - Port availability validation via socket binding
    - Docker container port conflict detection
    - Reservation expiration for cleanup
    - Support for Docker auto-assignment (port 0)

    Usage:
        allocator = PortAllocator(docker_client)

        # Allocate ports for a sandbox
        result = await allocator.allocate_ports("sandbox-123")

        # Use ports for container creation
        # ...

        # Release ports when sandbox terminates
        await allocator.release_ports(result.reservation_id)
    """

    def __init__(
        self,
        docker_client,
        mcp_port_range: tuple[int, int] = (18765, 19765),
        desktop_port_range: tuple[int, int] = (16080, 17080),
        terminal_port_range: tuple[int, int] = (17681, 18681),
        reservation_ttl_seconds: float = 300.0,  # 5 minutes default
        use_docker_auto_assign: bool = False,  # If True, let Docker assign ports
    ) -> None:
        """
        Initialize the port allocator.

        Args:
            docker_client: Docker client instance
            mcp_port_range: Range for MCP WebSocket ports (start, end)
            desktop_port_range: Range for desktop (noVNC) ports
            terminal_port_range: Range for terminal (ttyd) ports
            reservation_ttl_seconds: How long a reservation is valid without being confirmed
            use_docker_auto_assign: If True, use Docker's automatic port assignment
        """
        self._docker = docker_client
        self._mcp_port_range = mcp_port_range
        self._desktop_port_range = desktop_port_range
        self._terminal_port_range = terminal_port_range
        self._reservation_ttl = reservation_ttl_seconds
        self._use_docker_auto_assign = use_docker_auto_assign

        # Thread-safe lock for all port operations
        self._lock = asyncio.Lock()

        # Active reservations keyed by reservation_id
        self._reservations: dict[str, list[PortReservation]] = {}

        # Quick lookup of reserved ports
        self._reserved_ports: set[int] = set()

        # Port counters for round-robin allocation
        self._mcp_counter = 0
        self._desktop_counter = 0
        self._terminal_counter = 0

        logger.info(
            f"PortAllocator initialized: MCP={mcp_port_range}, "
            f"Desktop={desktop_port_range}, Terminal={terminal_port_range}"
        )

    async def allocate_ports(
        self,
        sandbox_id: str,
        timeout: float = 30.0,
    ) -> PortAllocationResult:
        """
        Allocate ports for a sandbox atomically.

        This method allocates all three ports (MCP, desktop, terminal) atomically,
        ensuring that either all succeed or all fail (no partial allocation).

        Args:
            sandbox_id: The sandbox ID requesting ports
            timeout: Maximum time to wait for port allocation

        Returns:
            PortAllocationResult with allocated ports

        Raises:
            RuntimeError: If no ports are available
            asyncio.TimeoutError: If allocation times out
        """
        if self._use_docker_auto_assign:
            # Return 0 for all ports - Docker will assign automatically
            return PortAllocationResult(
                mcp_port=0,
                desktop_port=0,
                terminal_port=0,
                reservation_id=f"docker-auto-{sandbox_id}",
            )

        try:
            async with asyncio.timeout(timeout):
                async with self._lock:
                    # Clean up expired reservations first
                    self._cleanup_expired_unsafe()

                    # Allocate all three ports atomically
                    mcp_port = self._find_available_port_unsafe(
                        self._mcp_port_range,
                        "mcp",
                    )
                    desktop_port = self._find_available_port_unsafe(
                        self._desktop_port_range,
                        "desktop",
                    )
                    terminal_port = self._find_available_port_unsafe(
                        self._terminal_port_range,
                        "terminal",
                    )

                    # Create reservation
                    reservation_id = f"res-{sandbox_id}-{int(time.time())}"
                    now = time.time()
                    expires_at = now + self._reservation_ttl

                    reservations = [
                        PortReservation(
                            port=mcp_port,
                            sandbox_id=sandbox_id,
                            service_type="mcp",
                            reserved_at=now,
                            expires_at=expires_at,
                        ),
                        PortReservation(
                            port=desktop_port,
                            sandbox_id=sandbox_id,
                            service_type="desktop",
                            reserved_at=now,
                            expires_at=expires_at,
                        ),
                        PortReservation(
                            port=terminal_port,
                            sandbox_id=sandbox_id,
                            service_type="terminal",
                            reserved_at=now,
                            expires_at=expires_at,
                        ),
                    ]

                    self._reservations[reservation_id] = reservations
                    self._reserved_ports.add(mcp_port)
                    self._reserved_ports.add(desktop_port)
                    self._reserved_ports.add(terminal_port)

                    logger.debug(
                        f"Allocated ports for {sandbox_id}: "
                        f"MCP={mcp_port}, Desktop={desktop_port}, Terminal={terminal_port}"
                    )

                    return PortAllocationResult(
                        mcp_port=mcp_port,
                        desktop_port=desktop_port,
                        terminal_port=terminal_port,
                        reservation_id=reservation_id,
                    )

        except TimeoutError:
            logger.error(f"Port allocation timeout for sandbox {sandbox_id}")
            raise
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Port allocation error for sandbox {sandbox_id}: {e}")
            raise RuntimeError(f"Port allocation failed: {e}")

    async def confirm_reservation(self, reservation_id: str) -> None:
        """
        Confirm a port reservation, making it permanent until explicitly released.

        Call this after successfully creating the container to prevent
        the reservation from expiring.

        Args:
            reservation_id: The reservation ID from allocate_ports
        """
        async with self._lock:
            if reservation_id in self._reservations:
                for reservation in self._reservations[reservation_id]:
                    reservation.expires_at = None  # Never expires
                logger.debug(f"Confirmed port reservation: {reservation_id}")

    async def release_ports(self, reservation_id: str) -> list[int]:
        """
        Release all ports associated with a reservation.

        Args:
            reservation_id: The reservation ID from allocate_ports

        Returns:
            List of released ports
        """
        async with self._lock:
            return self._release_ports_unsafe(reservation_id)

    def _release_ports_unsafe(self, reservation_id: str) -> list[int]:
        """Release ports without lock (must be called with lock held)."""
        if reservation_id not in self._reservations:
            return []

        released = []
        for reservation in self._reservations[reservation_id]:
            self._reserved_ports.discard(reservation.port)
            released.append(reservation.port)

        del self._reservations[reservation_id]
        logger.debug(f"Released ports for reservation {reservation_id}: {released}")
        return released

    async def release_ports_by_sandbox(self, sandbox_id: str) -> list[int]:
        """
        Release all ports reserved by a specific sandbox.

        Args:
            sandbox_id: The sandbox ID

        Returns:
            List of released ports
        """
        async with self._lock:
            released = []
            to_remove = []

            for reservation_id, reservations in self._reservations.items():
                if reservations and reservations[0].sandbox_id == sandbox_id:
                    to_remove.append(reservation_id)

            for reservation_id in to_remove:
                released.extend(self._release_ports_unsafe(reservation_id))

            return released

    def _find_available_port_unsafe(
        self,
        port_range: tuple[int, int],
        service_type: str,
    ) -> int:
        """
        Find an available port in the given range (must be called with lock held).

        Args:
            port_range: (start, end) port range
            service_type: Type of service for logging

        Returns:
            Available port number

        Raises:
            RuntimeError: If no ports are available
        """
        start, end = port_range
        range_size = end - start

        # Get the appropriate counter
        if service_type == "mcp":
            counter = self._mcp_counter
        elif service_type == "desktop":
            counter = self._desktop_counter
        else:
            counter = self._terminal_counter

        # Try each port in range starting from counter position
        for i in range(range_size):
            port = start + ((counter + i) % range_size)

            # Skip if already reserved
            if port in self._reserved_ports:
                continue

            # Check if port is actually available
            if self._is_port_available(port):
                # Update counter for round-robin
                if service_type == "mcp":
                    self._mcp_counter = (counter + i + 1) % range_size
                elif service_type == "desktop":
                    self._desktop_counter = (counter + i + 1) % range_size
                else:
                    self._terminal_counter = (counter + i + 1) % range_size

                return port

        raise RuntimeError(f"No available ports for {service_type} in range {port_range}")

    def _is_port_available(self, port: int) -> bool:
        """
        Check if a port is available on the host.

        Performs:
        1. Check if port is used by Docker containers
        2. Attempt to bind to verify it's free

        Args:
            port: The port number to check

        Returns:
            True if available, False otherwise
        """
        # Check Docker containers
        try:
            containers = self._docker.containers.list(all=True)
            for container in containers:
                ports = container.ports or {}
                for port_mappings in ports.values():
                    if port_mappings:
                        for mapping in port_mappings:
                            host_port = mapping.get("HostPort")
                            if host_port and int(host_port) == port:
                                return False
        except Exception as e:
            logger.warning(f"Error checking Docker container ports: {e}")

        # Try to bind to the port
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
                return True
        except OSError:
            return False

    def _cleanup_expired_unsafe(self) -> int:
        """
        Clean up expired reservations (must be called with lock held).

        Returns:
            Number of expired reservations cleaned up
        """
        expired = []

        for reservation_id, reservations in self._reservations.items():
            if reservations and reservations[0].is_expired():
                expired.append(reservation_id)

        for reservation_id in expired:
            self._release_ports_unsafe(reservation_id)

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired port reservations")

        return len(expired)

    async def cleanup_expired(self) -> int:
        """Clean up expired reservations with lock protection."""
        async with self._lock:
            return self._cleanup_expired_unsafe()

    async def get_stats(self) -> dict:
        """Get port allocator statistics."""
        async with self._lock:
            total_mcp = self._mcp_port_range[1] - self._mcp_port_range[0]
            total_desktop = self._desktop_port_range[1] - self._desktop_port_range[0]
            total_terminal = self._terminal_port_range[1] - self._terminal_port_range[0]

            mcp_reserved = sum(
                1
                for res_list in self._reservations.values()
                for res in res_list
                if res.service_type == "mcp"
            )
            desktop_reserved = sum(
                1
                for res_list in self._reservations.values()
                for res in res_list
                if res.service_type == "desktop"
            )
            terminal_reserved = sum(
                1
                for res_list in self._reservations.values()
                for res in res_list
                if res.service_type == "terminal"
            )

            return {
                "total_reservations": len(self._reservations),
                "reserved_ports_count": len(self._reserved_ports),
                "mcp": {
                    "range": self._mcp_port_range,
                    "total": total_mcp,
                    "reserved": mcp_reserved,
                    "available": total_mcp - mcp_reserved,
                },
                "desktop": {
                    "range": self._desktop_port_range,
                    "total": total_desktop,
                    "reserved": desktop_reserved,
                    "available": total_desktop - desktop_reserved,
                },
                "terminal": {
                    "range": self._terminal_port_range,
                    "total": total_terminal,
                    "reserved": terminal_reserved,
                    "available": total_terminal - terminal_reserved,
                },
            }
