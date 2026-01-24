"""
Neo4j client wrapper with connection pooling and timeout configuration.

This module provides a thin wrapper around the Neo4j AsyncDriver that:
- Manages connection pooling
- Configures timeouts to prevent indefinite hangs
- Provides helper methods for common graph operations
"""

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from neo4j import AsyncDriver, AsyncGraphDatabase

logger = logging.getLogger(__name__)

# Timeout configuration (in seconds)
CONNECTION_TIMEOUT = 10.0
ACQUISITION_TIMEOUT = 10.0
TRANSACTION_TIMEOUT = 30.0
MAX_CONNECTION_POOL_SIZE = 100
MAX_CONNECTION_LIFETIME = 3600


def _validate_identifier(identifier: str, context: str = "identifier") -> None:
    """
    Validate Neo4j identifiers (labels, relationship types, property keys).

    Args:
        identifier: The identifier to validate
        context: Description of what's being validated (for error messages)

    Raises:
        ValueError: If identifier contains invalid characters

    Note:
        Neo4j identifiers can contain letters (including Unicode), digits, and underscores.
        They must start with a letter or underscore. Special characters can be used if
        escaped with backticks, but we don't support backtick-escaped identifiers here
        for security reasons (to prevent injection attacks).
    """
    if not identifier:
        raise ValueError(f"Invalid {context}: empty string")

    # For security, we use a strict allowlist: ASCII letters, digits, and underscores only.
    # This prevents injection attacks while supporting the most common use cases.
    # If Unicode identifiers are needed, they should be validated separately.
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", identifier):
        raise ValueError(
            f"Invalid {context} '{identifier}': must start with ASCII letter or underscore "
            "and contain only ASCII letters, digits, and underscores"
        )


class Neo4jClient:
    """
    Async Neo4j client wrapper with connection pooling and timeout configuration.

    This client provides:
    - Connection pooling with configurable limits
    - Query timeout handling
    - Helper methods for common operations (save node, save edge, etc.)
    - Transaction support

    Example:
        async with Neo4jClient(uri, user, password) as client:
            await client.execute_query("MATCH (n) RETURN n LIMIT 10")
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        connection_timeout: float = CONNECTION_TIMEOUT,
        acquisition_timeout: float = ACQUISITION_TIMEOUT,
        max_pool_size: int = MAX_CONNECTION_POOL_SIZE,
    ):
        """
        Initialize Neo4j client.

        Args:
            uri: Neo4j connection URI (e.g., "bolt://localhost:7687")
            user: Neo4j username
            password: Neo4j password
            database: Database name (default: "neo4j")
            connection_timeout: Connection timeout in seconds
            acquisition_timeout: Connection acquisition timeout in seconds
            max_pool_size: Maximum connection pool size
        """
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.connection_timeout = connection_timeout
        self.acquisition_timeout = acquisition_timeout
        self.max_pool_size = max_pool_size

        self._driver: Optional[AsyncDriver] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the Neo4j driver connection."""
        if self._initialized:
            return

        if self.user is None or self.password is None:
            raise ValueError(
                "Neo4j credentials (user and password) must be provided and cannot be None."
            )

        logger.info(f"Initializing Neo4j connection to {self.uri}")

        self._driver = AsyncGraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password),
            max_connection_lifetime=MAX_CONNECTION_LIFETIME,
            max_connection_pool_size=self.max_pool_size,
            connection_timeout=self.connection_timeout,
            connection_acquisition_timeout=self.acquisition_timeout,
        )

        # Verify connectivity
        try:
            await asyncio.wait_for(
                self._driver.verify_connectivity(),
                timeout=self.connection_timeout,
            )
            self._initialized = True
            logger.info("Neo4j connection established successfully")
        except asyncio.TimeoutError:
            logger.error(f"Neo4j connection timeout after {self.connection_timeout}s")
            raise ConnectionError(f"Neo4j connection timeout to {self.uri}")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise

    async def close(self) -> None:
        """Close the Neo4j driver connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            self._initialized = False
            logger.info("Neo4j connection closed")

    async def __aenter__(self) -> "Neo4jClient":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    @property
    def driver(self) -> AsyncDriver:
        """Get the underlying Neo4j driver."""
        if not self._driver:
            raise RuntimeError("Neo4j client not initialized. Call initialize() first.")
        return self._driver

    async def execute_query(
        self,
        query: str,
        timeout: float = TRANSACTION_TIMEOUT,
        **parameters: Any,
    ) -> Any:
        """
        Execute a Cypher query with timeout handling.

        Args:
            query: Cypher query string
            timeout: Query timeout in seconds
            **parameters: Query parameters

        Returns:
            Query result (EagerResult with records, summary, keys)
        """
        if not self._initialized:
            await self.initialize()

        try:
            result = await asyncio.wait_for(
                self._driver.execute_query(
                    query,
                    database_=self.database,
                    **parameters,
                ),
                timeout=timeout,
            )
            return result
        except asyncio.TimeoutError:
            logger.error(f"Query timeout after {timeout}s: {query[:100]}...")
            raise TimeoutError(f"Neo4j query timeout after {timeout}s")

    @asynccontextmanager
    async def session(self):
        """
        Create an async session for transaction control.

        Example:
            async with client.session() as session:
                async with session.begin_transaction() as tx:
                    await tx.run("MATCH (n) RETURN n")
        """
        if not self._initialized:
            await self.initialize()

        async with self._driver.session(database=self.database) as session:
            yield session

    async def save_node(
        self,
        labels: List[str],
        uuid: str,
        properties: Dict[str, Any],
    ) -> None:
        """
        Save (MERGE) a node with the given labels and properties.

        Args:
            labels: List of node labels
            uuid: Node UUID (used as primary key)
            properties: Node properties

        Raises:
            ValueError: If labels or property keys contain invalid characters
        """
        # Validate labels
        for label in labels:
            _validate_identifier(label, "node label")

        # Validate property keys
        for key in properties.keys():
            _validate_identifier(key, "property key")

        # Remove uuid from properties if present to avoid duplicate argument
        props_without_uuid = {k: v for k, v in properties.items() if k != "uuid"}

        labels_str = ":".join(labels)
        props_str = ", ".join(f"n.{k} = ${k}" for k in props_without_uuid.keys())

        query = f"""
            MERGE (n:{labels_str} {{uuid: $uuid}})
            SET {props_str}
        """

        await self.execute_query(query, uuid=uuid, **props_without_uuid)

    async def save_edge(
        self,
        from_uuid: str,
        to_uuid: str,
        relationship_type: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Save (MERGE) an edge between two nodes.

        Args:
            from_uuid: Source node UUID
            to_uuid: Target node UUID
            relationship_type: Relationship type (e.g., "MENTIONS", "RELATES_TO")
            properties: Relationship properties (optional)

        Raises:
            ValueError: If relationship_type or property keys contain invalid characters
        """
        # Validate relationship type
        _validate_identifier(relationship_type, "relationship type")

        # Validate property keys if present
        if properties:
            for key in properties.keys():
                _validate_identifier(key, "property key")

        props_str = ""
        if properties:
            props_str = ", ".join(f"r.{k} = ${k}" for k in properties.keys())
            props_str = f"SET {props_str}"

        query = f"""
            MATCH (from {{uuid: $from_uuid}})
            MATCH (to {{uuid: $to_uuid}})
            MERGE (from)-[r:{relationship_type}]->(to)
            {props_str}
        """

        params = {"from_uuid": from_uuid, "to_uuid": to_uuid}
        if properties:
            params.update(properties)

        await self.execute_query(query, **params)

    async def delete_node(self, uuid: str) -> bool:
        """
        Delete a node by UUID (with DETACH to remove relationships).

        Args:
            uuid: Node UUID

        Returns:
            True if a node was deleted
        """
        query = """
            MATCH (n {uuid: $uuid})
            DETACH DELETE n
            RETURN count(n) AS deleted
        """

        result = await self.execute_query(query, uuid=uuid)
        if result.records:
            return result.records[0]["deleted"] > 0
        return False

    async def find_node_by_uuid(
        self,
        uuid: str,
        labels: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find a node by UUID.

        Args:
            uuid: Node UUID
            labels: Optional list of labels to filter by

        Returns:
            Node properties dict or None if not found
        """
        labels_str = ":".join(labels) if labels else ""
        label_filter = f":{labels_str}" if labels_str else ""

        query = f"""
            MATCH (n{label_filter} {{uuid: $uuid}})
            RETURN n
        """

        result = await self.execute_query(query, uuid=uuid)
        if result.records and len(result.records) > 0:
            node = result.records[0]["n"]
            return dict(node)
        return None

    async def build_indices(self, delete_existing: bool = False) -> None:
        """
        Build standard indices for the knowledge graph.

        Creates indices for:
        - Episodic nodes: uuid, project_id, created_at, memory_id
        - Entity nodes: uuid, name, project_id, name_embedding (vector)
        - Community nodes: uuid, project_id
        - RELATES_TO relationships: uuid

        Args:
            delete_existing: If True, drop existing indices first
        """
        logger.info("Building Neo4j indices...")

        # Index definitions
        indices = [
            # Episodic indices
            "CREATE INDEX episodic_uuid IF NOT EXISTS FOR (e:Episodic) ON (e.uuid)",
            "CREATE INDEX episodic_project IF NOT EXISTS FOR (e:Episodic) ON (e.project_id)",
            "CREATE INDEX episodic_created_at IF NOT EXISTS FOR (e:Episodic) ON (e.created_at)",
            "CREATE INDEX episodic_memory_id IF NOT EXISTS FOR (e:Episodic) ON (e.memory_id)",
            # Entity indices
            "CREATE INDEX entity_uuid IF NOT EXISTS FOR (e:Entity) ON (e.uuid)",
            "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)",
            "CREATE INDEX entity_project IF NOT EXISTS FOR (e:Entity) ON (e.project_id)",
            # Community indices
            "CREATE INDEX community_uuid IF NOT EXISTS FOR (c:Community) ON (c.uuid)",
            "CREATE INDEX community_project IF NOT EXISTS FOR (c:Community) ON (c.project_id)",
            # Fulltext index for content search
            """CREATE FULLTEXT INDEX episodic_content IF NOT EXISTS
               FOR (e:Episodic) ON EACH [e.content]""",
            """CREATE FULLTEXT INDEX entity_name_summary IF NOT EXISTS
               FOR (e:Entity) ON EACH [e.name, e.summary]""",
        ]

        if delete_existing:
            # Drop existing indices
            drop_query = """
                SHOW INDEXES YIELD name
                WHERE name STARTS WITH 'episodic_' OR name STARTS WITH 'entity_'
                    OR name STARTS WITH 'community_'
                RETURN name
            """
            result = await self.execute_query(drop_query)
            for record in result.records:
                index_name = record["name"]
                try:
                    await self.execute_query(f"DROP INDEX {index_name}")
                    logger.info(f"Dropped index: {index_name}")
                except Exception as e:
                    logger.warning(f"Failed to drop index {index_name}: {e}")

        # Create indices
        for index_query in indices:
            try:
                await asyncio.wait_for(
                    self.execute_query(index_query),
                    timeout=TRANSACTION_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(f"Index creation timed out: {index_query[:50]}...")
            except Exception as e:
                # Already exists errors are OK
                if "EquivalentSchemaRuleAlreadyExists" not in str(e):
                    logger.warning(f"Failed to create index: {e}")

        logger.info("Neo4j indices built successfully")

    async def create_vector_index(
        self,
        index_name: str,
        label: str,
        property_name: str,
        dimensions: int,
        similarity_function: str = "cosine",
    ) -> None:
        """
        Create a vector index for similarity search.

        Args:
            index_name: Name of the vector index
            label: Node label
            property_name: Property containing the vector
            dimensions: Vector dimensions
            similarity_function: Similarity function ("cosine", "euclidean")
        """
        query = f"""
            CREATE VECTOR INDEX {index_name} IF NOT EXISTS
            FOR (n:{label})
            ON (n.{property_name})
            OPTIONS {{
                indexConfig: {{
                    `vector.dimensions`: {dimensions},
                    `vector.similarity_function`: '{similarity_function}'
                }}
            }}
        """

        try:
            await self.execute_query(query)
            logger.info(f"Created vector index {index_name} ({dimensions}D, {similarity_function})")
        except Exception as e:
            if "EquivalentSchemaRuleAlreadyExists" not in str(e):
                logger.warning(f"Failed to create vector index: {e}")

    async def vector_search(
        self,
        index_name: str,
        query_vector: List[float],
        limit: int = 10,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Perform vector similarity search.

        Args:
            index_name: Name of the vector index
            query_vector: Query vector
            limit: Maximum results to return
            project_id: Optional project ID filter

        Returns:
            List of dicts with 'node' and 'score' keys
        """
        project_filter = ""
        if project_id:
            project_filter = "WHERE node.project_id = $project_id OR $project_id IS NULL"

        query = f"""
            CALL db.index.vector.queryNodes(
                $index_name,
                $limit,
                $query_vector
            )
            YIELD node, score
            {project_filter}
            RETURN node, score
            ORDER BY score DESC
        """

        params = {
            "index_name": index_name,
            "limit": limit,
            "query_vector": query_vector,
        }
        if project_id:
            params["project_id"] = project_id

        result = await self.execute_query(query, **params)

        return [
            {"node": dict(record["node"]), "score": record["score"]} for record in result.records
        ]

    async def fulltext_search(
        self,
        index_name: str,
        query: str,
        limit: int = 10,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Perform fulltext search.

        Args:
            index_name: Name of the fulltext index
            query: Search query
            limit: Maximum results to return
            project_id: Optional project ID filter

        Returns:
            List of dicts with 'node' and 'score' keys
        """
        project_filter = ""
        if project_id:
            project_filter = "WHERE node.project_id = $project_id OR $project_id IS NULL"

        query_str = f"""
            CALL db.index.fulltext.queryNodes($index_name, $query)
            YIELD node, score
            {project_filter}
            RETURN node, score
            ORDER BY score DESC
            LIMIT $limit
        """

        params = {
            "index_name": index_name,
            "query": query,
            "limit": limit,
        }
        if project_id:
            params["project_id"] = project_id

        result = await self.execute_query(query_str, **params)

        return [
            {"node": dict(record["node"]), "score": record["score"]} for record in result.records
        ]
