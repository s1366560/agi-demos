"""Build real factory/converter/catalog tools; no network or tool execution."""
import json
from pathlib import Path
from types import SimpleNamespace

from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.tools.sandbox_tool_wrapper import create_sandbox_mcp_tool
from src.infrastructure.agent.tools.todo_tools import todowrite_tool
from src.infrastructure.plugins.v2.tool_set import ToolSetCatalogV2, ToolSetV2

read = create_sandbox_mcp_tool('diagnostic-sandbox', 'read', {'name': 'read', 'input_schema': {'type': 'object', 'properties': {'file_path': {'type': 'string'}}, 'required': ['file_path']}}, None)
tools = {'read': read, 'todowrite': todowrite_tool}
definitions = convert_tools(tools)
catalog = ToolSetCatalogV2()
catalog.register_tools('qa-real-factory', lambda **kwargs: ToolSetV2(tools=tools, definitions=tuple(definitions)))
resolved = catalog.resolve(agent=SimpleNamespace(), selection_context=None, prepared_tool_provider=None)
result = {}
for tool in resolved.definitions:
    result[tool.name] = {'permission': tool.permission, 'resolver_retained': tool.permission_resolver is getattr(tools[tool.name], 'permission_resolver', None)}
    if tool.permission_resolver:
        result[tool.name]['progress_update'] = tool.permission_resolver({'action': 'update', 'todo_id': 'id', 'todos': [{'status': 'completed', 'result_summary': 'verified'}]})
        result[tool.name]['content_update'] = tool.permission_resolver({'action': 'update', 'todo_id': 'id', 'todos': [{'content': 'new task', 'status': 'completed'}]})
Path(__file__).with_name('read-todo-toolset-permission-proof.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result))
assert result['todowrite']['progress_update'] == 'conversation_progress'
assert result['todowrite']['resolver_retained']
assert result['read']['permission'] == 'read', 'Canonical server read tool is misclassified as ask'
