# memstack-plugin-template

Standalone plugin package template for MemStack runtime.

## Entry point contract

`pyproject.toml` registers the plugin in entry point group `memstack.agent_plugins`:

```toml
[project.entry-points."memstack.agent_plugins"]
template = "memstack_plugin_template.plugin:TemplatePlugin"
```

MemStack runtime discovers this entry point and executes `TemplatePlugin.setup(api)`.

## Local build

```bash
cd examples/plugins/memstack-plugin-template
uv build . --wheel --out-dir ./dist-wheel
```

## Install into MemStack runtime environment

```bash
python -m pip install ./dist-wheel/memstack_plugin_template-0.1.0-py3-none-any.whl
```

Then refresh plugin runtime in agent:

```python
plugin_manager(action="reload")
plugin_manager(action="list")
```

## Publish to private index (example)

```bash
# Use your organization index URL and credentials
python -m pip install twine
python -m twine upload --repository-url https://pypi.example.com/simple dist-wheel/*.whl
```

Install from private index in MemStack environment:

```bash
PIP_INDEX_URL=https://pypi.example.com/simple \
python -m pip install memstack-plugin-template==0.1.0
```

Or use agent tool after index is configured in runtime environment:

```python
plugin_manager(action="install", requirement="memstack-plugin-template==0.1.0")
```
