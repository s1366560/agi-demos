"""Agent First guardrail — static scan of semantic gate modules.

Enforces the top-level Agent First rule: modules responsible for
**subjective-looking decisions** (routing, HITL policy, termination) MUST
NOT contain regex / NLP / keyword-list / string-heuristic code paths that
substitute for an Agent call.

This is a *guardrail*, not a proof: new modules added to the allow-list
must either be free of the banned markers or explicitly comment them out
of scope. Allow-list lives in this file so changes to it show up in code
review.

Strict scope (files scanned):
    * ``src/domain/model/agent/conversation/hitl_policy.py``
    * ``src/domain/model/agent/conversation/termination.py``
    * selected routing modules
    * ``src/application/services/agent/termination_service.py``

Runtime gate scope additionally checks workspace supervisor/verifier,
category routing, skill/subagent matching, and tool selection for known
text-heuristic control flow markers.

Banned markers:
    * ``re.`` / ``re.compile`` / ``re.match`` / ``re.search``
    * ``fnmatch`` (glob matching over NL)
    * ``startswith("@")`` / ``endswith("?")`` / ``.lower()`` over message
      content (approximated by heuristic).
    * Hard-coded keyword lists used as control flow (approximated by
      ``KEYWORDS = {...}`` or ``BLOCKED_PHRASES``).

Allowed structural helpers (enum compare, set membership, arithmetic) are
excluded by construction — they do not use ``re``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[4]

_GUARDED_FILES: tuple[Path, ...] = (
    _REPO_ROOT / "src/domain/model/agent/conversation/hitl_policy.py",
    _REPO_ROOT / "src/domain/model/agent/conversation/termination.py",
    _REPO_ROOT / "src/application/services/agent/termination_service.py",
    _REPO_ROOT / "src/infrastructure/agent/routing/conversation_aware_router.py",
)

# Legacy routers that currently use regex for user-configurable binding
# patterns. They predate the Agent First rule. Flagged here so future cleanup
# is discoverable; not a current failure.
_LEGACY_ROUTERS: tuple[Path, ...] = (
    _REPO_ROOT / "src/infrastructure/agent/routing/default_message_router.py",
    _REPO_ROOT / "src/infrastructure/agent/routing/binding_router.py",
    _REPO_ROOT / "src/infrastructure/agent/routing/execution_router.py",
)

_RUNTIME_GATE_FILES: tuple[Path, ...] = (
    _REPO_ROOT / "src/infrastructure/agent/workspace_plan/allocator.py",
    _REPO_ROOT / "src/infrastructure/agent/workspace_plan/factory.py",
    _REPO_ROOT / "src/infrastructure/agent/workspace_plan/outbox_handlers.py",
    _REPO_ROOT / "src/infrastructure/agent/workspace_plan/supervisor.py",
    _REPO_ROOT / "src/infrastructure/agent/workspace_plan/verifier.py",
    _REPO_ROOT / "src/infrastructure/agent/core/react_agent.py",
    _REPO_ROOT / "src/infrastructure/agent/core/react_agent_routing_mixin.py",
    _REPO_ROOT / "src/infrastructure/agent/core/tool_selector.py",
    _REPO_ROOT / "src/infrastructure/agent/routing/intent_gate.py",
    _REPO_ROOT / "src/infrastructure/llm/category_router.py",
    _REPO_ROOT / "src/infrastructure/adapters/secondary/persistence/sql_subagent_repository.py",
)


_BANNED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("import re", re.compile(r"^\s*import\s+re(\s|$)", re.MULTILINE)),
    ("from re ", re.compile(r"^\s*from\s+re\s+import", re.MULTILINE)),
    ("fnmatch", re.compile(r"\bfnmatch\b")),
    (
        "KEYWORDS collection",
        re.compile(
            r"\b(KEYWORDS|BLOCKED_PHRASES|INTENT_WORDS|TRIGGER_WORDS|BANNED_WORDS)\s*=",
        ),
    ),
    # content.lower() style parsing usually implies NL classification
    (".lower() on content", re.compile(r"\.content\s*\.\s*lower\s*\(")),
    # heuristic phrase match
    ("content.startswith", re.compile(r"\.content\s*\.\s*startswith\s*\(")),
)

_TEXT_GATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("category keyword tables", re.compile(r"_\w+_KEYWORDS\s*=")),
    ("category word regex", re.compile(r"_WORD_RE|re\.findall")),
    ("tool keyword ranker", re.compile(r"KeywordSemanticToolRanker|TokenVectorSemanticToolRanker")),
    ("tool keyword extraction", re.compile(r"_extract_keywords|semantic_backend[^\n]+keyword")),
    ("transient infra marker table", re.compile(r"_TRANSIENT_INFRA_FAILURE_MARKERS")),
    ("retry action prose parsing", re.compile(r'"retry verification"\s+in|casefold\(\).*retry')),
    ("blocked report short circuit", re.compile(r"_should_short_circuit_blocked_worker_report\(")),
    ("description affinity parsing", re.compile(r"node\.description\.lower\(")),
    ("implicit skill query scoring", re.compile(r"score\s*=\s*skill\.matches_query\(")),
    ("implicit subagent router", re.compile(r"subagent_router\.match\(")),
    ("subagent keyword repository gate", re.compile(r"\.matches_keywords\(")),
    ("domain lane keyword table", re.compile(r"_DOMAIN_LANE_RULES")),
    ("intent gate runtime classify call", re.compile(r"_intent_gate\.classify\(")),
    ("previous attempt prose markers", re.compile(r"previous_reason|provider.*previous_attempt")),
)


def _load(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _executable_code(path: Path) -> str:
    source = _load(path)
    code_lines = [
        line for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    code = "\n".join(code_lines)
    code = re.sub(r'"""[\s\S]*?"""', "", code)
    return re.sub(r"'''[\s\S]*?'''", "", code)


@pytest.mark.parametrize("path", _GUARDED_FILES, ids=lambda p: p.name)
def test_no_forbidden_nl_patterns(path: Path) -> None:
    """Each guarded file must be free of regex / keyword / NL heuristics."""
    assert path.exists(), f"guarded file disappeared: {path}"
    code = _executable_code(path)

    violations: list[str] = []
    for label, pattern in _BANNED_PATTERNS:
        match = pattern.search(code)
        if match:
            snippet = match.group(0)
            violations.append(f"{label!r} matched {snippet!r}")

    assert not violations, (
        f"Agent First violation in {path.relative_to(_REPO_ROOT)}:\n"
        + "\n".join(f"  - {v}" for v in violations)
        + "\n(structural routing/policy/termination modules must not use "
        "regex or keyword-list NLP — route through an Agent instead.)"
    )


@pytest.mark.parametrize("path", _RUNTIME_GATE_FILES, ids=lambda p: p.name)
def test_runtime_gate_files_do_not_use_text_heuristic_control_flow(path: Path) -> None:
    """Runtime gate files must not route/classify by natural-language snippets."""
    assert path.exists(), f"guarded runtime file disappeared: {path}"
    code = _executable_code(path)
    violations: list[str] = []
    for label, pattern in _TEXT_GATE_PATTERNS:
        match = pattern.search(code)
        if match:
            violations.append(f"{label!r} matched {match.group(0)!r}")

    assert not violations, (
        f"Agent First runtime gate violation in {path.relative_to(_REPO_ROOT)}:\n"
        + "\n".join(f"  - {v}" for v in violations)
        + "\n(semantic verdicts must use structured agent/broker output.)"
    )


def test_allowlist_is_non_empty_and_resolved() -> None:
    """Sanity: the allow-list must actually point at real files, so a rename
    cannot silently bypass the guardrail."""
    assert _GUARDED_FILES, "allow-list empty"
    missing = [p for p in (*_GUARDED_FILES, *_RUNTIME_GATE_FILES) if not p.exists()]
    assert not missing, f"missing guarded files: {missing}"


def test_legacy_routers_are_tracked() -> None:
    """Document the legacy routers that still use regex/NLP heuristics.

    They predate Track B's Agent First rule. This test passes only to keep
    them on a tracked watch-list — a future refactor should migrate each
    one to agent-mediated routing and move it from ``_LEGACY_ROUTERS`` to
    ``_GUARDED_FILES``.
    """
    missing = [p for p in _LEGACY_ROUTERS if not p.exists()]
    assert not missing, f"missing legacy router files: {missing}"
