#!/usr/bin/env python3
"""
中文PDF生成辅助模块
提供完整的工具函数，确保PDF中的中文正确显示
"""

import os
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, PageBreak, ListFlowable, ListItem
)
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT


class ChinesePDFHelper:
    """中文PDF生成助手类"""

    # 中文字体搜索路径（按优先级排序）
    FONT_PATHS = [
        ("WenQuanYi Zen Hei", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        ("WenQuanYi Micro Hei", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        ("Noto Sans CJK", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        ("Droid Sans Fallback", "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
        ("Noto Sans CJK SC", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]

    def __init__(self, font_name="ChineseFont"):
        """
        初始化中文PDF助手

        Args:
            font_name: 注册的字体内置名称，默认"ChineseFont"
        """
        self.font_name = font_name
        self.font_path = None
        self.font_registered = False
        self.styles = {}

        # 自动注册字体
        self._register_font()
        self._create_styles()

    def _register_font(self):
        """注册中文字体"""
        for font_name, font_path in self.FONT_PATHS:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont(self.font_name, font_path))
                    self.font_path = font_path
                    self.font_registered = True
                    print(f"✓ 已注册中文字体: {font_name} ({font_path})")
                    return
                except Exception as e:
                    print(f"✗ 注册字体失败 {font_path}: {e}")
                    continue

        if not self.font_registered:
            raise RuntimeError(
                "未找到可用的中文字体。请安装中文字体:\n"
                "sudo apt-get install -y fonts-wqy-zenhei fonts-wqy-microhei"
            )

    def _create_styles(self):
        """创建常用中文样式"""
        base_styles = getSampleStyleSheet()

        # 标题样式
        self.styles['title'] = ParagraphStyle(
            'ChineseTitle',
            parent=base_styles['Heading1'],
            fontName=self.font_name,
            fontSize=20,
            leading=28,
            alignment=TA_CENTER,
            spaceAfter=20,
        )

        # 副标题样式
        self.styles['subtitle'] = ParagraphStyle(
            'ChineseSubtitle',
            parent=base_styles['Heading2'],
            fontName=self.font_name,
            fontSize=14,
            leading=20,
            alignment=TA_CENTER,
            spaceAfter=15,
        )

        # 章节标题
        self.styles['heading1'] = ParagraphStyle(
            'ChineseHeading1',
            parent=base_styles['Heading1'],
            fontName=self.font_name,
            fontSize=16,
            leading=24,
            spaceBefore=20,
            spaceAfter=12,
        )

        self.styles['heading2'] = ParagraphStyle(
            'ChineseHeading2',
            parent=base_styles['Heading2'],
            fontName=self.font_name,
            fontSize=14,
            leading=20,
            spaceBefore=15,
            spaceAfter=10,
        )

        # 正文样式
        self.styles['body'] = ParagraphStyle(
            'ChineseBody',
            parent=base_styles['Normal'],
            fontName=self.font_name,
            fontSize=11,
            leading=18,
            spaceBefore=6,
            spaceAfter=6,
        )

        # 小字样式
        self.styles['small'] = ParagraphStyle(
            'ChineseSmall',
            parent=base_styles['Normal'],
            fontName=self.font_name,
            fontSize=9,
            leading=14,
        )

        # 表格单元格样式
        self.styles['table_cell'] = ParagraphStyle(
            'ChineseTableCell',
            parent=base_styles['Normal'],
            fontName=self.font_name,
            fontSize=10,
            leading=14,
        )

        # 表格表头样式
        self.styles['table_header'] = ParagraphStyle(
            'ChineseTableHeader',
            parent=base_styles['Normal'],
            fontName=self.font_name,
            fontSize=10,
            leading=14,
            textColor=colors.whitesmoke,
            alignment=TA_CENTER,
        )

    @staticmethod
    def clean_text(text, max_length=500):
        """
        清理文本，移除HTML标签并规范化空白字符

        Args:
            text: 原始文本
            max_length: 最大长度，超过则截断

        Returns:
            清理后的文本
        """
        if text is None:
            return ""

        text = str(text)
        # 移除HTML标签
        text = re.sub(r'<[^>]+>', '', text)
        # 规范化空白字符
        text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
        # 合并多个空格
        text = ' '.join(text.split())
        # 截断长文本
        if len(text) > max_length:
            text = text[:max_length] + "..."
        return text

    def create_paragraph(self, text, style_name='body', style=None):
        """
        创建中文段落

        Args:
            text: 文本内容
            style_name: 样式名称（如果style为None）
            style: 自定义样式（优先使用）

        Returns:
            Paragraph对象
        """
        cleaned_text = self.clean_text(text)
        used_style = style if style else self.styles.get(style_name, self.styles['body'])
        return Paragraph(cleaned_text, used_style)

    def create_table(self, data, col_widths=None, header_style=None, cell_style=None):
        """
        创建包含中文的表格

        Args:
            data: 表格数据，二维列表
            col_widths: 列宽列表
            header_style: 表头单元格样式
            cell_style: 普通单元格样式

        Returns:
            Table对象
        """
        if header_style is None:
            header_style = self.styles['table_header']
        if cell_style is None:
            cell_style = self.styles['table_cell']

        # 将所有单元格转换为Paragraph
        table_data = []
        for i, row in enumerate(data):
            table_row = []
            for cell in row:
                style = header_style if i == 0 else cell_style
                if isinstance(cell, str):
                    table_row.append(self.create_paragraph(cell, style=style))
                else:
                    table_row.append(cell)
            table_data.append(table_row)

        # 创建表格
        if col_widths:
            table = Table(table_data, colWidths=col_widths)
        else:
            table = Table(table_data)

        # 设置表格样式
        table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), self.font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
        ]))

        return table

    def generate_pdf(self, output_path, title=None, subtitle=None,
                     sections=None, table_data=None, table_col_widths=None,
                     footer_text=None):
        """
        生成完整的PDF文档

        Args:
            output_path: 输出文件路径
            title: 文档标题
            subtitle: 副标题
            sections: 章节列表，每个章节为dict，包含heading和content
            table_data: 表格数据
            table_col_widths: 表格列宽
            footer_text: 页脚文本
        """
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm,
        )

        elements = []

        # 添加标题
        if title:
            elements.append(self.create_paragraph(title, 'title'))

        if subtitle:
            elements.append(self.create_paragraph(subtitle, 'subtitle'))

        if title or subtitle:
            elements.append(Spacer(1, 0.5*cm))

        # 添加章节
        if sections:
            for section in sections:
                heading = section.get('heading')
                content = section.get('content')

                if heading:
                    elements.append(self.create_paragraph(heading, 'heading1'))

                if content:
                    if isinstance(content, list):
                        for item in content:
                            elements.append(self.create_paragraph(item, 'body'))
                    else:
                        elements.append(self.create_paragraph(content, 'body'))

                elements.append(Spacer(1, 0.3*cm))

        # 添加表格
        if table_data:
            elements.append(Spacer(1, 0.5*cm))
            table = self.create_table(table_data, table_col_widths)
            elements.append(table)

        # 添加页脚
        if footer_text:
            elements.append(Spacer(1, 1*cm))
            elements.append(self.create_paragraph(footer_text, 'small'))

        # 生成PDF
        doc.build(elements)
        print(f"✓ PDF已生成: {output_path}")
        return output_path


# 便捷函数

def register_chinese_font(font_name="ChineseFont"):
    """
    注册中文字体（便捷函数）

    Args:
        font_name: 字体内置名称

    Returns:
        注册的字体内置名称
    """
    font_paths = [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]

    for path in font_paths:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(font_name, path))
                print(f"✓ 已注册中文字体: {path}")
                return font_name
            except Exception as e:
                continue

    raise RuntimeError("未找到可用的中文字体")


def clean_text(text):
    """清理文本（便捷函数）"""
    return ChinesePDFHelper.clean_text(text)


def create_chinese_paragraph(text, font_name="ChineseFont", font_size=12,
                             leading=None, alignment=TA_LEFT):
    """
    创建中文段落（便捷函数）

    Args:
        text: 文本内容
        font_name: 字体名称
        font_size: 字体大小
        leading: 行间距
        alignment: 对齐方式

    Returns:
        Paragraph对象
    """
    if leading is None:
        leading = font_size * 1.5

    style = ParagraphStyle(
        'CustomChinese',
        fontName=font_name,
        fontSize=font_size,
        leading=leading,
        alignment=alignment,
    )

    cleaned = ChinesePDFHelper.clean_text(text)
    return Paragraph(cleaned, style)


if __name__ == "__main__":
    # 测试代码
    helper = ChinesePDFHelper()

    helper.generate_pdf(
        output_path="test_chinese.pdf",
        title="中文PDF测试报告",
        subtitle="测试中文显示功能",
        sections=[
            {
                "heading": "一、测试章节",
                "content": [
                    "这是第一行中文内容，用于测试段落显示。",
                    "这是第二行中文内容，包含一些特殊字符：￥%&*@#。",
                ]
            },
            {
                "heading": "二、数据表格",
                "content": "下方是一个包含中文的表格："
            }
        ],
        table_data=[
            ["姓名", "职位", "部门", "备注"],
            ["张三", "经理", "销售部", "优秀员工"],
            ["李四", "工程师", "技术部", "项目负责人"],
            ["王五", "设计师", "设计部", "创意总监"],
        ],
        table_col_widths=[4*cm, 3*cm, 3*cm, 4*cm],
        footer_text="报告生成时间：2024年 | 机密文件"
    )