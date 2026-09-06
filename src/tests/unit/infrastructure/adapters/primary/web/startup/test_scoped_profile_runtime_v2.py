"""Actual repository Bundle, SQL configuration, scoped Loader and admitted operation."""

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2, ServiceRequiredV2
from src.infrastructure.adapters.primary.web.startup.plugin_trust_v2 import (
    configure_plugin_trust_v2,
)
from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
    initialize_scoped_profile_runtime_v2,
    shutdown_scoped_profile_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_SERVICE_V2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import compose_profile_sources_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.scoped_boundary import pin_scoped_agent_turn_operation_v2
from src.infrastructure.plugins.v2.service_closure import project_service_closure_v2

pytestmark = pytest.mark.unit


async def test_production_startup_component_consumes_actual_builtin_source(db_session):
    source = production_bundle_sources_v2()
    scope = ScopeV2(kind=ScopeKindV2.SESSION, tenant_id="t", project_id="p", session_id="s")
    root_scope = ScopeV2(kind=ScopeKindV2.ROOT)
    requirements = (
        ServiceRequiredV2(service=RUNTIME_BOUNDARY_SERVICE_V2, version="1.0.0", alias="boundary"),
    )
    composition = compose_profile_sources_v2(
        desired_set=source.desired_set,
        bundles=(source.bundle,),
        profile_source=source.profile_source,
        scope=root_scope,
    )
    snapshot = compose_profile_v2(
        composition.document, {m.plugin_id: m for m in composition.manifests}, generation=1
    )
    projected = project_service_closure_v2(
        snapshot, scope=root_scope, required_services=requirements
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    assert (await host.apply(projected, control_envelope_v2(projected, version=1))).accepted
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as session:
        await PlatformPluginProfileSourceRepositoryV2(session).record_source(
            scope=scope, source=source.profile_source, expected_revision=None
        )
        await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
            scope=scope, desired_set=source.desired_set, expected_revision=None, actor_id="fixture"
        )
        await session.commit()
    app = FastAPI()
    app.state.platform_plugin_runtime_v2 = host
    configure_plugin_trust_v2(app, key_files=(), allowed_registries=())
    runtime = initialize_scoped_profile_runtime_v2(app, session_factory=factory, redis_client=None)
    try:
        result = await runtime.publish_current(scope, required_services=requirements)
        assert result.publication.accepted
        reservation = await runtime.acquire(scope)
        assert reservation.lease.generation is not host.manager.current
        await shutdown_scoped_profile_runtime_v2(app)
        assert app.state.scoped_profile_runtime_v2 is None
        with pytest.raises(RuntimeV2Error, match="closed"):
            await runtime.acquire(scope)
        async with pin_scoped_agent_turn_operation_v2(
            reservation, operation_id="real-builtin", tenant_id="t", project_id="p", session_id="s"
        ) as operation:
            assert operation.require(RUNTIME_BOUNDARY_SERVICE_V2).protocol_version == 2
        await shutdown_scoped_profile_runtime_v2(app)
    finally:
        await runtime.close()
        await host.close()


def test_startup_requires_active_root_and_explicit_trust(db_session):
    app = FastAPI()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    with pytest.raises(RuntimeError, match="root"):
        initialize_scoped_profile_runtime_v2(app, session_factory=factory, redis_client=None)
