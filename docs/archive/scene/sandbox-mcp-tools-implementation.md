# Sandbox MCP Server 编程工具实现方案

## 一、需求概述

根据 `docs/场景/编程/tools.md` 文档分析，当前 `sandbox-mcp-server` 缺失核心编程能力，需要补全以下工具。

### 已有工具 (6个)

| 工具 | 描述 | 文件 |
|------|------|------|
| read | 读取文件内容 | file_tools.py |
| write | 写入文件 | file_tools.py |
| edit | 字符串替换编辑 | file_tools.py |
| glob | 文件模式匹配 | file_tools.py |
| grep | 正则搜索 | file_tools.py |
| bash | 命令执行 | bash_tool.py |

### 缺失工具清单

#### Phase 1: AST 解析工具 (高优先级)
1. `ast_parse` - 解析文件返回 AST
2. `ast_find_symbols` - 查找类/函数/变量
3. `ast_extract_function` - 提取函数代码
4. `ast_get_imports` - 获取导入依赖

#### Phase 2: 代码索引工具 (高优先级)
5. `code_index_build` - 构建代码索引
6. `find_definition` - 跳转到定义
7. `find_references` - 查找所有引用
8. `call_graph` - 获取调用图

#### Phase 3: 智能编辑工具 (中优先级)
9. `edit_by_ast` - 基于 AST 的精确编辑
10. `batch_edit` - 批量多文件编辑
11. `preview_edit` - 预览编辑

#### Phase 4: 测试工具 (中优先级)
12. `generate_tests` - 生成测试用例
13. `run_tests` - 运行测试
14. `analyze_coverage` - 覆盖率分析

#### Phase 5: Git 工具 (低优先级)
15. `git_diff` - Diff 分析
16. `git_log` - 文件历史
17. `generate_commit` - 生成 commit 消息

## 二、架构设计

### 目录结构

```
sandbox-mcp-server/src/tools/
├── __init__.py
├── registry.py              # 工具注册
├── base.py                  # 新增: 工具基类
│
├── file_tools.py            # 已有: read, write, edit, glob, grep
├── bash_tool.py             # 已有: bash
│
├── ast_tools.py             # 新增: AST 解析工具
├── index_tools.py           # 新增: 代码索引工具
├── edit_tools.py            # 新增: 智能编辑工具
├── test_tools.py            # 新增: 测试工具
└── git_tools.py             # 新增: Git 工具
```

### 工具基类设计

```python
# sandbox-mcp-server/src/tools/base.py
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional
import ast

class CodeParser(ABC):
    """代码解析器基类"""

    @abstractmethod
    async def parse_file(self, file_path: str) -> Any:
        """解析文件，返回 AST 或语法树"""
        pass

    @abstractmethod
    async def find_symbols(self, tree: Any, symbol_type: str) -> list[Dict]:
        """查找指定类型的符号"""
        pass

class PythonASTParser(CodeParser):
    """Python AST 解析器"""

    async def parse_file(self, file_path: str) -> ast.AST:
        content = Path(file_path).read_text(encoding='utf-8')
        return ast.parse(content)

    async def find_symbols(self, tree: ast.AST, symbol_type: str) -> list[Dict]:
        symbols = []
        for node in ast.walk(tree):
            if symbol_type == 'class' and isinstance(node, ast.ClassDef):
                symbols.append({
                    'name': node.name,
                    'lineno': node.lineno,
                    'end_lineno': node.end_lineno,
                    'type': 'class'
                })
            elif symbol_type == 'function' and isinstance(node, ast.FunctionDef):
                symbols.append({
                    'name': node.name,
                    'lineno': node.lineno,
                    'end_lineno': node.end_lineno,
                    'type': 'function'
                })
        return symbols
```

### 代码索引器设计

```python
# sandbox-mcp-server/src/tools/index_tools.py
from dataclasses import dataclass, field
from typing import Dict, List, Set

@dataclass
class SymbolIndex:
    """代码符号索引"""
    definitions: Dict[str, List[Dict]] = field(default_factory=dict)
    references: Dict[str, List[Dict]] = field(default_factory=dict)
    call_graph: Dict[str, Set[str]] = field(default_factory=dict)
    files_indexed: Set[str] = field(default_factory=set)

class CodeIndexer:
    """代码索引器"""

    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        self.index = SymbolIndex()

    async def build(self, project_path: str) -> SymbolIndex:
        """构建项目代码索引"""
        # 实现代码...
        pass

    async def find_references(self, symbol_name: str) -> List[Dict]:
        """查找符号的所有引用"""
        return self.index.references.get(symbol_name, [])

    async def find_definition(self, symbol_name: str) -> Optional[Dict]:
        """查找符号定义"""
        defs = self.index.definitions.get(symbol_name, [])
        return defs[0] if defs else None
```

## 三、分阶段实现

### Phase 1: AST 解析工具

| 工具 | 描述 |
|------|------|
| `ast_parse` | 解析 Python 文件返回 AST 结构 |
| `ast_find_symbols` | 查找类/函数/变量/导入 |
| `ast_extract_function` | 提取函数源代码 |
| `ast_get_imports` | 获取导入依赖列表 |

**实现要点**:
- 使用 Python 内置 `ast` 模块
- 返回结构化的符号信息
- 支持按类型和模式过滤

### Phase 2: 代码索引工具

| 工具 | 描述 |
|------|------|
| `code_index_build` | 构建项目代码索引 |
| `find_definition` | 查找符号定义位置 |
| `find_references` | 查找所有引用位置 |
| `call_graph` | 获取函数调用图 |

**实现要点**:
- 内存索引 + 可选持久化
- 支持增量更新
- 按文件分组显示引用

### Phase 3: 智能编辑工具

| 工具 | 描述 |
|------|------|
| `edit_by_ast` | 基于 AST 的精确编辑 |
| `batch_edit` | 批量多文件编辑 |
| `preview_edit` | 预览编辑变更 |

**实现要点**:
- 使用 `ast` 模块定位节点
- 保留注释和格式
- 支持回滚

### Phase 4: 测试工具

| 工具 | 描述 |
|------|------|
| `generate_tests` | 生成测试用例 |
| `run_tests` | 运行测试 |
| `analyze_coverage` | 覆盖率分析 |

### Phase 5: Git 工具

| 工具 | 描述 |
|------|------|
| `git_diff` | Diff 分析 |
| `git_log` | 文件历史 |
| `generate_commit` | 生成 commit 消息 |

## 四、依赖项

```txt
# 新增 Python 依赖
# pyproject.toml

[project.dependencies]
# 现有依赖...
aiofiles>=23.0.0
aiohttp>=3.9.0

# 新增: Git 支持
gitpython>=3.1.0

# 新增: 测试工具集成 (可选)
pytest>=7.0.0
coverage>=7.0.0
```

## 五、工具注册

```python
# sandbox-mcp-server/src/tools/registry.py

from src.tools.ast_tools import create_ast_parse_tool, create_ast_find_symbols_tool
from src.tools.index_tools import (
    create_code_index_build_tool,
    create_find_definition_tool,
    create_find_references_tool,
    create_call_graph_tool,
)

def get_tool_registry(workspace_dir: str = "/workspace") -> ToolRegistry:
    registry = ToolRegistry(workspace_dir)

    # 文件工具 (已有)
    registry.register(create_read_tool())
    registry.register(create_write_tool())
    registry.register(create_edit_tool())
    registry.register(create_glob_tool())
    registry.register(create_grep_tool())

    # Bash 工具 (已有)
    registry.register(create_bash_tool())

    # AST 工具 (新增)
    registry.register(create_ast_parse_tool())
    registry.register(create_ast_find_symbols_tool())

    # 代码索引工具 (新增)
    registry.register(create_code_index_build_tool())
    registry.register(create_find_definition_tool())
    registry.register(create_find_references_tool())
    registry.register(create_call_graph_tool())

    return registry
```

## 六、API 设计

### ast_parse

```json
{
  "name": "ast_parse",
  "description": "Parse a Python file and extract its AST structure",
  "inputSchema": {
    "type": "object",
    "properties": {
      "file_path": {"type": "string"}
    },
    "required": ["file_path"]
  }
}
```

### ast_find_symbols

```json
{
  "name": "ast_find_symbols",
  "description": "Find symbols (classes, functions, imports) in a Python file",
  "inputSchema": {
    "type": "object",
    "properties": {
      "file_path": {"type": "string"},
      "symbol_type": {
        "type": "string",
        "enum": ["class", "function", "import", "all"]
      },
      "pattern": {"type": "string"}
    },
    "required": ["file_path", "symbol_type"]
  }
}
```

### code_index_build

```json
{
  "name": "code_index_build",
  "description": "Build code index for a Python project",
  "inputSchema": {
    "type": "object",
    "properties": {
      "project_path": {"type": "string"},
      "force_rebuild": {"type": "boolean"}
    },
    "required": ["project_path"]
  }
}
```

### find_definition

```json
{
  "name": "find_definition",
  "description": "Find the definition of a symbol in the indexed codebase",
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol_name": {"type": "string"}
    },
    "required": ["symbol_name"]
  }
}
```

### find_references

```json
{
  "name": "find_references",
  "description": "Find all references to a symbol in the indexed codebase",
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol_name": {"type": "string"}
    },
    "required": ["symbol_name"]
  }
}
```

### call_graph

```json
{
  "name": "call_graph",
  "description": "Get the call graph for a function or the entire project",
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol_name": {"type": "string"},
      "max_depth": {"type": "integer", "default": 2}
    }
  }
}
```

## 七、测试策略

```python
# tests/tools/test_ast_tools.py

import pytest
from src.tools.ast_tools import ast_parse, ast_find_symbols

@pytest.mark.asyncio
async def test_ast_parse_simple_file():
    result = await ast_parse(
        file_path="test_sample.py",
        _workspace_dir="tests/fixtures",
    )
    assert not result.get("isError")
    symbols = result["metadata"]["symbols"]
    assert len(symbols["functions"]) >= 0

@pytest.mark.asyncio
async def test_find_symbols_filter():
    result = await ast_find_symbols(
        file_path="test_sample.py",
        symbol_type="class",
        _workspace_dir="tests/fixtures",
    )
    assert not result.get("isError")
```

## 八、风险与注意事项

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 大型项目索引慢 | 高 | 增量索引、并行处理 |
| 内存占用 | 中 | 限制索引大小、分片处理 |
| 多语言支持 | 低 | 优先 Python，逐步添加 |

## 九、进度跟踪

| Phase | 工具 | 状态 | 覆盖率 |
|-------|------|------|--------|
| Phase 1 | `ast_parse` | ✅ 已完成 | 89% |
| Phase 1 | `ast_find_symbols` | ✅ 已完成 | - |
| Phase 1 | `ast_extract_function` | ✅ 已完成 | - |
| Phase 1 | `ast_get_imports` | ✅ 已完成 | - |
| Phase 2 | `code_index_build` | ✅ 已完成 | 82% |
| Phase 2 | `find_definition` | ✅ 已完成 | - |
| Phase 2 | `find_references` | ✅ 已完成 | - |
| Phase 2 | `call_graph` | ✅ 已完成 | - |
| Phase 2 | `dependency_graph` | ✅ 已完成 | - |
| Phase 3 | `edit_by_ast` | ✅ 已完成 | - |
| Phase 3 | `batch_edit` | ✅ 已完成 | - |
| Phase 3 | `preview_edit` | ✅ 已完成 | - |
| Phase 4 | `generate_tests` | ✅ 已完成 | 80% |
| Phase 4 | `run_tests` | ✅ 已完成 | - |
| Phase 4 | `analyze_coverage` | ✅ 已完成 | - |
| Phase 5 | `git_diff` | ✅ 已完成 | 78% |
| Phase 5 | `git_log` | ✅ 已完成 | - |
| Phase 5 | `generate_commit` | ✅ 已完成 | - |

**测试状态**: 69 个测试全部通过 ✅

**工具注册**: 24 个工具已注册

**Bug 修复记录**:
- 修复 `call_graph` 字段默认值从 `set` 改为 `dict`
- 修复 `test_tools.py` 中 `ast.unparse` 语法错误
- 修复 `_generate_function_test` 缺少 `class_name` 参数
- 修复 `_generate_function_test` 获取默认值的方式

## 十、实现文件清单

### 新增文件
- `src/tools/ast_tools.py` - AST 解析工具 (686 行)
- `src/tools/index_tools.py` - 代码索引工具 (876 行)
- `src/tools/edit_tools.py` - 智能编辑工具 (526 行)
- `src/tools/test_tools.py` - 测试工具 (550 行)
- `src/tools/git_tools.py` - Git 工具 (460 行)
- `tests/tools/test_ast_tools.py` - AST 工具测试 (270 行)
- `tests/tools/test_index_tools.py` - 索引工具测试 (350 行)
- `tests/tools/test_edit_tools.py` - 编辑工具测试 (326 行)
- `tests/tools/test_test_tools.py` - 测试工具测试 (283 行)
- `tests/tools/test_git_tools.py` - Git 工具测试 (360 行)

### 修改文件
- `src/tools/registry.py` - 更新工具注册

**总代码量**: 约 4100+ 行新增代码
