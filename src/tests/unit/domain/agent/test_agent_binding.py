"""Unit tests for the AgentBinding domain entity."""

import dataclasses

import pytest

from src.domain.model.agent.agent_binding import AgentBinding


def _make_binding(**overrides):
    defaults = {
        "id": "binding-1",
        "tenant_id": "tenant-1",
        "agent_id": "agent-1",
    }
    defaults.update(overrides)
    return AgentBinding(**defaults)


@pytest.mark.unit
class TestAgentBinding:
    def test_create_binding_defaults(self):
        binding = _make_binding()
        assert binding.channel_type is None
        assert binding.channel_id is None
        assert binding.account_id is None
        assert binding.peer_id is None
        assert binding.priority == 0
        assert binding.enabled is True

    def test_create_binding_empty_id_raises(self):
        with pytest.raises(ValueError, match="id cannot be empty"):
            _make_binding(id="")

    def test_create_binding_empty_tenant_id_raises(self):
        with pytest.raises(ValueError, match="tenant_id cannot be empty"):
            _make_binding(tenant_id="")

    def test_create_binding_empty_agent_id_raises(self):
        with pytest.raises(ValueError, match="agent_id cannot be empty"):
            _make_binding(agent_id="")

    def test_create_binding_negative_priority_raises(self):
        with pytest.raises(ValueError, match="priority must be non-negative"):
            _make_binding(priority=-1)

    def test_specificity_score_all_none(self):
        binding = _make_binding()
        assert binding.specificity_score == 0

    def test_specificity_score_channel_type_only(self):
        binding = _make_binding(channel_type="slack")
        assert binding.specificity_score == 1

    def test_specificity_score_channel_id_only(self):
        binding = _make_binding(channel_id="ch-123")
        assert binding.specificity_score == 2

    def test_specificity_score_account_id_only(self):
        binding = _make_binding(account_id="acc-1")
        assert binding.specificity_score == 4

    def test_specificity_score_peer_id_only(self):
        binding = _make_binding(peer_id="peer-1")
        assert binding.specificity_score == 8

    def test_specificity_score_all_set(self):
        binding = _make_binding(
            channel_type="slack",
            channel_id="ch-1",
            account_id="acc-1",
            peer_id="peer-1",
        )
        assert binding.specificity_score == 15

    def test_specificity_score_with_priority(self):
        binding = _make_binding(
            channel_type="slack",
            channel_id="ch-1",
            account_id="acc-1",
            peer_id="peer-1",
            priority=10,
        )
        assert binding.specificity_score == 25

    def test_frozen_immutability(self):
        binding = _make_binding()
        with pytest.raises(dataclasses.FrozenInstanceError):
            binding.priority = 5  # type: ignore[misc]

    def test_to_dict_includes_specificity_score(self):
        binding = _make_binding()
        d = binding.to_dict()
        assert "specificity_score" in d
        assert d["specificity_score"] == 0

    def test_to_dict_from_dict_round_trip(self):
        binding = _make_binding(
            channel_type="slack",
            channel_id="ch-1",
            account_id="acc-1",
            peer_id="peer-1",
            priority=5,
            enabled=False,
        )
        d = binding.to_dict()
        restored = AgentBinding.from_dict(d)
        assert restored.id == binding.id
        assert restored.tenant_id == binding.tenant_id
        assert restored.agent_id == binding.agent_id
        assert restored.channel_type == binding.channel_type
        assert restored.channel_id == binding.channel_id
        assert restored.account_id == binding.account_id
        assert restored.peer_id == binding.peer_id
        assert restored.priority == binding.priority
        assert restored.enabled == binding.enabled
