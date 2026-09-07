"""Generation-derived runtime-hook catalog tests."""

from types import SimpleNamespace

import pytest

from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_hook_catalog import runtime_hook_catalog_v2
from src.infrastructure.plugins.v2.sisyphus_runtime import SISYPHUS_BEFORE_REQUEST_MODULE_V2


def _fiber(
    module_ref: str,
    *,
    event: str,
    config: dict[str, object] | None = None,
    schema: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        entry=SimpleNamespace(module_ref=module_ref, config=dict(config or {})),
        contract=SimpleNamespace(
            events=SimpleNamespace(handles=(SimpleNamespace(event=event),)),
            config_schema=dict(schema or {"type": "object"}),
        ),
    )


@pytest.mark.unit
def test_catalog_contains_only_active_v2_lifecycle_fibers() -> None:
    generation = SimpleNamespace(
        fibers=(
            _fiber("builtin://memstack/unrelated", event="unrelated"),
            _fiber(
                SISYPHUS_BEFORE_REQUEST_MODULE_V2,
                event="agent.before_request",
                config={"require_direct_outcome": True},
                schema={
                    "type": "object",
                    "properties": {"require_direct_outcome": {"type": "boolean"}},
                },
            ),
        )
    )

    rows = runtime_hook_catalog_v2(generation)

    assert len(rows) == 1
    assert rows[0].module_ref == SISYPHUS_BEFORE_REQUEST_MODULE_V2
    assert rows[0].plugin_name == "sisyphus-runtime"
    assert rows[0].hook_name == "before_response"
    assert rows[0].default_settings == {"require_direct_outcome": True}
    assert rows[0].settings_schema["properties"] == {
        "require_direct_outcome": {"type": "boolean"}
    }


@pytest.mark.unit
def test_catalog_rejects_runtime_contract_drift() -> None:
    generation = SimpleNamespace(
        fibers=(
            _fiber(
                SISYPHUS_BEFORE_REQUEST_MODULE_V2,
                event="agent.session.start",
            ),
        )
    )

    with pytest.raises(RuntimeV2Error) as exc_info:
        runtime_hook_catalog_v2(generation)

    assert exc_info.value.code == "runtime_hook_contract_mismatch"
