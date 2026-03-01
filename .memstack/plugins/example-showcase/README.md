# Example Showcase Plugin

A comprehensive reference plugin demonstrating **all 10 MemStack plugin capabilities**.
Use this as a template when building your own plugins.

## Capabilities Demonstrated

| # | Capability | Registration Method | File |
|---|-----------|-------------------|------|
| 1 | Tools | `register_tool_factory()` | `tools.py` |
| 2 | Skills | SKILL.md files in `skills/` directory (preferred) | `skills/*/SKILL.md` |
| 3 | Hooks (with priority) | `register_hook()` | `handlers.py` |
| 4 | HTTP Routes | `register_http_route()` | `handlers.py` |
| 5 | CLI Commands | `register_cli_command()` | `handlers.py` |
| 6 | Lifecycle Hooks | `register_lifecycle_hook()` | `handlers.py` |
| 7 | Config Schema | `register_config_schema()` | `plugin.py` |
| 8 | Commands | `register_command()` | `handlers.py` |
| 9 | Services | `register_service()` | `handlers.py` |
| 10 | Providers | `register_provider()` | `handlers.py` |

## File Structure

```
example-showcase/
  memstack.plugin.json   # Plugin manifest (id, name, version, skills path)
  __init__.py            # Package marker
  plugin.py              # Entry point -- ExampleShowcasePlugin with setup(api)
  tools.py               # 3 tool classes: EchoTool, RandomNumberTool, TimestampTool
  skills/                # SKILL.md-based skill definitions (preferred approach)
    showcase-greeting/SKILL.md
    showcase-summary/SKILL.md
  skills.py              # Legacy skill factory (kept for backward compat reference)
  handlers.py            # All handler types (hooks, HTTP, CLI, lifecycle, etc.)
  README.md              # This file
```

## Activation

```python
# Enable via the agent's plugin_manager tool
plugin_manager(action="enable", plugin_name="example-showcase")
plugin_manager(action="reload")
```

## Important: Import Pattern for Local Plugins

Local plugins (under `.memstack/plugins/`) are loaded via
`importlib.util.spec_from_file_location` **without a package context**.
This means **relative imports will fail**:

```python
# WRONG -- will raise ImportError
from .tools import EchoTool

# CORRECT -- use importlib to load sibling modules
import importlib.util
from pathlib import Path
from types import ModuleType

_PLUGIN_DIR = Path(__file__).resolve().parent

def _load_sibling(module_file: str) -> ModuleType:
    file_path = _PLUGIN_DIR / module_file
    spec = importlib.util.spec_from_file_location(
        f"my_plugin_{file_path.stem}", file_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

_tools = _load_sibling("tools.py")
EchoTool = _tools.EchoTool
```

Alternatively, keep everything in a single `plugin.py` file for simple plugins.

## Tool Protocol

Each tool class must implement:

```python
class MyTool:
    name = "my_tool_name"
    description = "What the tool does"

    @staticmethod
    def get_parameters_schema() -> dict:
        return {"type": "object", "properties": {...}}

    @staticmethod
    def validate_args(**kwargs) -> bool:
        return True

    async def execute(self, **kwargs) -> str:
        return "result"
```

The **preferred** approach is SKILL.md files in a `skills/` directory:

```
skills/
  my-skill/
    SKILL.md
```

The manifest declares the skills directory:
```json
{
  "skills": ["./skills"]
}
```

Each SKILL.md uses YAML frontmatter:
```markdown
---
name: my-skill
description: What the skill teaches
trigger_patterns:
  - "keyword1"
  - "keyword2"
tools:
  - tool_name
user_invocable: true
---

# My Skill

Instructions for the agent...
```

For backward compatibility, you can also use Python factory functions:
```python
def my_skill_factory(context):
    return {
        "my-skill": {
            "name": "my-skill",
            "description": "What the skill teaches",
            "content": "Markdown instructions for the agent",
            "trigger_keywords": ["keyword1", "keyword2"],
        },
    }
```

## Hook Priorities

Lower number = runs earlier. Default is 100.

| Priority | Use Case |
|----------|----------|
| 1-10 | Security checks, input validation |
| 50 | Normal processing |
| 100 | Default -- logging, metrics |
| 200+ | Cleanup, post-processing |

## Config Schema

Register a JSON Schema dict to validate plugin configuration:

```python
api.register_config_schema({
    "type": "object",
    "properties": {
        "my_setting": {"type": "string", "default": "value"},
    },
    "additionalProperties": False,
})
```