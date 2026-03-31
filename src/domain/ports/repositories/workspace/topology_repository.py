from abc import ABC, abstractmethod

from src.domain.model.workspace.topology_edge import TopologyEdge
from src.domain.model.workspace.topology_node import TopologyNode


class TopologyRepository(ABC):
    """Repository interface for workspace topology graph."""

    @abstractmethod
    async def save_node(self, node: TopologyNode) -> TopologyNode:
        """Save a topology node (create or update)."""

    @abstractmethod
    async def find_node_by_id(self, node_id: str) -> TopologyNode | None:
        """Find topology node by ID."""

    @abstractmethod
    async def list_nodes_by_workspace(
        self,
        workspace_id: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[TopologyNode]:
        """List topology nodes in a workspace."""

    @abstractmethod
    async def list_all_nodes_by_workspace(self, workspace_id: str) -> list[TopologyNode]:
        """List all topology nodes in a workspace."""

    @abstractmethod
    async def list_nodes_by_hex(
        self,
        workspace_id: str,
        hex_q: int,
        hex_r: int,
    ) -> list[TopologyNode]:
        """List topology nodes occupying a specific hex."""

    @abstractmethod
    async def acquire_hex_lock(
        self,
        workspace_id: str,
        hex_q: int,
        hex_r: int,
    ) -> None:
        """Serialize competing occupancy claims for a single workspace hex."""

    @abstractmethod
    async def save_edge(self, edge: TopologyEdge) -> TopologyEdge:
        """Save a topology edge (create or update)."""

    @abstractmethod
    async def find_edge_by_id(self, edge_id: str) -> TopologyEdge | None:
        """Find topology edge by ID."""

    @abstractmethod
    async def list_edges_by_workspace(
        self,
        workspace_id: str,
        limit: int = 2000,
        offset: int = 0,
    ) -> list[TopologyEdge]:
        """List topology edges in a workspace."""

    @abstractmethod
    async def list_all_edges_by_workspace(self, workspace_id: str) -> list[TopologyEdge]:
        """List all topology edges in a workspace."""

    @abstractmethod
    async def list_edges_for_node(
        self,
        workspace_id: str,
        node_id: str,
    ) -> list[TopologyEdge]:
        """List topology edges connected to a node within a workspace."""

    @abstractmethod
    async def sync_edge_coordinates_for_node(
        self,
        workspace_id: str,
        node_id: str,
        hex_q: int | None,
        hex_r: int | None,
    ) -> None:
        """Update only the endpoint coordinates connected to a moved node."""

    @abstractmethod
    async def delete_node(self, node_id: str) -> bool:
        """Delete topology node by ID."""

    @abstractmethod
    async def delete_edge(self, edge_id: str) -> bool:
        """Delete topology edge by ID."""
