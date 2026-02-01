---
name: sandbox
description: |
  Sandbox MCP Server 是一个隔离的代码执行环境，提供完整的文件系统操作、命令执行、
  代码分析、测试运行和远程桌面能力。当你需要执行代码、操作文件、运行测试、
  分析代码结构、或需要图形界面操作时使用此技能。支持 Python、Node.js、Java 等多语言环境。
metadata:
  version: "1.0.0"
  author: MemStack Team
  tags: [sandbox, code-execution, file-system, desktop, testing]
---

# Sandbox MCP Server 技能指南

## 概述

Sandbox 是一个功能完备的隔离执行环境，通过 MCP (Model Context Protocol) 提供以下核心能力：

- **文件系统操作**: 读写、编辑、搜索文件
- **命令执行**: 在隔离环境中安全执行 bash 命令
- **代码分析**: AST 解析、符号索引、调用图分析
- **测试支持**: 测试生成、运行、覆盖率分析
- **版本控制**: Git diff、log、commit 生成
- **远程桌面**: XFCE 桌面环境，通过 noVNC 浏览器访问

## 工作目录

所有操作默认在 `/workspace` 目录下进行。路径可以是：
- **相对路径**: 相对于 `/workspace`，如 `src/main.py`
- **绝对路径**: 必须在 `/workspace` 内部，如 `/workspace/src/main.py`

⚠️ **安全限制**: 不允许访问 `/workspace` 外部的文件

---

## 工具分类与使用指南

### 1. 文件系统工具

#### `read` - 读取文件
读取文件内容，返回带行号的文本。

```json
{
  "tool": "read",
  "arguments": {
    "file_path": "src/main.py",
    "offset": 0,         // 起始行 (0-based)
    "limit": 2000        // 最大行数
  }
}
```

**使用场景**:
- 查看源代码内容
- 检查配置文件
- 分析日志文件

**返回格式**:
```
     1	import os
     2	from pathlib import Path
     3	
     4	def main():
     5	    pass
```

#### `write` - 写入文件
创建或覆盖文件。自动创建父目录。

```json
{
  "tool": "write",
  "arguments": {
    "file_path": "src/new_module.py",
    "content": "# New module\n\ndef hello():\n    return 'world'"
  }
}
```

**使用场景**:
- 创建新文件
- 完全重写文件内容
- 生成配置文件

#### `edit` - 编辑文件
通过查找替换修改文件内容。

```json
{
  "tool": "edit",
  "arguments": {
    "file_path": "src/main.py",
    "old_text": "def old_function():\n    pass",
    "new_text": "def new_function():\n    return True"
  }
}
```

**使用场景**:
- 修改函数实现
- 更新配置值
- 修复 bug

**注意事项**:
- `old_text` 必须精确匹配（包括空格和换行）
- 建议包含 3-5 行上下文确保唯一性

#### `patch` - 应用补丁
使用 unified diff 格式应用补丁。

```json
{
  "tool": "patch",
  "arguments": {
    "file_path": "src/main.py",
    "patch": "--- a/src/main.py\n+++ b/src/main.py\n@@ -1,3 +1,4 @@\n import os\n+import sys\n from pathlib import Path"
  }
}
```

#### `glob` - 查找文件
通过 glob 模式查找文件。

```json
{
  "tool": "glob",
  "arguments": {
    "pattern": "**/*.py",          // Glob 模式
    "include_hidden": false,       // 是否包含隐藏文件
    "max_results": 100            // 最大结果数
  }
}
```

**常用模式**:
- `**/*.py` - 所有 Python 文件
- `src/**/*.ts` - src 目录下所有 TypeScript 文件
- `*.json` - 当前目录的 JSON 文件
- `**/test_*.py` - 所有测试文件

#### `grep` - 搜索内容
在文件中搜索文本或正则表达式。

```json
{
  "tool": "grep",
  "arguments": {
    "pattern": "def\\s+\\w+\\(",   // 搜索模式
    "path": "src/",                 // 搜索路径
    "file_pattern": "*.py",         // 文件过滤
    "is_regex": true,               // 是否正则表达式
    "context_lines": 2              // 上下文行数
  }
}
```

**使用场景**:
- 查找函数定义
- 搜索特定字符串
- 定位 TODO 注释

#### `list` - 列出目录
列出目录内容。

```json
{
  "tool": "list",
  "arguments": {
    "path": "src/",
    "recursive": false,
    "include_hidden": false
  }
}
```

---

### 2. 命令执行工具

#### `bash` - 执行命令
在 sandbox 中执行 bash 命令。

```json
{
  "tool": "bash",
  "arguments": {
    "command": "python -m pytest tests/ -v",
    "timeout": 300,                // 超时秒数 (最大 600)
    "working_dir": "project/"      // 工作目录
  }
}
```

**使用场景**:
- 运行脚本: `python script.py`
- 安装依赖: `pip install -r requirements.txt`
- 构建项目: `npm run build`
- 运行测试: `pytest tests/`
- Git 操作: `git status`

**安全限制**:
- 禁止危险命令 (`rm -rf /`, `mkfs`, fork bomb 等)
- 超时上限 600 秒
- 输出上限 16MB

**预装环境**:
```
Python 3.13 (及 /opt/skills-venv 虚拟环境)
Node.js 22 (npm, pnpm, yarn, bun)
Java 21 (maven, gradle)
Git, ffmpeg, pandoc, LibreOffice
```

**中文支持**:
```
Locale: zh_CN.UTF-8
时区: Asia/Shanghai

预装中文字体:
- Noto Sans CJK (思源黑体) - /usr/share/fonts/opentype/noto/
- Noto Serif CJK (思源宋体)
- 文泉驿微米黑 (WenQuanYi Micro Hei)
- 文泉驿正黑 (WenQuanYi Zen Hei)  
- 文鼎楷体 (AR PL UKai)
- 文鼎明体 (AR PL UMing)

桌面输入法: IBus 拼音 (仅完整版)
```

**Python 中文字体使用示例**:
```python
# Pillow 绘制中文
from PIL import ImageFont
font = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 24)

# Matplotlib 中文
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'WenQuanYi Micro Hei']
plt.rcParams['axes.unicode_minus'] = False

# ReportLab PDF 中文
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
pdfmetrics.registerFont(TTFont('NotoSansCJK', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))
```

**预装 Python 包**:
```
# 文档处理
pypdf, pdfplumber, reportlab, pdf2image
python-docx, openpyxl, pandas

# 图像处理
pillow, imageio, numpy, matplotlib

# Web 自动化
playwright (已安装 chromium)

# 开发工具
pytest, black, ruff, mypy
```

**预装 Node.js 包**:
```
pptxgenjs, docx, typescript, vite, parcel
remotion, puppeteer, sharp, tailwindcss
```

---

### 3. 代码分析工具

#### `ast_parse` - AST 解析
解析 Python 文件的 AST 结构。

```json
{
  "tool": "ast_parse",
  "arguments": {
    "file_path": "src/main.py",
    "include_docstrings": true
  }
}
```

**返回信息**:
- 类定义 (名称、行号、基类、方法)
- 函数定义 (名称、参数、返回类型)
- 导入语句
- 变量定义

#### `ast_find_symbols` - 查找符号
在 AST 中查找特定符号。

```json
{
  "tool": "ast_find_symbols",
  "arguments": {
    "file_path": "src/main.py",
    "symbol_name": "MyClass",
    "symbol_type": "class"    // class, function, method
  }
}
```

#### `ast_extract_function` - 提取函数
提取函数的完整代码。

```json
{
  "tool": "ast_extract_function",
  "arguments": {
    "file_path": "src/main.py",
    "function_name": "process_data"
  }
}
```

#### `ast_get_imports` - 获取导入
获取文件的所有导入语句。

```json
{
  "tool": "ast_get_imports",
  "arguments": {
    "file_path": "src/main.py"
  }
}
```

---

### 4. 代码索引工具

#### `code_index_build` - 构建索引
为项目构建代码索引。

```json
{
  "tool": "code_index_build",
  "arguments": {
    "project_path": "src/",
    "pattern": "**/*.py",
    "exclude_dirs": ["__pycache__", ".venv"]
  }
}
```

#### `find_definition` - 查找定义
查找符号的定义位置。

```json
{
  "tool": "find_definition",
  "arguments": {
    "symbol_name": "MyClass"
  }
}
```

#### `find_references` - 查找引用
查找符号的所有引用。

```json
{
  "tool": "find_references",
  "arguments": {
    "symbol_name": "process_data"
  }
}
```

#### `call_graph` - 调用图
生成函数调用关系图。

```json
{
  "tool": "call_graph",
  "arguments": {
    "function_name": "main",
    "max_depth": 3
  }
}
```

#### `dependency_graph` - 依赖图
生成模块依赖关系图。

```json
{
  "tool": "dependency_graph",
  "arguments": {
    "module_name": "src.main"
  }
}
```

---

### 5. 编辑增强工具

#### `edit_by_ast` - AST 编辑
基于 AST 进行精确编辑。

```json
{
  "tool": "edit_by_ast",
  "arguments": {
    "file_path": "src/main.py",
    "target_type": "function",   // class, function, method
    "target_name": "old_name",
    "operation": "rename",       // rename, delete
    "new_value": "new_name"
  }
}
```

**使用场景**:
- 重命名函数/类
- 删除代码块

#### `batch_edit` - 批量编辑
一次执行多个编辑操作。

```json
{
  "tool": "batch_edit",
  "arguments": {
    "edits": [
      {"file_path": "a.py", "old_text": "foo", "new_text": "bar"},
      {"file_path": "b.py", "old_text": "baz", "new_text": "qux"}
    ],
    "dry_run": false,
    "stop_on_error": true
  }
}
```

#### `preview_edit` - 预览编辑
预览编辑效果（不实际修改）。

```json
{
  "tool": "preview_edit",
  "arguments": {
    "file_path": "src/main.py",
    "old_text": "old_code",
    "new_text": "new_code"
  }
}
```

---

### 6. 测试工具

#### `generate_tests` - 生成测试
为 Python 代码生成测试用例。

```json
{
  "tool": "generate_tests",
  "arguments": {
    "file_path": "src/calculator.py",
    "function_name": "add",        // 可选
    "class_name": "Calculator",    // 可选
    "test_framework": "pytest",
    "output_path": "tests/test_calculator.py"
  }
}
```

#### `run_tests` - 运行测试
执行测试并返回结果。

```json
{
  "tool": "run_tests",
  "arguments": {
    "path": "tests/",
    "pattern": "test_*.py",
    "verbose": true,
    "coverage": true
  }
}
```

#### `analyze_coverage` - 覆盖率分析
分析测试覆盖率。

```json
{
  "tool": "analyze_coverage",
  "arguments": {
    "source_dir": "src/",
    "test_dir": "tests/"
  }
}
```

---

### 7. Git 工具

#### `git_diff` - 查看差异
显示代码变更。

```json
{
  "tool": "git_diff",
  "arguments": {
    "file_path": "src/main.py",   // 可选，不填则显示所有
    "cached": false,               // true 显示暂存区
    "context_lines": 3
  }
}
```

#### `git_log` - 提交历史
查看 Git 提交历史。

```json
{
  "tool": "git_log",
  "arguments": {
    "max_count": 10,
    "file_path": "src/main.py",   // 可选
    "since": "1 week ago"         // 可选
  }
}
```

#### `generate_commit` - 生成提交信息
基于变更生成提交信息。

```json
{
  "tool": "generate_commit",
  "arguments": {
    "style": "conventional"   // conventional, simple
  }
}
```

---

### 8. 终端工具

#### `start_terminal` - 启动终端
启动 Web 终端 (ttyd)。

```json
{
  "tool": "start_terminal",
  "arguments": {
    "port": 7681
  }
}
```

访问: `http://localhost:7681`

#### `stop_terminal` - 停止终端
```json
{"tool": "stop_terminal", "arguments": {}}
```

#### `get_terminal_status` - 终端状态
```json
{"tool": "get_terminal_status", "arguments": {}}
```

---

### 9. 远程桌面工具

#### `start_desktop` - 启动桌面
启动 XFCE 远程桌面。

```json
{
  "tool": "start_desktop",
  "arguments": {
    "display": ":1",
    "resolution": "1920x1080",
    "port": 6080
  }
}
```

访问: `http://localhost:6080/vnc.html`

**支持分辨率**: 1280x720, 1920x1080, 1600x900

#### `stop_desktop` - 停止桌面
```json
{"tool": "stop_desktop", "arguments": {}}
```

#### `get_desktop_status` - 桌面状态
```json
{"tool": "get_desktop_status", "arguments": {}}
```

#### `restart_desktop` - 重启桌面
```json
{
  "tool": "restart_desktop",
  "arguments": {
    "resolution": "1920x1080"
  }
}
```

---

## 典型工作流程

### 1. 项目探索

```
1. glob pattern="**/*.py" → 找到所有 Python 文件
2. read file_path="README.md" → 了解项目
3. code_index_build project_path="src/" → 建立索引
4. ast_parse file_path="src/main.py" → 分析代码结构
```

### 2. 修改代码

```
1. read file_path="src/module.py" → 查看当前代码
2. preview_edit old_text="..." new_text="..." → 预览修改
3. edit file_path="src/module.py" old_text="..." new_text="..." → 执行修改
4. run_tests path="tests/" → 验证修改
```

### 3. 调试问题

```
1. grep pattern="ERROR" path="logs/" → 查找错误
2. read file_path="logs/app.log" offset=100 → 查看日志
3. bash command="python -c 'import module; print(module.debug())'" → 测试
```

### 4. 图形界面操作

```
1. start_desktop resolution="1920x1080" → 启动桌面
2. bash command="firefox https://example.com" → 打开浏览器
3. get_desktop_status → 获取 VNC URL
4. [用户通过浏览器访问 noVNC 进行图形操作]
```

### 5. 文档处理 (使用预装 Skills 依赖)

```
# PDF 处理
bash command="python -c \"
from pypdf import PdfReader
reader = PdfReader('/workspace/doc.pdf')
print(len(reader.pages))
\""

# Excel 处理
bash command="python -c \"
import pandas as pd
df = pd.read_excel('/workspace/data.xlsx')
print(df.head())
\""

# Word 文档
bash command="pandoc input.docx -o output.md"
```

---

## 最佳实践

### 文件操作

1. **先读后改**: 修改文件前先 `read` 确认当前内容
2. **精确匹配**: `edit` 时 `old_text` 要包含足够上下文
3. **批量操作**: 多个相关修改使用 `batch_edit`
4. **预览修改**: 重要修改前用 `preview_edit` 确认

### 命令执行

1. **设置超时**: 长时间任务设置合理的 `timeout`
2. **检查退出码**: 注意返回的 `exit_code`
3. **分步执行**: 复杂任务拆分成多个简单命令
4. **使用虚拟环境**: Python 项目使用 `/opt/skills-venv` 或创建新虚拟环境

### 代码分析

1. **先建索引**: 分析前先 `code_index_build`
2. **利用 AST**: 代码重构优先使用 `edit_by_ast`
3. **查调用图**: 修改函数前查看 `call_graph` 了解影响

### 测试

1. **先生成后运行**: 使用 `generate_tests` 生成骨架
2. **关注覆盖率**: 定期 `analyze_coverage`
3. **增量测试**: 修改后只运行相关测试

---

## 错误处理

所有工具返回统一格式:

```json
{
  "content": [{"type": "text", "text": "结果或错误信息"}],
  "isError": true/false,
  "metadata": { ... }
}
```

常见错误:
- `File not found`: 文件不存在
- `Path is outside workspace`: 路径越界
- `Command blocked for security`: 危险命令被阻止
- `Command timed out`: 命令超时

---

## 连接信息

| 服务 | 端口 | URL |
|------|------|-----|
| MCP Server | 8765 | `ws://localhost:8765` |
| Web Terminal | 7681 | `http://localhost:7681` |
| Remote Desktop | 6080 | `http://localhost:6080/vnc.html` |
