"""Unit tests for Temporal Episode Activities."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestAddEpisodeActivity:
    """Test cases for add_episode_activity."""

    @pytest.fixture
    def mock_graph_service(self):
        """Create mock graph service."""
        service = MagicMock()
        service.client = MagicMock()
        service.client.execute_query = AsyncMock()
        service.process_episode = AsyncMock()
        service.community_updater = MagicMock()
        service.community_updater.update_communities_for_entities = AsyncMock()
        return service

    @pytest.fixture
    def sample_payload(self):
        """Create sample episode payload."""
        return {
            "uuid": "ep_test_123",
            "content": "Test episode content for processing",
            "name": "Test Episode",
            "group_id": "proj_123",
            "project_id": "proj_123",
            "tenant_id": "tenant_123",
            "user_id": "user_123",
            "memory_id": "mem_123",
            "task_id": "task_123",
        }

    @pytest.mark.asyncio
    async def test_add_episode_success(self, mock_graph_service, sample_payload):
        """Test successful episode processing."""
        from src.infrastructure.adapters.secondary.temporal.activities.episode import (
            add_episode_activity,
        )

        # Setup mock result
        mock_result = MagicMock()
        mock_result.nodes = [MagicMock(uuid="entity_1"), MagicMock(uuid="entity_2")]
        mock_result.edges = [MagicMock(), MagicMock(), MagicMock()]
        mock_graph_service.process_episode.return_value = mock_result

        # Mock activity.info()
        mock_info = MagicMock()
        mock_info.workflow_id = "wf_test_123"
        mock_info.attempt = 1

        with (
            patch(
                "src.infrastructure.adapters.secondary.temporal.worker_state.get_graph_service",
                return_value=mock_graph_service,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.activity"
            ) as mock_activity,
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.update_task_progress",
                new_callable=AsyncMock,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.update_memory_status",
                new_callable=AsyncMock,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.mark_task_completed",
                new_callable=AsyncMock,
            ),
        ):
            mock_activity.info.return_value = mock_info

            # Act
            result = await add_episode_activity(sample_payload)

            # Assert
            assert result["status"] == "completed"
            assert result["episode_uuid"] == "ep_test_123"
            assert result["entity_count"] == 2
            assert result["relationship_count"] == 3
            mock_graph_service.process_episode.assert_called_once_with(
                episode_uuid="ep_test_123",
                content="Test episode content for processing",
                project_id="proj_123",
                tenant_id="tenant_123",
                user_id="user_123",
            )

    @pytest.mark.asyncio
    async def test_add_episode_no_graph_service(self, sample_payload):
        """Test activity fails when graph service not initialized."""
        from src.infrastructure.adapters.secondary.temporal.activities.episode import (
            add_episode_activity,
        )

        mock_info = MagicMock()
        mock_info.workflow_id = "wf_test_123"
        mock_info.attempt = 1

        with (
            patch(
                "src.infrastructure.adapters.secondary.temporal.worker_state.get_graph_service",
                return_value=None,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.activity"
            ) as mock_activity,
        ):
            mock_activity.info.return_value = mock_info

            # Act & Assert
            with pytest.raises(RuntimeError, match="Graph service not initialized"):
                await add_episode_activity(sample_payload)

    @pytest.mark.asyncio
    async def test_add_episode_processing_failure(self, mock_graph_service, sample_payload):
        """Test activity handles processing failure correctly."""
        from src.infrastructure.adapters.secondary.temporal.activities.episode import (
            add_episode_activity,
        )

        # Setup failure
        mock_graph_service.process_episode.side_effect = Exception("LLM extraction failed")

        mock_info = MagicMock()
        mock_info.workflow_id = "wf_test_123"
        mock_info.attempt = 1

        with (
            patch(
                "src.infrastructure.adapters.secondary.temporal.worker_state.get_graph_service",
                return_value=mock_graph_service,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.activity"
            ) as mock_activity,
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.update_task_progress",
                new_callable=AsyncMock,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.update_memory_status",
                new_callable=AsyncMock,
            ) as mock_update_memory,
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.mark_task_failed",
                new_callable=AsyncMock,
            ) as mock_mark_failed,
        ):
            mock_activity.info.return_value = mock_info

            # Act & Assert
            with pytest.raises(Exception, match="LLM extraction failed"):
                await add_episode_activity(sample_payload)

            # Verify failure handling
            mock_mark_failed.assert_called_once()
            # Memory status should be updated to FAILED
            assert mock_update_memory.call_count >= 1

    @pytest.mark.asyncio
    async def test_add_episode_no_entities_extracted(self, mock_graph_service, sample_payload):
        """Test activity handles empty extraction result."""
        from src.infrastructure.adapters.secondary.temporal.activities.episode import (
            add_episode_activity,
        )

        # Setup empty result
        mock_result = MagicMock()
        mock_result.nodes = []
        mock_result.edges = []
        mock_graph_service.process_episode.return_value = mock_result

        mock_info = MagicMock()
        mock_info.workflow_id = "wf_test_123"
        mock_info.attempt = 1

        with (
            patch(
                "src.infrastructure.adapters.secondary.temporal.worker_state.get_graph_service",
                return_value=mock_graph_service,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.activity"
            ) as mock_activity,
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.update_task_progress",
                new_callable=AsyncMock,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.update_memory_status",
                new_callable=AsyncMock,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.mark_task_completed",
                new_callable=AsyncMock,
            ),
        ):
            mock_activity.info.return_value = mock_info

            # Act
            result = await add_episode_activity(sample_payload)

            # Assert - should still succeed with 0 entities
            assert result["status"] == "completed"
            assert result["entity_count"] == 0
            assert result["relationship_count"] == 0


@pytest.mark.unit
class TestExtractEntitiesActivity:
    """Test cases for extract_entities_activity."""

    @pytest.fixture
    def mock_graph_service(self):
        """Create mock graph service."""
        service = MagicMock()
        service._entity_extractor = MagicMock()
        service._entity_extractor.extract = AsyncMock()
        return service

    @pytest.mark.asyncio
    async def test_extract_entities_success(self, mock_graph_service):
        """Test successful entity extraction."""
        from src.infrastructure.adapters.secondary.temporal.activities.episode import (
            extract_entities_activity,
        )

        # Setup mock result
        mock_entity_1 = MagicMock()
        mock_entity_1.uuid = "entity_1"
        mock_entity_2 = MagicMock()
        mock_entity_2.uuid = "entity_2"

        mock_result = MagicMock()
        mock_result.entities = [mock_entity_1, mock_entity_2]
        mock_graph_service._entity_extractor.extract.return_value = mock_result

        with (
            patch(
                "src.infrastructure.adapters.secondary.temporal.worker_state.get_graph_service",
                return_value=mock_graph_service,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.activity"
            ) as mock_activity,
        ):
            mock_activity.heartbeat = MagicMock()

            # Act
            result = await extract_entities_activity(
                episode_uuid="ep_123",
                content="Test content",
                project_id="proj_123",
                tenant_id="tenant_123",
            )

            # Assert
            assert result["status"] == "completed"
            assert result["entity_count"] == 2
            assert result["entity_ids"] == ["entity_1", "entity_2"]
            mock_activity.heartbeat.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_entities_empty_result(self, mock_graph_service):
        """Test entity extraction with no entities found."""
        from src.infrastructure.adapters.secondary.temporal.activities.episode import (
            extract_entities_activity,
        )

        # Setup empty result
        mock_result = MagicMock()
        mock_result.entities = []
        mock_graph_service._entity_extractor.extract.return_value = mock_result

        with (
            patch(
                "src.infrastructure.adapters.secondary.temporal.worker_state.get_graph_service",
                return_value=mock_graph_service,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.activity"
            ) as mock_activity,
        ):
            mock_activity.heartbeat = MagicMock()

            # Act
            result = await extract_entities_activity(
                episode_uuid="ep_123",
                content="Short text",
                project_id="proj_123",
            )

            # Assert
            assert result["status"] == "completed"
            assert result["entity_count"] == 0
            assert result["entity_ids"] == []

    @pytest.mark.asyncio
    async def test_extract_entities_no_graph_service(self):
        """Test extraction fails when graph service not available."""
        from src.infrastructure.adapters.secondary.temporal.activities.episode import (
            extract_entities_activity,
        )

        with patch(
            "src.infrastructure.adapters.secondary.temporal.worker_state.get_graph_service",
            return_value=None,
        ):
            # Act & Assert
            with pytest.raises(RuntimeError, match="Graph service not initialized"):
                await extract_entities_activity(
                    episode_uuid="ep_123",
                    content="Test content",
                    project_id="proj_123",
                )


@pytest.mark.unit
class TestIncrementalRefreshActivity:
    """Test cases for incremental_refresh_activity."""

    @pytest.fixture
    def mock_graph_service(self):
        """Create mock graph service."""
        service = MagicMock()
        service.client = MagicMock()
        service.client.execute_query = AsyncMock()
        service.process_episode = AsyncMock()
        return service

    @pytest.fixture
    def sample_refresh_payload(self):
        """Create sample refresh payload."""
        return {
            "project_id": "proj_123",
            "tenant_id": "tenant_123",
            "user_id": "user_123",
            "episode_uuids": ["ep_1", "ep_2"],
            "rebuild_communities": False,
            "task_id": "task_refresh_123",
        }

    @pytest.mark.asyncio
    async def test_incremental_refresh_no_episodes(self, mock_graph_service):
        """Test refresh with no episodes to process."""
        from src.infrastructure.adapters.secondary.temporal.activities.episode import (
            incremental_refresh_activity,
        )

        mock_info = MagicMock()
        mock_info.workflow_id = "wf_refresh_123"
        mock_info.attempt = 1

        payload = {
            "project_id": "proj_123",
            "episode_uuids": [],
            "task_id": "task_123",
        }

        with (
            patch(
                "src.infrastructure.adapters.secondary.temporal.worker_state.get_graph_service",
                return_value=mock_graph_service,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.activity"
            ) as mock_activity,
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.update_task_progress",
                new_callable=AsyncMock,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.mark_task_completed",
                new_callable=AsyncMock,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode._get_episodes_by_uuids",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_activity.info.return_value = mock_info

            # Act
            result = await incremental_refresh_activity(payload)

            # Assert
            assert result["status"] == "completed"
            assert result["processed_count"] == 0

    @pytest.mark.asyncio
    async def test_incremental_refresh_no_graph_service(self, sample_refresh_payload):
        """Test refresh fails when graph service not available."""
        from src.infrastructure.adapters.secondary.temporal.activities.episode import (
            incremental_refresh_activity,
        )

        mock_info = MagicMock()
        mock_info.workflow_id = "wf_refresh_123"
        mock_info.attempt = 1

        with (
            patch(
                "src.infrastructure.adapters.secondary.temporal.worker_state.get_graph_service",
                return_value=None,
            ),
            patch(
                "src.infrastructure.adapters.secondary.temporal.activities.episode.activity"
            ) as mock_activity,
        ):
            mock_activity.info.return_value = mock_info

            # Act & Assert
            with pytest.raises(RuntimeError, match="Graph service not initialized"):
                await incremental_refresh_activity(sample_refresh_payload)


@pytest.mark.unit
class TestHelperFunctions:
    """Test cases for helper functions in episode activities."""

    @pytest.mark.asyncio
    async def test_get_episodes_by_uuids_empty(self):
        """Test getting episodes with empty UUID list."""
        from src.infrastructure.adapters.secondary.temporal.activities.episode import (
            _get_episodes_by_uuids,
        )

        mock_client = MagicMock()

        # Act
        result = await _get_episodes_by_uuids(mock_client, [])

        # Assert
        assert result == []
        mock_client.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_episodes_by_uuids_success(self):
        """Test getting episodes by UUIDs."""
        from src.infrastructure.adapters.secondary.temporal.activities.episode import (
            _get_episodes_by_uuids,
        )

        # Setup mock
        mock_record = {
            "uuid": "ep_1",
            "name": "Test Episode",
            "content": "Test content",
            "source_description": "text",
            "valid_at": datetime.now(timezone.utc).isoformat(),
            "project_id": "proj_123",
            "tenant_id": "tenant_123",
            "user_id": "user_123",
        }

        mock_result = MagicMock()
        mock_result.records = [mock_record]

        mock_client = MagicMock()
        mock_client.execute_query = AsyncMock(return_value=mock_result)

        # Act
        result = await _get_episodes_by_uuids(mock_client, ["ep_1"])

        # Assert
        assert len(result) == 1
        assert result[0]["uuid"] == "ep_1"
        assert result[0]["name"] == "Test Episode"

    @pytest.mark.asyncio
    async def test_get_recent_episodes(self):
        """Test getting recent episodes."""
        from src.infrastructure.adapters.secondary.temporal.activities.episode import (
            _get_recent_episodes,
        )

        # Setup mock
        mock_record = {
            "uuid": "ep_recent",
            "name": "Recent Episode",
            "content": "Recent content",
            "source_description": None,
            "valid_at": None,
            "project_id": "proj_123",
            "tenant_id": None,
            "user_id": None,
        }

        mock_result = MagicMock()
        mock_result.records = [mock_record]

        mock_client = MagicMock()
        mock_client.execute_query = AsyncMock(return_value=mock_result)

        # Act
        result = await _get_recent_episodes(mock_client, "proj_123", hours=24, limit=100)

        # Assert
        assert len(result) == 1
        assert result[0]["uuid"] == "ep_recent"
        mock_client.execute_query.assert_called_once()
