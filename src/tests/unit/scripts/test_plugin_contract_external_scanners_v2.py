"""Cross-runtime AST scanner tests for protocol-v2 contract completeness."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import (
    check_plugin_contract_completeness_v2 as completeness_gate_v2,
    plugin_contract_external_scanners_v2 as external_scanners_v2,
)
from scripts.check_plugin_contract_completeness_v2 import check_repository
from src.tests.unit.scripts.test_plugin_contract_completeness_v2 import (
    _contract,
    _write_external_repository,
)


@pytest.mark.unit
@pytest.mark.parametrize("target", ["rust-server", "desktop-sidecar"])
def test_rust_scanner_accepts_declared_literal_calls(tmp_path: Path, target: str) -> None:
    _write_external_repository(
        tmp_path,
        target=target,
        language="rust",
        entrypoint="example::apply",
        contract=_contract(
            provides=("service:clock",),
            requires=(("database", "service:database"),),
            handles=("event:changed",),
            emits=("event:requested",),
        ),
        source="""
const CLOCK_SERVICE: &str = "service:clock";

async fn apply(context: &mut ContextV2) -> Result<(), RuntimeV2Error> {
    context.provide(CLOCK_SERVICE, ())?;
    context.require::<()>("database")?;
    context.on("event:changed", |payload| async move { Ok(payload) })?;
    context.dispatch("event:requested", Value::Null).await?;
    Ok(())
}
""",
    )

    assert check_repository(tmp_path) == ()


@pytest.mark.unit
def test_rust_scanner_rejects_dynamic_contract_key(tmp_path: Path) -> None:
    _write_external_repository(
        tmp_path,
        target="rust-server",
        language="rust",
        contract=_contract(provides=("service:clock",)),
        source="""
fn apply(context: &mut ContextV2) -> Result<(), RuntimeV2Error> {
    let service = "service:clock";
    context.provide(service, ())?;
    Ok(())
}
""",
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["unclassified_context_call"]
    assert "provide" in issues[0].detail


@pytest.mark.unit
def test_rust_scanner_rejects_undeclared_literal(tmp_path: Path) -> None:
    _write_external_repository(
        tmp_path,
        target="rust-server",
        language="rust",
        contract=_contract(),
        source="""
fn apply(context: &mut ContextV2) -> Result<(), RuntimeV2Error> {
    context.on("event:other", |payload| async move { Ok(payload) })?;
    Ok(())
}
""",
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["undeclared_context_call"]
    assert "on event:other" in issues[0].detail


@pytest.mark.unit
@pytest.mark.parametrize("target", ["web", "desktop-renderer"])
def test_typescript_scanner_accepts_declared_literal_calls(tmp_path: Path, target: str) -> None:
    _write_external_repository(
        tmp_path,
        target=target,
        language="typescript",
        contract=_contract(
            provides=("service:clock",),
            requires=(("database", "service:database"),),
            handles=("event:changed",),
            emits=("event:requested",),
        ),
        source="""
const CLOCK_SERVICE = 'service:clock';

export async function apply(context: ContextV2): Promise<void> {
  context.provide(CLOCK_SERVICE, {});
  context.require('database');
  context.on('event:changed', async (payload) => payload);
  await context.dispatch('event:requested', {});
}
""",
    )

    assert check_repository(tmp_path) == ()


@pytest.mark.unit
@pytest.mark.parametrize(
    "call",
    [
        "context.provide(service, {});",
        "context[method]('service:clock', {});",
        "const provide = context.provide; provide('service:clock', {});",
    ],
)
def test_typescript_scanner_rejects_unclassified_context_call(
    tmp_path: Path,
    call: str,
) -> None:
    _write_external_repository(
        tmp_path,
        target="web",
        language="typescript",
        contract=_contract(provides=("service:clock",)),
        source=f"""
export function apply(context: ContextV2, service: string, method: 'provide'): void {{
  {call}
}}
""",
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["unclassified_context_call"]


@pytest.mark.unit
def test_typescript_scanner_rejects_undeclared_literal(tmp_path: Path) -> None:
    _write_external_repository(
        tmp_path,
        target="web",
        language="typescript",
        contract=_contract(),
        source="""
export function apply(context: ContextV2): void {
  context.require('other');
}
""",
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["undeclared_context_call"]
    assert "require other" in issues[0].detail


@pytest.mark.unit
@pytest.mark.parametrize(
    ("language", "target", "source"),
    [
        (
            "rust",
            "rust-server",
            """
fn register(context: &mut ContextV2) {
    context.provide("service:other", ());
}

fn apply(context: &mut ContextV2) {
    register(context);
}
""",
        ),
        (
            "typescript",
            "web",
            """
function register(context: ContextV2): void {
  context.provide('service:other', {});
}

export function apply(context: ContextV2): void {
  register(context);
}
""",
        ),
    ],
)
def test_external_scanners_follow_reachable_local_helpers(
    tmp_path: Path,
    language: str,
    target: str,
    source: str,
) -> None:
    _write_external_repository(
        tmp_path,
        target=target,
        language=language,
        contract=_contract(),
        source=source,
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["undeclared_context_call"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("language", "target", "source"),
    [
        (
            "rust",
            "rust-server",
            "fn apply(context: &mut OtherContext) {}\n",
        ),
        (
            "typescript",
            "web",
            "export function apply(context: OtherContext): void {}\n",
        ),
    ],
)
def test_external_entrypoint_without_typed_context_fails_closed(
    tmp_path: Path,
    language: str,
    target: str,
    source: str,
) -> None:
    _write_external_repository(
        tmp_path,
        target=target,
        language=language,
        contract=_contract(),
        source=source,
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["unclassified_entrypoint_context"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("language", "target", "entrypoint", "source"),
    [
        (
            "rust",
            "rust-server",
            "PluginB::apply",
            """
struct PluginA;
struct PluginB;

impl PluginA {
    fn apply(context: &mut ContextV2) {
        context.provide("service:wrong", ());
    }
}

impl PluginB {
    fn apply(_context: &mut ContextV2) {}
}
""",
        ),
        (
            "typescript",
            "web",
            "PluginB.apply",
            """
class PluginA {
  static apply(context: ContextV2): void {
    context.provide('service:wrong', {});
  }
}

export class PluginB {
  static apply(_context: ContextV2): void {}
}
""",
        ),
    ],
)
def test_external_scanner_selects_qualified_apply_entrypoint(
    tmp_path: Path,
    language: str,
    target: str,
    entrypoint: str,
    source: str,
) -> None:
    _write_external_repository(
        tmp_path,
        target=target,
        language=language,
        entrypoint=entrypoint,
        contract=_contract(),
        source=source,
    )

    assert check_repository(tmp_path) == ()


@pytest.mark.unit
def test_external_artifact_byte_drift_fails_attestation(tmp_path: Path) -> None:
    _write_external_repository(
        tmp_path,
        target="web",
        language="typescript",
        contract=_contract(),
        source="export function apply(_context: ContextV2): void {}\n",
    )
    (tmp_path / "src/example/plugin.ts").write_text(
        "export function apply(_context: ContextV2): void { throw new Error(); }\n",
        encoding="utf-8",
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["artifact_digest_mismatch"]


@pytest.mark.unit
def test_malformed_external_scanner_response_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_external_repository(
        tmp_path,
        target="web",
        language="typescript",
        contract=_contract(),
        source="export function apply(_context: ContextV2): void {}\n",
    )
    result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='{"issues":"invalid"}',
        stderr="",
    )
    monkeypatch.setattr(external_scanners_v2.subprocess, "run", lambda *args, **kwargs: result)

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["scanner_failed"]


@pytest.mark.unit
def test_targets_using_same_language_are_scanned_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_external_repository(
        tmp_path,
        target="web",
        targets=("web", "desktop-renderer"),
        language="typescript",
        contract=_contract(),
        source="export function apply(_context: ContextV2): void {}\n",
    )
    calls: list[str] = []

    def record_scan(
        _root: Path,
        _module: object,
        language: str,
        _issues: list[object],
    ) -> None:
        calls.append(language)

    monkeypatch.setattr(completeness_gate_v2, "check_external_entrypoint_v2", record_scan)

    assert check_repository(tmp_path) == ()
    assert calls == ["typescript"]
