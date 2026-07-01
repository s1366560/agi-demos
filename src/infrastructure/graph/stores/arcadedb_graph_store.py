"""ArcadeDB graph store (Phase 4 POC).

ArcadeDB exposes a Bolt-compatible port that speaks OpenCypher, so it is
reachable via the standard ``neo4j`` async driver — the same client we use for
Neo4j. This adapter subclasses ``NativeGraphAdapter`` (a.k.a. the Neo4j store)
to reuse ALL Cypher-based CRUD primitives (episode/entity/relationship write,
delete, graph snapshot, counts, maintenance).

ArcadeDB splits its surface across TWO languages, and this split is the central
design constraint of the adapter (verified live against
``arcadedata/arcadedb:latest``, v26.7.x):

- **OpenCypher over Bolt** (port 7687): node/edge CRUD — ``MERGE`` / ``SET`` /
  ``MATCH`` / ``CREATE`` / ``DELETE`` with bound ``$params``. Works exactly like
  Neo4j. This is everything ``NativeGraphAdapter`` already does.
- **SQL over HTTP** (port 2480, ``/api/v1/command/{db}``): schema DDL
  (``CREATE VERTEX/EDGE/PROPERTY TYPE``), vector indexing
  (``LSM_VECTOR`` + the ``vectorNeighbors()`` function) and fulltext
  (``SEARCH_INDEX()``). These CANNOT run over Bolt — ArcadeDB's Cypher parser
  rejects ``SELECT``/DDL with ``Syntax error ... mismatched input``.

Therefore the three overridden primitives (``initialize_schema``,
``vector_search``, ``fulltext_search``) issue **SQL via HTTP**, while every
other primitive is inherited unchanged and runs over Bolt/Cypher.

Construction:

    ArcadeDBGraphStore(
        neo4j_client=client,            # Bolt client pointing at ArcadeDB :7687
        llm_client=...,
        embedding_service=...,
        http_base_url="http://host:2480",  # SQL-over-HTTP endpoint
        http_database="memstack",          # ArcadeDB database name
        http_auth=("root", "arcadepw"),
    )

The ``http_*`` kwargs default to ``None``; when omitted they are derived from
the Bolt client's URI/database/credentials so the two transports always agree.
"""

from __future__ import annotations

import base64
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from src.domain.model.graph.dtos import GraphSearchHit
from src.infrastructure.graph.native_graph_adapter import NativeGraphAdapter
from src.infrastructure.graph.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


class ArcadeDBGraphStore(NativeGraphAdapter):
    """ArcadeDB backend (Bolt + HTTP SQL) implementing ``GraphStorePort``.

    Reuses ``NativeGraphAdapter`` for all Cypher CRUD primitives (ArcadeDB
    supports OpenCypher over Bolt) and overrides ``initialize_schema`` /
    ``vector_search`` / ``fulltext_search`` to issue ArcadeDB SQL over HTTP
    (the only transport through which DDL and the vector/fulltext functions
    are reachable).
    """

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        *,
        http_base_url: str | None = None,
        http_database: str | None = None,
        http_auth: tuple[str, str] | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        super().__init__(neo4j_client=neo4j_client, **kwargs)

        # Derive the HTTP SQL endpoint from the Bolt client when not given, so
        # the two transports point at the same cluster / database / credentials.
        parsed = urlparse(neo4j_client.uri)
        host = parsed.hostname or "localhost"
        self._http_base_url = http_base_url or f"http://{host}:2480"
        self._http_database = http_database or neo4j_client.database
        self._http_auth = http_auth or (neo4j_client.user, neo4j_client.password)
        # Embedding dimension drives the vector index dimension; fall back to
        # the embedding service's reported dimension, else 1536 (OpenAI text).
        self._vector_dim: int = getattr(self._embedding_service, "embedding_dim", None) or 1536
        logger.info(
            "ArcadeDBGraphStore initialized (Bolt=%s, HTTP SQL db=%s, dim=%d)",
            neo4j_client.uri,
            self._http_database,
            self._vector_dim,
        )

    # ------------------------------------------------------------------
    # SQL-over-HTTP transport
    # ------------------------------------------------------------------

    async def _sql(self, command: str) -> Any:  # noqa: ANN401
        """Run a SQL command against ArcadeDB's HTTP API and return ``result``.

        Endpoint: ``POST /api/v1/command/{database}`` with JSON body
        ``{"language":"sql","command":...}`` (Basic auth).

        NOTE: ArcadeDB's HTTP command endpoint does NOT bind ``parameters``
        (named ``:x`` or positional ``?``) in this build — they are silently
        dropped. Dynamic values MUST be serialized into the command string as
        SQL literals. Use :meth:`_sql_vec_literal` for query vectors.
        """
        url = f"{self._http_base_url}/api/v1/command/{self._http_database}"
        body: dict[str, Any] = {"language": "sql", "command": command}
        token = base64.b64encode(f"{self._http_auth[0]}:{self._http_auth[1]}".encode()).decode()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Basic {token}"},
            )
            payload: dict[str, Any] = {}
            try:
                payload = resp.json()
            except Exception:
                resp.raise_for_status()
            if resp.is_error or "error" in payload:
                detail = payload.get("detail") or payload.get("error") or resp.text
                raise RuntimeError(f"ArcadeDB SQL error: {detail}")
            return payload.get("result", [])

    @staticmethod
    def _sql_str_literal(text: str) -> str:
        """Quote a string for ArcadeDB SQL (single-quote, escape internals).

        ArcadeDB SQL strings are single-quoted; embedded single quotes are
        doubled. We additionally reject newlines/backticks to keep the literal
        a single, injection-safe token.
        """
        if any(c in text for c in ("\n", "\r", "`")):
            raise ValueError("ArcadeDB fulltext query contains illegal characters")
        return "'" + text.replace("'", "''") + "'"

    @staticmethod
    def _sql_vec_literal(vec: list[float]) -> str:
        """Render a float vector as an ArcadeDB SQL array literal ``[1.0, 2.0]``.

        Only finite floats are accepted (no NaN/Inf, no strings), so this is
        injection-safe. Required because ArcadeDB's HTTP endpoint drops bound
        parameters.
        """
        parts: list[str] = []
        for v in vec:
            fv = float(v)
            if not (abs(fv) < float("inf")):  # rejects NaN and Inf
                raise ValueError("Vector contains non-finite value")
            parts.append(repr(fv))
        return "[" + ",".join(parts) + "]"

    # ------------------------------------------------------------------
    # Schema initialization (SQL DDL over HTTP — Cypher cannot do DDL)
    # ------------------------------------------------------------------

    async def initialize_schema(self) -> None:
        """Create ArcadeDB schema: vertex/edge types + vector/fulltext indexes.

        All statements are idempotent (``IF NOT EXISTS``). Runs as SQL over
        HTTP because ArcadeDB's Cypher parser rejects DDL.
        """
        # 1. Vertex + edge types.
        for stmt in (
            "CREATE VERTEX TYPE Entity IF NOT EXISTS",
            "CREATE VERTEX TYPE Episodic IF NOT EXISTS",
            "CREATE VERTEX TYPE Community IF NOT EXISTS",
            "CREATE EDGE TYPE MENTIONS IF NOT EXISTS",
            "CREATE EDGE TYPE RELATES_TO IF NOT EXISTS",
            "CREATE EDGE TYPE BELONGS_TO IF NOT EXISTS",
        ):
            try:
                await self._sql(stmt)
            except Exception as e:
                logger.warning("ArcadeDB DDL stmt failed (may already exist): %s", e)

        # 2. name_embedding property (ARRAY_OF_FLOATS — required for LSM_VECTOR
        #    with the default FLOAT32 encoding).
        try:
            await self._sql("CREATE PROPERTY Entity.name_embedding IF NOT EXISTS ARRAY_OF_FLOATS")
        except Exception as e:
            logger.warning("ArcadeDB vector property creation skipped: %s", e)

        # 3. LSM_VECTOR index (cosine similarity). ArcadeDB's vector index type
        #    is ``LSM_VECTOR`` (NOT Neo4j's VECTOR_INDEX), configured via
        #    ``METADATA {dimensions, similarity}``.
        try:
            await self._sql(
                "CREATE INDEX entity_name_embedding IF NOT EXISTS "
                "ON Entity (name_embedding) LSM_VECTOR "
                f'METADATA {{dimensions: {self._vector_dim}, similarity: "COSINE"}}'
            )
        except Exception as e:
            logger.warning("ArcadeDB vector index creation skipped: %s", e)

    # ------------------------------------------------------------------
    # Vector search (SQL vectorNeighbors function over HTTP)
    # ------------------------------------------------------------------

    async def vector_search(
        self,
        query_vector: list[float],
        limit: int = 10,
        project_id: str | None = None,
        index_name: str | None = None,
    ) -> list[GraphSearchHit]:
        """Vector similarity search via ArcadeDB's ``vectorNeighbors`` SQL fn.

        ArcadeDB syntax (vector inlined — the HTTP endpoint drops params)::

            SELECT expand(vectorNeighbors('Entity[name_embedding]', [v1,v2,...], k))

        Returns rows each carrying the matched ``record`` and a ``distance``.
        """
        vec_lit = self._sql_vec_literal(query_vector)
        lim = int(limit)
        rows = await self._sql(
            f"SELECT expand(vectorNeighbors('Entity[name_embedding]', {vec_lit}, {lim}))"
        )
        hits: list[GraphSearchHit] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            record = row.get("record") or {}
            if project_id is not None and record.get("project_id") != project_id:
                continue
            props = dict(record)
            # ArcadeDB returns a distance (0 = identical); convert to a
            # similarity-ish score (1 - distance for cosine in [0,2]).
            distance = float(row.get("distance", 0.0))
            score = max(0.0, 1.0 - distance)
            hits.append(GraphSearchHit(node=props, score=score))
        return hits

    # ------------------------------------------------------------------
    # Fulltext search (SQL SEARCH_INDEX function over HTTP)
    # ------------------------------------------------------------------

    async def fulltext_search(
        self,
        query: str,
        limit: int = 10,
        project_id: str | None = None,
        index_name: str | None = None,
    ) -> list[GraphSearchHit]:
        """Fulltext search via ArcadeDB's ``SEARCH_INDEX`` SQL function.

        ArcadeDB syntax (query inlined — the HTTP endpoint drops params)::

            SELECT expand(SEARCH_INDEX('Entity[name_summary]', 'text'))

        Requires a ``LSM_FULLTEXT`` index on ``Entity.name_summary`` (created
        lazily here if missing).
        """
        # Lazily ensure the fulltext index + property exist. ArcadeDB's Lucene
        # fulltext index type is ``FULL_TEXT`` (NOT ``FULLTEXT`` / ``LSM_FULLTEXT``).
        try:
            await self._sql("CREATE PROPERTY Entity.name_summary IF NOT EXISTS STRING")
            await self._sql(
                "CREATE INDEX entity_name_summary IF NOT EXISTS ON Entity (name_summary) FULL_TEXT"
            )
        except Exception as e:
            logger.debug("ArcadeDB fulltext index ensure skipped: %s", e)

        # SEARCH_INDEX takes the INDEX NAME (not 'Type[prop]') and a Lucene query.
        text_lit = self._sql_str_literal(query)
        rows = await self._sql(f"SELECT expand(SEARCH_INDEX('entity_name_summary', {text_lit}))")
        hits: list[GraphSearchHit] = []
        for row in rows:
            if isinstance(row, dict) and "record" in row:
                record = row["record"] or {}
            elif isinstance(row, dict):
                record = row
            else:
                continue
            if project_id is not None and record.get("project_id") != project_id:
                continue
            props = dict(record)
            score = float(props.pop("_score", 1.0))
            hits.append(GraphSearchHit(node=props, score=score))
            if len(hits) >= limit:
                break
        return hits
