---
name: sandbox
description: |
  Sandbox MCP Server 是一个隔离的代码执行环境，提供完整的文件系统操作、命令执行、
  代码分析、测试运行和远程桌面能力。当你需要执行代码、操作文件、运行测试、
  分析代码结构、或需要图形界面操作时使用此技能。支持 Python、Node.js、Java 等多语言环境。
license: MIT
metadata:
  version: "1.0.0"
  author: MemStack Team
  tags: [sandbox, code-execution, file-system, desktop, testing, mcp]
---

# Sandbox 执行环境技能

Sandbox 是 Agent 的隔离执行环境，通过 MCP 协议提供安全的代码执行和文件操作能力。

## 何时使用

- 需要**执行代码**（Python/Node.js/Java/Bash）
- 需要**读写文件**（查看源码、修改配置、创建文件）
- 需要**运行测试**（pytest、jest 等）
- 需要**分析代码**（AST 解析、查找定义/引用）
- 需要**图形界面**（Web 自动化、GUI 应用）
- 需要**处理文档**（PDF、Word、Excel、PPT）

## 快速参考

### 核心工具

| 工具 | 用途 | 示例参数 |
|------|------|----------|
| `read` | 读取文件 | `file_path="src/main.py"` |
| `write` | 写入文件 | `file_path="new.py", content="..."` |
| `edit` | 编辑文件 | `file_path, old_text, new_text` |
| `glob` | 查找文件 | `pattern="**/*.py"` |
| `grep` | 搜索内容 | `pattern="TODO", path="src/"` |
| `bash` | 执行命令 | `command="python script.py"` |

### 代码分析工具

| 工具 | 用途 |
|------|------|
| `ast_parse` | 解析 Python AST |
| `ast_find_symbols` | 查找类/函数定义 |
| `code_index_build` | 构建代码索引 |
| `find_definition` | 查找符号定义 |
| `find_references` | 查找符号引用 |
| `call_graph` | 生成调用关系图 |

### 测试工具

| 工具 | 用途 |
|------|------|
| `generate_tests` | 生成测试用例 |
| `run_tests` | 运行测试 |
| `analyze_coverage` | 分析覆盖率 |

### 桌面/终端工具

| 工具 | 用途 |
|------|------|
| `start_desktop` | 启动远程桌面 (noVNC) |
| `start_terminal` | 启动 Web 终端 (ttyd) |

---

## 预装环境

### 系统工具
```
Python 3.13, Node.js 22, Java 21
Git, ffmpeg, pandoc, LibreOffice
bun, pnpm, yarn
```

### 中文支持
```
Locale: zh_CN.UTF-8
时区: Asia/Shanghai

预装中文字体:
- Noto CJK (思源黑体/宋体)
- 文泉驿微米黑/正黑
- 文鼎楷体/明体

桌面输入法: IBus 拼音
```

### Python 虚拟环境 (`/opt/skills-venv`)
```python
# 文档处理
pypdf, pdfplumber, reportlab, pdf2image
python-docx, openpyxl, pandas, xlrd

# 图像/媒体
pillow, imageio, imageio-ffmpeg, numpy
matplotlib, seaborn

# Web 自动化
playwright  # 已安装 chromium

# 开发工具
pytest, black, ruff, mypy, ipython
```

### Node.js 全局包
```
pptxgenjs, docx            # 文档生成
typescript, vite, parcel   # 构建工具
remotion, @remotion/cli    # 视频生成
puppeteer, sharp           # 渲染/图像
tailwindcss, postcss       # CSS
```

---

## 工作流示例

### 1. 探索项目

```
→ glob pattern="**/*.py"                    # 列出所有 Python 文件
→ read file_path="README.md"                # 阅读项目说明
→ ast_parse file_path="src/main.py"         # 分析入口文件
→ code_index_build project_path="src/"      # 建立代码索引
```

### 2. 修改代码

```
→ read file_path="src/module.py"            # 查看当前代码
→ preview_edit old_text="..." new_text="..."  # 预览修改
→ edit file_path="..." old_text="..." new_text="..."  # 执行修改
→ run_tests path="tests/"                   # 验证修改
```

### 3. 运行脚本

```
→ bash command="pip install -r requirements.txt"  # 安装依赖
→ bash command="python main.py --arg value"       # 运行脚本
→ bash command="pytest tests/ -v"                 # 运行测试
```

### 4. 文档处理

```
# PDF 提取文本
→ bash command="python -c \"
from pdfplumber import open as pdf_open
with pdf_open('doc.pdf') as pdf:
    print(pdf.pages[0].extract_text())
\""

# Excel 分析
→ bash command="python -c \"
import pandas as pd
df = pd.read_excel('data.xlsx')
print(df.describe())
\""

# Word 转换
→ bash command="pandoc input.docx -o output.md"

# PPT 生成 (Node.js)
→ bash command="node -e \"
const pptx = require('pptxgenjs');
let pres = new pptx.default();
pres.addSlide().addText('Hello', {x:1, y:1});
pres.writeFile({fileName: 'output.pptx'});
\""
```

### 5. 图形界面操作

```
→ start_desktop resolution="1920x1080"       # 启动桌面
→ bash command="firefox https://example.com" # 打开浏览器
→ get_desktop_status                         # 获取 VNC URL
# 用户通过 http://localhost:6080/vnc.html 访问
```

### 6. Web 自动化

```
→ bash command="python -c \"
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('https://example.com')
    page.screenshot(path='screenshot.png')
    browser.close()
\""
```

### 7. 中文内容处理

```
# 生成包含中文的图片
→ bash command="python -c \"
from PIL import Image, ImageDraw, ImageFont
img = Image.new('RGB', (400, 200), 'white')
draw = ImageDraw.Draw(img)
# 使用预装的中文字体
font = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 32)
draw.text((50, 80), '你好，世界！', font=font, fill='black')
img.save('chinese.png')
\""

# 检查系统字体
→ bash command="fc-list :lang=zh"

# 创建包含中文的 PDF
→ bash command="python -c \"
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
pdfmetrics.registerFont(TTFont('NotoSansCJK', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))
c = canvas.Canvas('chinese.pdf')
c.setFont('NotoSansCJK', 24)
c.drawString(100, 750, '中文PDF测试')
c.save()
\""
```

---

## 重要限制

### 安全限制
- 所有文件操作限制在 `/workspace` 目录内
- 危险命令被禁止 (`rm -rf /`, `mkfs`, fork bomb 等)
- 命令超时上限 600 秒
- 输出上限 16MB

### 路径规则
- 相对路径: 相对于 `/workspace`
- 绝对路径: 必须在 `/workspace` 内
- ⚠️ 不允许访问 workspace 外部

### 编辑注意事项
- `edit` 的 `old_text` 必须**精确匹配**（包括空格和换行）
- 建议包含 **3-5 行上下文** 确保唯一性
- 重要修改前使用 `preview_edit` 确认

---

## 连接信息

| 服务 | 端口 | URL |
|------|------|-----|
| MCP Server | 8765 | `ws://localhost:8765` |
| Web Terminal | 7681 | `http://localhost:7681` |
| Remote Desktop | 6080 | `http://localhost:6080/vnc.html` |

---

## 错误处理

返回格式:
```json
{
  "content": [{"type": "text", "text": "结果"}],
  "isError": false,
  "metadata": {...}
}
```

常见错误:
- `File not found` - 文件不存在
- `Path is outside workspace` - 路径越界
- `Command blocked for security` - 危险命令
- `Command timed out` - 超时

---

## 详细文档

完整 API 文档请参阅 `sandbox-mcp-server/SKILL.md`
