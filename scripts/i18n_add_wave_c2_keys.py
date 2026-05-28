# pyright: basic
"""Wave C2 — keys for MemoryCreateModal.

Idempotent deep-merge into web/src/locales/{en-US,zh-CN}.json.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCALES = REPO / "web" / "src" / "locales"

EN = {
    "memory": {
        "create": {
            "title": "Create Memory",
            "tabBasic": "Basic Info",
            "tabExtraction": "Entity Extraction",
            "tabAdvanced": "Advanced Settings",
            "titleLabel": "Memory Title *",
            "titlePlaceholder": "Enter memory title",
            "contentLabel": "Memory Content *",
            "contentPlaceholder": "Enter memory content",
            "typeLabel": "Memory Type",
            "typeText": "Text",
            "typeDocument": "Document",
            "typeImage": "Image",
            "typeVideo": "Video",
            "authorLabel": "User ID",
            "authorPlaceholder": "Enter user ID (optional)",
            "authorHelp": "Optional: record the user creating this memory",
            "extractionHeading": "AI Entity Extraction",
            "extractionHint": "Click the buttons below to automatically extract entities and relationships from the text. Make sure you have entered content in Basic Info.",
            "extractEntities": "Extract Entities",
            "extractRelationships": "Extract Relationships",
            "extracting": "Extracting...",
            "extractedEntitiesHeading": "Extracted Entities",
            "extractedRelationshipsHeading": "Extracted Relationships",
            "metadataLabel": "Metadata Settings",
            "enableSearch": "Enable Search",
            "enableGraph": "Enable Graph",
            "tagsLabel": "Tags",
            "tagsPlaceholder": "Enter tags separated by commas",
            "tagsHelp": "Use commas to separate multiple tags",
            "cancel": "Cancel",
            "creating": "Creating...",
            "submit": "Create Memory",
        }
    },
}

ZH = {
    "memory": {
        "create": {
            "title": "创建记忆",
            "tabBasic": "基础信息",
            "tabExtraction": "实体提取",
            "tabAdvanced": "高级设置",
            "titleLabel": "记忆标题 *",
            "titlePlaceholder": "输入记忆标题",
            "contentLabel": "记忆内容 *",
            "contentPlaceholder": "输入记忆内容",
            "typeLabel": "记忆类型",
            "typeText": "文本",
            "typeDocument": "文档",
            "typeImage": "图片",
            "typeVideo": "视频",
            "authorLabel": "用户ID",
            "authorPlaceholder": "输入用户ID（可选）",
            "authorHelp": "可选：记录创建此记忆的用户",
            "extractionHeading": "AI 实体提取",
            "extractionHint": "点击下面的按钮来自动提取文本中的实体和关系。确保你已经在基础信息中输入了内容。",
            "extractEntities": "提取实体",
            "extractRelationships": "提取关系",
            "extracting": "提取中...",
            "extractedEntitiesHeading": "提取的实体",
            "extractedRelationshipsHeading": "提取的关系",
            "metadataLabel": "元数据设置",
            "enableSearch": "启用搜索",
            "enableGraph": "启用图谱",
            "tagsLabel": "标签",
            "tagsPlaceholder": "输入标签，用逗号分隔",
            "tagsHelp": "使用逗号分隔多个标签",
            "cancel": "取消",
            "creating": "创建中...",
            "submit": "创建记忆",
        }
    },
}


def deep_merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def update(path: Path, payload: dict) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    deep_merge(data, payload)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"updated {path}")


update(LOCALES / "en-US.json", EN)
update(LOCALES / "zh-CN.json", ZH)
