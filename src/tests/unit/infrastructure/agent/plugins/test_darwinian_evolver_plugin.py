"""Tests for the Darwinian Evolver local plugin."""

from __future__ import annotations

import ast
import importlib.util
import json
import pickle
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.infrastructure.agent.plugins.discovery import DiscoveredPlugin, discover_plugins
from src.infrastructure.agent.plugins.manifest import parse_plugin_manifest_payload
from src.infrastructure.agent.plugins.plugin_skill_loader import load_plugin_skills_from_markdown
from src.infrastructure.agent.plugins.state_store import PluginStateStore

pytestmark = pytest.mark.unit

PLUGIN_DIR = Path(__file__).resolve().parents[6] / ".memstack" / "plugins" / "darwinian-evolver"
SKILL_DIR = PLUGIN_DIR / "darwinian-evolver"


class PickledOrganism:
    prompt_template = "Say {{ phrase }}"


def test_manifest_declares_skill_contract() -> None:
    payload = json.loads((PLUGIN_DIR / "memstack.plugin.json").read_text(encoding="utf-8"))

    metadata, diagnostics = parse_plugin_manifest_payload(
        payload,
        plugin_name="darwinian-evolver-plugin",
        manifest_path=str(PLUGIN_DIR / "memstack.plugin.json"),
    )

    assert metadata is not None
    assert metadata.id == "darwinian-evolver-plugin"
    assert metadata.skills == ("darwinian-evolver",)
    assert metadata.contracts["skills"] == ("darwinian-evolver",)
    assert metadata.env_vars["darwinian-evolver"] == (
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_BASE_URL",
        "EVOLVER_MODEL",
        "EVOLVER_TRACE_JSONL",
        "DARWINIAN_EVOLVER_CACHE_DIR",
    )
    assert diagnostics == []


def test_local_discovery_finds_plugin() -> None:
    plugins, diagnostics = discover_plugins(
        state_store=PluginStateStore(base_path=PLUGIN_DIR.parents[2]),
        include_builtins=False,
        include_entrypoints=False,
    )

    by_name = {plugin.name: plugin for plugin in plugins}
    plugin = by_name["darwinian-evolver-plugin"]
    assert plugin.source == "local"
    assert plugin.manifest_path == str(PLUGIN_DIR / "memstack.plugin.json")
    assert plugin.skills == ("darwinian-evolver",)
    assert not [
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.plugin_name == "darwinian-evolver-plugin"
    ]


def test_plugin_skill_loads_from_markdown() -> None:
    skills, diagnostics = load_plugin_skills_from_markdown(
        [
            DiscoveredPlugin(
                name="darwinian-evolver-plugin",
                plugin=object(),
                source="local",
                manifest_path=str(PLUGIN_DIR / "memstack.plugin.json"),
                skills=("darwinian-evolver",),
                contracts={"skills": ("darwinian-evolver",)},
            )
        ],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert diagnostics == []
    assert [skill.name for skill in skills] == ["darwinian-evolver"]
    skill = skills[0]
    assert skill.source.value == "plugin"
    assert skill.license == "MIT"
    assert "AGPL-3.0" in (skill.full_content or "")
    assert "darwinian_evolver" in (skill.full_content or "")


def test_runtime_plugin_registers_only_local_metadata() -> None:
    spec = importlib.util.spec_from_file_location(
        "darwinian_evolver_plugin_test",
        PLUGIN_DIR / "plugin.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.plugin.name == "darwinian-evolver-plugin"
    assert module.DARWINIAN_EVOLVER_DEFAULTS["skill_dir"] == str(SKILL_DIR)


@pytest.mark.parametrize(
    "path",
    [
        SKILL_DIR / "scripts" / "evaluate_local_parrot.py",
        SKILL_DIR / "scripts" / "parrot_openrouter.py",
        SKILL_DIR / "scripts" / "show_snapshot.py",
        SKILL_DIR / "templates" / "custom_problem_template.py",
    ],
)
def test_shipped_scripts_parse(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"))


def test_openrouter_driver_keeps_provider_failures_non_fatal() -> None:
    source = (SKILL_DIR / "scripts" / "parrot_openrouter.py").read_text(encoding="utf-8")

    assert "OPENROUTER_API_KEY" in source
    assert "openrouter.ai/api/v1" in source
    assert "OPENROUTER_BASE_URL" in source
    assert "EVOLVER_MODEL" in source
    assert "LLM_ERROR" in source
    assert "EVOLVER_TRACE_JSONL" in source


def test_openrouter_driver_extracts_zhipu_style_fenced_prompt() -> None:
    _install_fake_darwinian_modules()
    module = _load_python_module(
        "darwinian_evolver_parrot_openrouter_test",
        SKILL_DIR / "scripts" / "parrot_openrouter.py",
    )

    response = """
Diagnosis...

```text
Repeat the following text verbatim. Output only this:

{{ phrase }}
```
""".strip()

    assert module._extract_prompt_template(response) == (
        "Repeat the following text verbatim. Output only this:\n\n{{ phrase }}"
    )


def test_openrouter_driver_extracts_json_prompt_template() -> None:
    module = _load_python_module(
        "darwinian_evolver_parrot_openrouter_test_json",
        SKILL_DIR / "scripts" / "parrot_openrouter.py",
    )

    response = json.dumps(
        {
            "prompt_template": (
                "Return this text exactly and output nothing else:\n\n{{ phrase }}"
            )
        }
    )

    assert module._extract_prompt_template(response) == (
        "Return this text exactly and output nothing else:\n\n{{ phrase }}"
    )


def test_openrouter_driver_rejects_unstructured_diagnosis_response() -> None:
    module = _load_python_module(
        "darwinian_evolver_parrot_openrouter_test_unstructured",
        SKILL_DIR / "scripts" / "parrot_openrouter.py",
    )

    response = (
        'The original prompt "Say {{ phrase }}" lacks constraints, so the model '
        "capitalizes and adds punctuation. You should make it more explicit."
    )

    assert module._extract_prompt_template(response) is None


def test_openrouter_driver_classifies_strict_mutator_prompt() -> None:
    module = _load_python_module(
        "darwinian_evolver_parrot_openrouter_test_classify",
        SKILL_DIR / "scripts" / "parrot_openrouter.py",
    )

    assert module._classify_prompt("Return only the improved template in one fenced block") == "mutator"


def test_openrouter_driver_uses_purpose_specific_system_messages() -> None:
    module = _load_python_module(
        "darwinian_evolver_parrot_openrouter_test_messages",
        SKILL_DIR / "scripts" / "parrot_openrouter.py",
    )

    evaluator_messages = module._messages_for_prompt(purpose="evaluator", prompt="Say {{ phrase }}")
    mutator_messages = module._messages_for_prompt(
        purpose="mutator",
        prompt="Return only the improved template",
    )

    assert evaluator_messages[0]["role"] == "system"
    assert "copy function" in evaluator_messages[0]["content"]
    assert mutator_messages[0]["role"] == "system"
    assert "Jinja prompt templates" in mutator_messages[0]["content"]


def test_openrouter_driver_retries_transient_llm_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_python_module(
        "darwinian_evolver_parrot_openrouter_test_retry",
        SKILL_DIR / "scripts" / "parrot_openrouter.py",
    )
    module.DEFAULT_LLM_RETRIES = 2
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    calls = {"count": 0}

    class _Completions:
        def create(self, **kwargs):
            calls["count"] += 1
            assert kwargs["temperature"] == 0
            assert kwargs["messages"][0]["role"] == "system"
            if calls["count"] == 1:
                raise RuntimeError("temporary")
            message = SimpleNamespace(content="ok")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    monkeypatch.setattr(module, "_client", lambda: fake_client)

    assert module._prompt_llm("Say hello") == "ok"
    assert calls["count"] == 2


def test_snapshot_reader_requires_trust_acknowledgement() -> None:
    source = (SKILL_DIR / "scripts" / "show_snapshot.py").read_text(encoding="utf-8")

    assert "--i-trust-this-file" in source
    assert "refusing to unpickle" in source


def test_snapshot_reader_maps_script_main_classes() -> None:
    module = _load_python_module(
        "darwinian_evolver_show_snapshot_test",
        SKILL_DIR / "scripts" / "show_snapshot.py",
    )

    PickledOrganism.__module__ = "__main__"
    PickledOrganism.__qualname__ = "PickledOrganism"
    sys.modules["__main__"].PickledOrganism = PickledOrganism
    try:
        inner = pickle.dumps(
            {
                "organisms": [
                    (
                        PickledOrganism(),
                        SimpleNamespace(score=0.25),
                    )
                ]
            }
        )
        outer = pickle.dumps({"population_snapshot": inner})
    finally:
        delattr(sys.modules["__main__"], "PickledOrganism")

    loaded_outer = module._trusted_loads(outer, class_map={"PickledOrganism": PickledOrganism})
    loaded_inner = module._trusted_loads(
        loaded_outer["population_snapshot"],
        class_map={"PickledOrganism": PickledOrganism},
    )

    organism, result = loaded_inner["organisms"][0]
    assert isinstance(organism, PickledOrganism)
    assert result.score == 0.25


def _load_python_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_fake_darwinian_modules() -> None:
    if "darwinian_evolver.cli_common" in sys.modules:
        return

    package = types.ModuleType("darwinian_evolver")
    cli_common = types.ModuleType("darwinian_evolver.cli_common")
    cli_common.build_hyperparameter_config_from_args = lambda _args: None
    cli_common.parse_learning_log_view_type = lambda value: value
    cli_common.register_hyperparameter_args = lambda _parser: None

    evolve_problem_loop = types.ModuleType("darwinian_evolver.evolve_problem_loop")
    evolve_problem_loop.EvolveProblemLoop = type("EvolveProblemLoop", (), {})

    problem = types.ModuleType("darwinian_evolver.problem")

    class _GenericBase:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        def __class_getitem__(cls, _item):
            return cls

    problem.EvaluationFailureCase = type("EvaluationFailureCase", (_GenericBase,), {})
    problem.EvaluationResult = type("EvaluationResult", (_GenericBase,), {})
    problem.Evaluator = type("Evaluator", (_GenericBase,), {})
    problem.Mutator = type("Mutator", (_GenericBase,), {})
    problem.Organism = type("Organism", (_GenericBase,), {})
    problem.Problem = type("Problem", (_GenericBase,), {})

    sys.modules["darwinian_evolver"] = package
    sys.modules["darwinian_evolver.cli_common"] = cli_common
    sys.modules["darwinian_evolver.evolve_problem_loop"] = evolve_problem_loop
    sys.modules["darwinian_evolver.problem"] = problem
