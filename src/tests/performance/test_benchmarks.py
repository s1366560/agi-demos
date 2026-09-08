"""In-process HTTP benchmarks with SQLite and mocked external graph services."""

import asyncio
import time
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.agent.plugins.skill_evolution.scheduler import EvolutionScheduler
from src.infrastructure.plugins.v2.builtin_enhanced_search_http_routes import (
    ENHANCED_SEARCH_HTTP_ROUTES_ROW_V2,
)
from src.infrastructure.plugins.v2.builtin_episodes_http_routes import EPISODES_HTTP_ROUTES_ROW_V2
from src.infrastructure.plugins.v2.builtin_memories_http_routes import MEMORIES_HTTP_ROUTES_ROW_V2
from src.infrastructure.plugins.v2.builtin_projects_http_routes import PROJECTS_HTTP_ROUTES_ROW_V2


@pytest.fixture
async def client(
    test_app: FastAPI, mock_graph_service: object, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """Measure in-process HTTP with real V2 routes and mocked external graph work."""

    async def graph_runtime_factory() -> object:
        return mock_graph_service

    monkeypatch.setattr(EvolutionScheduler, "start", AsyncMock())
    await initialize_plugin_runtime_v2(test_app, graph_runtime_factory=graph_runtime_factory)
    try:
        assert {
            EPISODES_HTTP_ROUTES_ROW_V2,
            MEMORIES_HTTP_ROUTES_ROW_V2,
            PROJECTS_HTTP_ROUTES_ROW_V2,
            ENHANCED_SEARCH_HTTP_ROUTES_ROW_V2,
        } <= set(test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids)
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            yield client
    finally:
        await shutdown_plugin_runtime_v2(test_app)


# These measure application HTTP overhead with test adapters, not PostgreSQL pool
# throughput or external graph/model latency. Run separately against stable CI baselines.


@pytest.mark.performance
@pytest.mark.slow
class TestPerformanceBenchmarks:
    """Performance benchmarks for API endpoints."""

    async def test_episode_creation_performance(
        self, client, mock_graphiti_client, test_project_db
    ):
        """Benchmark episode creation endpoint."""
        iterations = 100
        mock_graphiti_client.add_episode = AsyncMock(
            side_effect=lambda episode: Mock(id=episode.id)
        )
        sample_data = {
            "name": "Benchmark Episode",
            "content": "This is a benchmark test episode content.",
            "project_id": test_project_db.id,
            "tenant_id": test_project_db.tenant_id,
        }

        start_time = time.perf_counter()

        for _ in range(iterations):
            response = await client.post("/api/v1/episodes/", json=sample_data)
            assert response.status_code == 202

        end_time = time.perf_counter()
        total_time = end_time - start_time
        avg_time = (total_time / iterations) * 1000  # Convert to ms

        print("\nEpisode Creation Performance:")
        print(f"  Total time: {total_time:.2f}s")
        print(f"  Average time: {avg_time:.2f}ms")
        print(f"  Throughput: {iterations / total_time:.2f} req/s")

        # Performance assertions
        assert mock_graphiti_client.add_episode.await_count == iterations
        assert avg_time < 100, f"Average response time too high: {avg_time:.2f}ms"

    async def test_search_performance(self, client, test_project_db, mock_graph_service):
        """Benchmark search endpoint."""
        iterations = 50

        start_time = time.perf_counter()

        for _ in range(iterations):
            response = await client.post(
                "/api/v1/search-enhanced/advanced",
                json={"query": "test search", "limit": 20, "project_id": test_project_db.id},
            )
            assert response.status_code == 200

        end_time = time.perf_counter()
        total_time = end_time - start_time
        avg_time = (total_time / iterations) * 1000

        print("\nSearch Performance:")
        print(f"  Total time: {total_time:.2f}s")
        print(f"  Average time: {avg_time:.2f}ms")
        print(f"  Throughput: {iterations / total_time:.2f} req/s")

        assert mock_graph_service.search.await_count == iterations
        assert avg_time < 200, f"Search response time too high: {avg_time:.2f}ms"

    async def test_list_episodes_performance(self, client, test_project_db):
        """Benchmark list episodes endpoint."""
        iterations = 100

        start_time = time.perf_counter()

        for _ in range(iterations):
            response = await client.get(
                f"/api/v1/episodes/?limit=50&tenant_id={test_project_db.tenant_id}"
                f"&project_id={test_project_db.id}"
            )
            assert response.status_code == 200

        end_time = time.perf_counter()
        total_time = end_time - start_time
        avg_time = (total_time / iterations) * 1000

        print("\nList Episodes Performance:")
        print(f"  Total time: {total_time:.2f}s")
        print(f"  Average time: {avg_time:.2f}ms")
        print(f"  Throughput: {iterations / total_time:.2f} req/s")

        assert avg_time < 50, f"List response time too high: {avg_time:.2f}ms"

    async def test_concurrent_requests(self, client):
        """Benchmark concurrent request handling."""

        async def make_request(client):
            response = await client.get("/api/v1/episodes/health")
            return response

        start_time = time.perf_counter()

        # Make 50 concurrent requests
        tasks = [make_request(client) for _ in range(50)]
        responses = await asyncio.gather(*tasks)

        end_time = time.perf_counter()
        total_time = end_time - start_time

        successful = sum(1 for r in responses if r.status_code == 200)

        print("\nConcurrent Requests Performance:")
        print(f"  Total time: {total_time:.2f}s")
        print("  Concurrent requests: 50")
        print(f"  Successful: {successful}/50")
        print(f"  Throughput: {50 / total_time:.2f} req/s")

        assert successful == 50, f"Some requests failed: {successful}/50"

    async def test_memory_crud_performance(self, client, test_project_db):
        """Benchmark memory CRUD operations."""
        # Create
        create_data = {
            "project_id": test_project_db.id,
            "title": "Bench Memory",
            "content": "Benchmark memory content",
            "author_id": test_project_db.owner_id,
            "tenant_id": test_project_db.tenant_id,
        }

        start_time = time.perf_counter()
        response = await client.post("/api/v1/memories/", json=create_data)
        create_time = (time.perf_counter() - start_time) * 1000

        # Read
        assert response.status_code == 201
        memory_id = response.json()["id"]
        start_time = time.perf_counter()
        response = await client.get(f"/api/v1/memories/{memory_id}")
        read_time = (time.perf_counter() - start_time) * 1000
        assert response.status_code == 200
        assert response.json()["title"] == create_data["title"]

        # Update
        update_data = {"title": "Updated Bench Memory", "version": response.json()["version"]}
        start_time = time.perf_counter()
        response = await client.patch(f"/api/v1/memories/{memory_id}", json=update_data)
        update_time = (time.perf_counter() - start_time) * 1000
        assert response.status_code == 200
        assert response.json()["title"] == update_data["title"]
        assert response.json()["version"] == update_data["version"] + 1

        print("\nMemory CRUD Performance:")
        print(f"  Create: {create_time:.2f}ms")
        print(f"  Read: {read_time:.2f}ms")
        print(f"  Update: {update_time:.2f}ms")

        assert create_time < 100
        assert read_time < 50
        assert update_time < 100


@pytest.mark.performance
class TestArchitectureComparison:
    """Legacy descriptive comparisons, not measured performance results."""

    def test_old_vs_new_episode_creation(self):
        """
        Compare episode creation performance between architectures.

        This test should be run with both server/ and src/ implementations
        to compare performance.
        """
        print("\n=== Architecture Comparison: Episode Creation ===")
        print("Old Architecture (server/):")
        print("  - Monolithic service layer")
        print("  - Direct GraphitiService access")
        print("  - Expected: ~50-80ms per request")
        print()
        print("New Architecture (src/):")
        print("  - Hexagonal architecture")
        print("  - Use Case + Adapter pattern")
        print("  - Expected: ~60-100ms per request (slight overhead from abstraction)")
        print()
        print("Trade-offs:")
        print("  + New: Better testability, separation of concerns")
        print("  + New: Easier to swap implementations")
        print("  - New: Slight performance overhead from additional layers")
        print("  - New: More boilerplate code")

    def test_old_vs_new_search(self):
        """
        Compare search performance between architectures.
        """
        print("\n=== Architecture Comparison: Search ===")
        print("Old Architecture (server/):")
        print("  - Direct service calls")
        print("  - Inline search logic in endpoints")
        print("  - Expected: ~150-200ms per search")
        print()
        print("New Architecture (src/):")
        print("  - Dedicated Use Cases")
        print("  - Port/Adapter pattern for Graphiti")
        print("  - Expected: ~160-210ms per search")
        print()
        print("Benefits of new architecture for search:")
        print("  + Easier to mock Graphiti for testing")
        print("  + Can swap search implementations without changing Use Case")
        print("  + Clear separation between application logic and infrastructure")

    def test_old_vs_new_maintainability(self):
        """
        Compare maintainability metrics between architectures.
        """
        print("\n=== Architecture Comparison: Maintainability ===")
        print()
        print("Metric                          | Old (server/) | New (src/)")
        print("-" * 70)
        print("Lines per endpoint             | ~50-100       | ~40-80")
        print("Test coverage potential         | Medium        | High")
        print("Dependency injection           | Limited       | Full")
        print("Domain logic isolation         | No            | Yes")
        print("External service mocking        | Difficult     | Easy")
        print("Swap implementations            | Hard          | Easy")
        print("Single Responsibility Principle | Partial       | Full")
        print()
        print("Conclusion:")
        print("  New architecture trades ~10-20% performance for:")
        print("  - Significantly better testability")
        print("  - Easier maintenance")
        print("  - Better separation of concerns")
        print("  - Ability to scale team development")


@pytest.mark.performance
class TestScalabilityBenchmarks:
    """Test scalability characteristics of the new architecture."""

    async def test_memory_leak_check(self, client, mock_graphiti_client):
        """Check for memory leaks with repeated requests."""
        import gc

        mock_graphiti_client.health_probe = AsyncMock(return_value=True)

        # Force garbage collection
        gc.collect()

        # Get initial memory size
        initial_objects = len(gc.get_objects())

        # Make many requests
        for _ in range(100):
            response = await client.get("/api/v1/episodes/health")
            assert response.status_code == 200

        assert mock_graphiti_client.health_probe.await_count == 100

        # Force garbage collection again
        gc.collect()

        # Get final memory size
        final_objects = len(gc.get_objects())

        # Check for significant memory growth
        growth = final_objects - initial_objects
        growth_percent = (growth / initial_objects) * 100

        print("\nMemory Leak Check:")
        print(f"  Initial objects: {initial_objects}")
        print(f"  Final objects: {final_objects}")
        print(f"  Growth: {growth} ({growth_percent:.2f}%)")

        # Allow some growth but not excessive
        assert growth_percent < 20, f"Possible memory leak: {growth_percent:.2f}% growth"

    async def test_database_connection_pool(self, client):
        """Exercise concurrent database-backed HTTP requests using the SQLite test engine."""

        # Make many concurrent database requests
        async def db_request():
            response = await client.get("/api/v1/projects/")
            return response

        start_time = time.perf_counter()

        # 100 concurrent requests
        tasks = [db_request() for _ in range(100)]
        responses = await asyncio.gather(*tasks)

        end_time = time.perf_counter()

        successful = sum(1 for r in responses if r.status_code == 200)
        avg_time = ((end_time - start_time) / 100) * 1000

        print("\nConcurrent SQLite HTTP Request Test:")
        print("  Concurrent requests: 100")
        print(f"  Successful: {successful}/100")
        print(f"  Average time: {avg_time:.2f}ms")
        print(f"  Total time: {end_time - start_time:.2f}s")

        assert successful >= 95, f"Too many failed requests: {successful}/100"


# Helper functions for running benchmarks


def run_benchmark(func: callable, iterations: int = 100) -> dict:
    """
    Run a benchmark function multiple times and return statistics.

    Args:
        func: Function to benchmark
        iterations: Number of iterations

    Returns:
        Dictionary with benchmark statistics
    """
    times = []

    for _ in range(iterations):
        start = time.perf_counter()
        func()
        end = time.perf_counter()
        times.append((end - start) * 1000)  # Convert to ms

    return {
        "min": min(times),
        "max": max(times),
        "avg": sum(times) / len(times),
        "median": sorted(times)[len(times) // 2],
        "p95": sorted(times)[int(len(times) * 0.95)],
        "p99": sorted(times)[int(len(times) * 0.99)],
    }


if __name__ == "__main__":
    # Run benchmarks directly
    print("Running performance benchmarks...")
    print("Note: Run with pytest for full integration:")
    print("  pytest src/tests/performance/ -v -m performance")
