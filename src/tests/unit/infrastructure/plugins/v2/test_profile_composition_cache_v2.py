"""Compilation reuse retains exact inputs, isolation and bounded ownership."""

from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.composer import compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import ProfileSourceCompositionV2Error
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.profile_composition_cache import ProfileCompositionCacheV2

pytestmark = pytest.mark.unit


@pytest.fixture
def inputs():
    source = production_bundle_sources_v2()
    return {
        "desired": deepcopy(source.desired_set),
        "source": deepcopy(source.profile_source),
        "bundles": (deepcopy(source.bundle),),
        "scope": ScopeV2(kind=ScopeKindV2.ROOT),
    }


def test_exact_values_reuse_compilation_without_sharing_mappings(inputs):
    cache = ProfileCompositionCacheV2()
    with patch(
        "src.infrastructure.plugins.v2.profile_composition_cache.compose_profile_v2",
        wraps=compose_profile_v2,
    ) as compile_profile:
        first = cache.compose(**inputs)
        first.entries[0].config["changed_by_consumer"] = True
        second = cache.compose(**deepcopy(inputs))
        assert "changed_by_consumer" not in second.entries[0].config
        second.entries[0].config["changed_again"] = True
        assert "changed_again" not in cache.compose(**inputs).entries[0].config
        assert compile_profile.call_count == 1


@pytest.mark.parametrize("value", ["source", "bundle", "desired"])
def test_altered_input_cannot_reuse_old_digest(inputs, value):
    cache = ProfileCompositionCacheV2()
    cache.compose(**inputs)
    if value == "source":
        inputs["source"].layers[0].entries[0].config["tampered"] = True
    elif value == "bundle":
        inputs["bundles"][0].layers[0].entries[0].config["tampered"] = True
    else:
        inputs["desired"] = replace(inputs["desired"], revision=2)
    with pytest.raises(ProfileSourceCompositionV2Error):
        cache.compose(**inputs)


def test_bounded_scope_isolation_and_clear(inputs):
    cache = ProfileCompositionCacheV2(capacity=1)
    project = {**inputs, "scope": ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="t", project_id="p")}
    with patch(
        "src.infrastructure.plugins.v2.profile_composition_cache.compose_profile_v2",
        wraps=compose_profile_v2,
    ) as compile_profile:
        cache.compose(**inputs)
        cache.compose(**project)
        cache.compose(**inputs)
        assert compile_profile.call_count == 3
        cache.clear()
        cache.compose(**inputs)
        assert compile_profile.call_count == 4


def test_capacity_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        ProfileCompositionCacheV2(capacity=0)
