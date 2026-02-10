---
name: pdf-chinese-support
description: Generate PDF documents with proper Chinese character support using reportlab. Automatically handles font registration and provides helper functions for creating Chinese PDFs without garbled text issues. Use when generating any PDF containing Chinese characters.
---

# PDF Chinese Support

## Overview

When using reportlab to generate PDFs, Chinese fonts are not supported by default, causing Chinese text to display as garbled characters (squares or question marks). This skill provides a complete solution to ensure Chinese displays correctly in all PDF elements.

## Quick Start

### Method 1: Use the Helper Module (Recommended)

```python
from scripts.chinese_pdf_helper import ChinesePDFHelper

# Create helper instance
helper = ChinesePDFHelper()

# Generate PDF with Chinese content
helper.generate_pdf(
    output_path="report.pdf",
    title="中文报告标题",
    sections=[
        {"heading": "第一节", "content": "这是第一节的内容。"},
        {"heading": "第二节", "content": "这是第二节的内容，包含表格。"},
    ],
    table_data=[
        ["姓名", "职位", "部门"],
        ["张三", "经理", "销售部"],
        ["李四", "工程师", "技术部"],
    ]
)
```

### Method 2: Manual Font Registration

```python
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

# Step 1: Register Chinese font
pdfmetrics.registerFont(TTFont('ChineseFont', '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'))

# Step 2: Create style with Chinese font
chinese_style = ParagraphStyle(
    'ChineseStyle',
    fontName='ChineseFont',
    fontSize=12,
)

# Step 3: Wrap all Chinese text with Paragraph
text = Paragraph("你好，世界！", chinese_style)
```

## Available Chinese Fonts

| Font Name | Path | Priority |
|-----------|------|----------|
| WenQuanYi Zen Hei | `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc` | 1 |
| WenQuanYi Micro Hei | `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc` | 2 |
| Noto Sans CJK | `/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc` | 3 |
| Droid Sans Fallback | `/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf` | 4 |

## Key Rules for Chinese PDF

### 1. Always Register Font First
```python
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# MUST do this before creating any PDF content
pdfmetrics.registerFont(TTFont('ChineseFont', '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'))
```

### 2. Use Paragraph for All Text
```python
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

# Create Chinese style
style = ParagraphStyle('Chinese', fontName='ChineseFont', fontSize=12)

# Wrap ALL text with Paragraph - never use raw strings
title = Paragraph("中文标题", style)
content = Paragraph("中文内容", style)
```

### 3. Tables Must Use Paragraph Cells
```python
from reportlab.platypus import Table

# Convert all cell values to Paragraph
table_data = []
for row in data:
    table_row = [Paragraph(str(cell), chinese_style) for cell in row]
    table_data.append(table_row)

table = Table(table_data)
table.setStyle(TableStyle([
    ('FONTNAME', (0, 0), (-1, -1), 'ChineseFont'),  # All cells
]))
```

### 4. Clean HTML/Formatting
```python
import re

def clean_text(text):
    """Remove HTML tags and normalize whitespace"""
    text = re.sub(r'<[^>]+>', '', str(text))
    text = text.replace('\n', ' ').replace('\r', ' ')
    text = ' '.join(text.split())
    return text

# Always clean text before creating Paragraph
cleaned = clean_text(raw_text)
para = Paragraph(cleaned, chinese_style)
```

## Complete Example

```python
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import cm

# 1. Register font
pdfmetrics.registerFont(TTFont('ChineseFont', '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'))

# 2. Create document
doc = SimpleDocTemplate("output.pdf", pagesize=A4)
elements = []

# 3. Define styles
title_style = ParagraphStyle('Title', fontName='ChineseFont', fontSize=18, leading=24)
body_style = ParagraphStyle('Body', fontName='ChineseFont', fontSize=12, leading=20)

# 4. Add content
elements.append(Paragraph("报告标题", title_style))
elements.append(Spacer(1, 0.5*cm))
elements.append(Paragraph("这是报告正文内容。", body_style))

# 5. Create table with Chinese
data = [
    [Paragraph('列1', body_style), Paragraph('列2', body_style)],
    [Paragraph('数据1', body_style), Paragraph('数据2', body_style)],
]
table = Table(data)
table.setStyle(TableStyle([
    ('FONTNAME', (0, 0), (-1, -1), 'ChineseFont'),
    ('GRID', (0, 0), (-1, -1), 1, colors.black),
]))
elements.append(table)

# 6. Build PDF
doc.build(elements)
```

## Troubleshooting

### Issue: Chinese shows as squares or ???

**Cause**: Font not registered or not applied to text element.

**Solution**:
1. Check font exists: `ls -la /usr/share/fonts/truetype/wqy/`
2. Ensure `pdfmetrics.registerFont()` is called BEFORE creating any content
3. Verify all text uses `Paragraph(text, chinese_style)`
4. Check table cells are also wrapped with Paragraph

### Issue: Font file not found

**Solution**:
```bash
# Install Chinese fonts
sudo apt-get update
sudo apt-get install -y fonts-wqy-zenhei fonts-wqy-microhei
fc-cache -fv
```

### Issue: Some characters still garbled

**Cause**: Font doesn't support all Unicode characters.

**Solution**: Try different font:
```python
# Try Noto Sans CJK for better Unicode support
pdfmetrics.registerFont(TTFont('ChineseFont', '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc'))
```

## Helper Functions

The skill provides `chinese_pdf_helper.py` with these utilities:

- `register_chinese_font()` - Auto-detect and register available Chinese font
- `create_chinese_style()` - Create ParagraphStyle with Chinese font
- `clean_text()` - Remove HTML tags and normalize text
- `create_paragraph()` - Create Paragraph with automatic text cleaning
- `create_table_with_chinese()` - Create Table with all cells as Paragraphs
- `generate_pdf()` - High-level function to generate complete PDF

## Resources

- `scripts/check_fonts.py` - Check available Chinese fonts
- `scripts/generate_chinese_pdf.py` - Basic example
- `scripts/chinese_pdf_helper.py` - Complete helper module with all utilities