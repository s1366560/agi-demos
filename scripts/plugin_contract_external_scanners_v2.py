"""Subprocess adapters for Rust and TypeScript protocol-v2 completeness scanners."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2

if TYPE_CHECKING:
    from scripts.plugin_contract_completeness_support_v2 import (
        ContractCompletenessIssueV2,
        _contract_declarations,
        _ManifestModuleV2,
        _relative,
    )
elif __package__:
    from .plugin_contract_completeness_support_v2 import (
        ContractCompletenessIssueV2,
        _contract_declarations,
        _ManifestModuleV2,
        _relative,
    )
else:
    from plugin_contract_completeness_support_v2 import (
        ContractCompletenessIssueV2,
        _contract_declarations,
        _ManifestModuleV2,
        _relative,
    )

ROOT = Path(__file__).resolve().parents[1]
RUST_SCANNER_MANIFEST_V2 = ROOT / "agi-stack/tools/plugin-contract-completeness-v2/Cargo.toml"
TYPESCRIPT_SCANNER_PATH_V2 = ROOT / "scripts/check_plugin_contract_completeness_v2_ts.mjs"

_EXTERNAL_ARTIFACT_V2 = {
    "rust": ("repo+rust://", frozenset({".rs"})),
    "typescript": ("repo+typescript://", frozenset({".ts", ".tsx"})),
}


def check_external_entrypoint_v2(
    root: Path,
    module: _ManifestModuleV2,
    language: str,
    issues: list[ContractCompletenessIssueV2],
) -> None:
    """Attest exact source bytes, then invoke the language-owned AST scanner."""
    attested = _attested_external_source(root, module, language, issues)
    if attested is None:
        return
    source_path, source = attested
    issue_count = len(issues)
    declarations = _contract_declarations(module, _relative(source_path, root), issues)
    if len(issues) != issue_count:
        return
    request = {
        "source": source,
        "entrypoint": module.entrypoint,
        "declarations": {method: sorted(values) for method, values in sorted(declarations.items())},
    }
    command = _scanner_command_v2(language)
    if command is None:
        issues.append(
            ContractCompletenessIssueV2(
                code="scanner_unavailable",
                path=_relative(module.path, root),
                module_ref=module.module_ref,
                detail=f"{language} contract completeness scanner is unavailable",
            )
        )
        return
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            input=json.dumps(request, separators=(",", ":")),
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        issues.append(
            ContractCompletenessIssueV2(
                code="scanner_failed",
                path=_relative(source_path, root),
                module_ref=module.module_ref,
                detail=f"{language} scanner failed: {exc}",
            )
        )
        return
    if result.returncode != 0:
        detail = result.stderr.strip() or f"scanner exited with status {result.returncode}"
        issues.append(
            ContractCompletenessIssueV2(
                code="scanner_failed",
                path=_relative(source_path, root),
                module_ref=module.module_ref,
                detail=f"{language} scanner failed: {detail[:2000]}",
            )
        )
        return
    _append_external_scanner_issues(root, source_path, module, result.stdout, issues)


def _attested_external_source(
    root: Path,
    module: _ManifestModuleV2,
    language: str,
    issues: list[ContractCompletenessIssueV2],
) -> tuple[Path, str] | None:
    prefix, extensions = _EXTERNAL_ARTIFACT_V2[language]
    if not module.artifact_source.startswith(prefix):
        issues.append(
            ContractCompletenessIssueV2(
                code="artifact_source_mismatch",
                path=_relative(module.path, root),
                module_ref=module.module_ref,
                detail=f"{language} artifact source must start with {prefix}",
            )
        )
        return None
    raw_path = module.artifact_source.removeprefix(prefix)
    relative = PurePosixPath(raw_path)
    if (
        not raw_path
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.suffix not in extensions
        or relative.as_posix() != raw_path
    ):
        issues.append(
            ContractCompletenessIssueV2(
                code="artifact_source_mismatch",
                path=_relative(module.path, root),
                module_ref=module.module_ref,
                detail=f"{language} artifact source is not a canonical repository path",
            )
        )
        return None
    source_path = (root / Path(*relative.parts)).resolve()
    if not source_path.is_relative_to(root) or not source_path.is_file():
        issues.append(
            ContractCompletenessIssueV2(
                code="artifact_resolution_failed",
                path=_relative(module.path, root),
                module_ref=module.module_ref,
                detail=f"{language} artifact source is unavailable",
            )
        )
        return None
    try:
        source_bytes = source_path.read_bytes()
        source = source_bytes.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        issues.append(
            ContractCompletenessIssueV2(
                code="artifact_resolution_failed",
                path=_relative(source_path, root),
                module_ref=module.module_ref,
                detail=str(exc),
            )
        )
        return None
    actual_digest = artifact_digest_v2(source_bytes)
    if actual_digest != module.artifact_digest:
        issues.append(
            ContractCompletenessIssueV2(
                code="artifact_digest_mismatch",
                path=_relative(source_path, root),
                module_ref=module.module_ref,
                detail=f"manifest has {module.artifact_digest}; actual bytes are {actual_digest}",
            )
        )
    return source_path, source


def _scanner_command_v2(language: str) -> list[str] | None:
    if language == "rust" and RUST_SCANNER_MANIFEST_V2.is_file():
        return [
            "cargo",
            "run",
            "--quiet",
            "--manifest-path",
            str(RUST_SCANNER_MANIFEST_V2),
            "--",
        ]
    if language == "typescript" and TYPESCRIPT_SCANNER_PATH_V2.is_file():
        return ["node", str(TYPESCRIPT_SCANNER_PATH_V2)]
    return None


def _append_external_scanner_issues(
    root: Path,
    source_path: Path,
    module: _ManifestModuleV2,
    output: str,
    issues: list[ContractCompletenessIssueV2],
) -> None:
    try:
        payload = cast("object", json.loads(output))
        if not isinstance(payload, dict) or set(payload) != {"issues"}:
            raise TypeError("scanner response must contain only an issues array")
        rows = payload["issues"]
        if not isinstance(rows, list):
            raise TypeError("scanner response must contain only an issues array")
        for raw_row in rows:
            if not isinstance(raw_row, dict) or set(raw_row) != {"code", "line", "detail"}:
                raise TypeError("scanner issue has an invalid shape")
            row = cast("dict[str, Any]", raw_row)
            code = row["code"]
            line = row["line"]
            detail = row["detail"]
            if (
                not isinstance(code, str)
                or not isinstance(detail, str)
                or (line is not None and (not isinstance(line, int) or isinstance(line, bool)))
            ):
                raise TypeError("scanner issue fields have invalid types")
            issues.append(
                ContractCompletenessIssueV2(
                    code=code,
                    path=_relative(source_path, root),
                    module_ref=module.module_ref,
                    line=line,
                    detail=detail,
                )
            )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        issues.append(
            ContractCompletenessIssueV2(
                code="scanner_failed",
                path=_relative(source_path, root),
                module_ref=module.module_ref,
                detail=f"scanner returned invalid JSON: {exc}",
            )
        )


__all__ = ["check_external_entrypoint_v2"]
