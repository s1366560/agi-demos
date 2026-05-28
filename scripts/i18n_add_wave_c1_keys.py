# pyright: basic
"""Wave C batch 1 — add i18n keys for ProjectSettingsModal, MemoryDetailModal,
MemoryManager.

Idempotent: deep-merges into web/src/locales/{en-US,zh-CN}.json.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCALES = REPO / "web" / "src" / "locales"

EN = {
    "project": {
        "settings": {
            "title": "Project Settings",
            "nameLabel": "Project Name *",
            "namePlaceholder": "Enter project name",
            "descriptionLabel": "Description",
            "descriptionPlaceholder": "Add project description...",
            "publicLabel": "Public Project",
            "publicHint": "Public projects can be accessed by anyone with the link",
            "agentModeLabel": "Agent Conversation Mode",
            "agentMode": {
                "singleAgent": {
                    "label": "Single Agent (Default)",
                    "hint": "Each conversation routes to a single Agent; HITL appears as a private modal.",
                },
                "multiShared": {
                    "label": "Multi-Agent Shared Channel",
                    "hint": "Multiple Agents collaborate in the same conversation; HITL is exposed as channel messages.",
                },
                "multiIsolated": {
                    "label": "Multi-Agent Isolated Threads",
                    "hint": "Each Agent keeps an isolated thread, displayed side-by-side without interference.",
                },
            },
            "projectIdPrefix": "Project ID:",
            "createdAtPrefix": "Created",
            "deleteConfirmMessage": "Are you sure you want to delete this project? This action cannot be undone. All related memories and data will be deleted.",
            "cancel": "Cancel",
            "deleting": "Deleting...",
            "confirmDelete": "Confirm Delete",
            "deleteProject": "Delete Project",
            "saving": "Saving...",
            "saveChanges": "Save Changes",
        }
    },
    "memory": {
        "detail": {
            "editTitle": "Edit Memory",
            "title": "Memory Details",
            "saveAria": "Save",
            "saveTitle": "Save",
            "cancelAria": "Cancel editing",
            "cancelTitle": "Cancel",
            "editAria": "Edit",
            "editTitleTooltip": "Edit",
            "shareAria": "Share",
            "shareTitle": "Share",
            "downloadAria": "Download",
            "downloadTitle": "Download",
            "closeAria": "Close",
            "versionConflict": "Version conflict: this memory was modified by another user. Please refresh and try again.",
            "saveFailed": "Save failed, please try again later",
            "linkCopied": "Link copied to clipboard!",
            "linkCopyFailed": "Failed to copy link",
            "titlePlaceholder": "Memory Title",
            "userPrefix": "User:",
            "createdPrefix": "Created:",
            "updatedPrefix": "Updated:",
            "contentHeading": "Memory Content",
            "contentPlaceholder": "Enter memory content...",
            "entitiesHeading": "Entities",
            "relationshipsHeading": "Relationships",
            "confidencePrefix": "Confidence:",
            "metadataHeading": "Metadata",
            "projectPrefix": "Project:",
            "viewCountPrefix": "Views:",
        },
        "manager": {
            "selectProjectFirstHeading": "Select a Project First",
            "selectProjectHint": "Select a project to view and manage memories",
            "title": "Memory Management",
            "countSuffix": "({{count}} items)",
            "newButton": "New Memory",
            "searchPlaceholder": "Search memories...",
            "typeAll": "All Types",
            "typeText": "Text",
            "typeDocument": "Document",
            "typeImage": "Image",
            "typeVideo": "Video",
            "userFilterPlaceholder": "Filter by user...",
            "search": "Search",
            "reset": "Reset",
            "emptyHeading": "No Memories",
            "emptyNoMatch": "No matching memories found",
            "emptyHint": "Start creating your first memory",
            "createMemory": "Create Memory",
            "deleteConfirm": "Are you sure you want to delete this memory? This action cannot be undone.",
            "entitiesLabel": "Entities",
            "relationshipsLabel": "Relationships",
        },
    }
}

ZH = {
    "project": {
        "settings": {
            "title": "项目设置",
            "nameLabel": "项目名称 *",
            "namePlaceholder": "输入项目名称",
            "descriptionLabel": "描述",
            "descriptionPlaceholder": "添加项目描述...",
            "publicLabel": "公开项目",
            "publicHint": "公开项目可以被任何拥有链接的人访问",
            "agentModeLabel": "Agent 会话模式",
            "agentMode": {
                "singleAgent": {
                    "label": "单 Agent(默认)",
                    "hint": "每个会话只路由到一个 Agent，HITL 以私密 modal 呈现。",
                },
                "multiShared": {
                    "label": "多 Agent 共享频道",
                    "hint": "多个 Agent 在同一会话中协作；HITL 将以频道消息形式公开。",
                },
                "multiIsolated": {
                    "label": "多 Agent 独立线程",
                    "hint": "每个 Agent 保留独立线程，并排展示，互不干扰。",
                },
            },
            "projectIdPrefix": "项目ID:",
            "createdAtPrefix": "创建于",
            "deleteConfirmMessage": "确定要删除此项目吗？此操作不可恢复，所有相关的记忆和数据都将被删除。",
            "cancel": "取消",
            "deleting": "删除中...",
            "confirmDelete": "确认删除",
            "deleteProject": "删除项目",
            "saving": "保存中...",
            "saveChanges": "保存更改",
        }
    },
    "memory": {
        "detail": {
            "editTitle": "编辑记忆",
            "title": "记忆详情",
            "saveAria": "保存",
            "saveTitle": "保存",
            "cancelAria": "取消编辑",
            "cancelTitle": "取消",
            "editAria": "编辑",
            "editTitleTooltip": "编辑",
            "shareAria": "分享",
            "shareTitle": "分享",
            "downloadAria": "下载",
            "downloadTitle": "下载",
            "closeAria": "关闭",
            "versionConflict": "版本冲突：该记忆已被其他用户修改。请刷新页面后重试。",
            "saveFailed": "保存失败，请稍后重试",
            "linkCopied": "链接已复制到剪贴板！",
            "linkCopyFailed": "复制链接失败",
            "titlePlaceholder": "记忆标题",
            "userPrefix": "用户:",
            "createdPrefix": "创建:",
            "updatedPrefix": "更新:",
            "contentHeading": "记忆内容",
            "contentPlaceholder": "输入记忆内容...",
            "entitiesHeading": "实体信息",
            "relationshipsHeading": "关系信息",
            "confidencePrefix": "置信度:",
            "metadataHeading": "元数据",
            "projectPrefix": "项目:",
            "viewCountPrefix": "查看次数:",
        },
        "manager": {
            "selectProjectFirstHeading": "请先选择项目",
            "selectProjectHint": "选择一个项目来查看和管理记忆",
            "title": "记忆管理",
            "countSuffix": "({{count}} 条)",
            "newButton": "新建记忆",
            "searchPlaceholder": "搜索记忆内容...",
            "typeAll": "所有类型",
            "typeText": "文本",
            "typeDocument": "文档",
            "typeImage": "图片",
            "typeVideo": "视频",
            "userFilterPlaceholder": "按用户筛选...",
            "search": "搜索",
            "reset": "重置",
            "emptyHeading": "暂无记忆",
            "emptyNoMatch": "没有找到匹配的记忆",
            "emptyHint": "开始创建你的第一条记忆",
            "createMemory": "创建记忆",
            "deleteConfirm": "确定要删除这条记忆吗？此操作不可恢复。",
            "entitiesLabel": "实体",
            "relationshipsLabel": "关系",
        },
    }
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
