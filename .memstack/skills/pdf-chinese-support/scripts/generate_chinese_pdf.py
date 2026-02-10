#!/usr/bin/env python3
"""
生成包含中文的PDF文件示例
使用 reportlab 并正确注册中文字体
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import cm
import os

def generate_chinese_pdf(output_path="chinese_demo.pdf", title="中文PDF示例", content=None):
    """
    生成包含中文的PDF文件

    Args:
        output_path: 输出PDF文件路径
        title: 文档标题
        content: 表格内容，格式为 [[col1, col2, col3], ...]
    """

    # 尝试注册中文字体（按优先级顺序）
    font_paths = [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]

    font_registered = False
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont('ChineseFont', font_path))
                print(f"✓ 成功注册字体: {font_path}")
                font_registered = True
                break
            except Exception as e:
                print(f"✗ 注册字体失败 {font_path}: {e}")

    if not font_registered:
        raise RuntimeError(
            "未找到可用的中文字体。请安装中文字体:\n"
            "sudo apt-get install -y fonts-wqy-zenhei fonts-wqy-microhei"
        )

    # 创建文档
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    elements = []

    # 创建中文样式
    styles = getSampleStyleSheet()
    chinese_style = ParagraphStyle(
        'ChineseStyle',
        parent=styles['Normal'],
        fontName='ChineseFont',
        fontSize=12,
        leading=20,
    )
    chinese_title = ParagraphStyle(
        'ChineseTitle',
        parent=styles['Heading1'],
        fontName='ChineseFont',
        fontSize=18,
        leading=24,
    )
    chinese_header = ParagraphStyle(
        'ChineseHeader',
        parent=styles['Normal'],
        fontName='ChineseFont',
        fontSize=12,
        leading=20,
        textColor=colors.whitesmoke,
    )

    # 添加标题
    title_para = Paragraph(title, chinese_title)
    elements.append(title_para)
    elements.append(Spacer(1, 0.5*cm))

    # 添加说明文字
    desc_text = "这是使用 reportlab 生成的中文PDF文档，中文显示正常。"
    desc = Paragraph(desc_text, chinese_style)
    elements.append(desc)
    elements.append(Spacer(1, 0.5*cm))

    # 默认表格内容
    if content is None:
        content = [
            ['项目名称', '描述', '状态'],
            ['功能A', '这是一个测试功能', '已完成'],
            ['功能B', '这是另一个测试功能', '进行中'],
            ['功能C', '这是第三个测试功能', '待开始'],
        ]

    # 将字符串转换为 Paragraph（确保中文正确显示）
    table_data = []
    for row in content:
        table_row = []
        for cell in row:
            if isinstance(cell, str):
                table_row.append(Paragraph(cell, chinese_style))
            else:
                table_row.append(cell)
        table_data.append(table_row)

    # 创建表格
    col_widths = [6*cm, 6*cm, 3*cm]
    table = Table(table_data, colWidths=col_widths)

    # 设置表格样式
    table_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'ChineseFont'),  # 表头字体
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]
    table.setStyle(TableStyle(table_style))

    elements.append(table)

    # 生成PDF
    doc.build(elements)
    print(f"✓ PDF已生成: {output_path}")
    return output_path

if __name__ == "__main__":
    # 示例用法
    generate_chinese_pdf(
        output_path="chinese_demo.pdf",
        title="中文PDF演示",
        content=[
            ['技能名称', '用途', '状态'],
            ['personal-productivity', '个人生产力管理', '已安装'],
            ['daily-meeting-update', '生成每日站会更新', '已安装'],
            ['brainstorming', '头脑风暴', '已安装'],
        ]
    )