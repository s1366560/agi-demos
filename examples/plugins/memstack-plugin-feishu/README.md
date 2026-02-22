# memstack-plugin-feishu

External Feishu channel plugin package for MemStack runtime.

## Entry point

```toml
[project.entry-points."memstack.agent_plugins"]
feishu = "memstack_plugin_feishu.plugin:FeishuChannelPlugin"
```

## Build

```bash
cd examples/plugins/memstack-plugin-feishu
uv build . --wheel --out-dir ./dist
```

## Install

```bash
python -m pip install dist/*.whl
```

After install, refresh runtime in agent:

```python
plugin_manager(action="reload")
plugin_manager(action="list")
```
