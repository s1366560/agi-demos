# pyright: basic
"""Wave C4 — keys for ProjectManager/States.tsx (empty/loading state copy)."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCALES = REPO / "web" / "src" / "locales"

EN = {
    "tenant": {
        "projectManager": {
            "states": {
                "noTenantMessage": "Please select a workspace first",
                "noTenantSubtitle": "Select a workspace to view and manage projects",
                "noResultsMessage": "No matching projects found",
                "noResultsSubtitle": "Try using different search keywords",
                "noProjectsMessage": "Start by creating your first project",
                "noProjectsSubtitle": "Create a project to organize your memories and knowledge",
                "createProjectButton": "Create Project",
                "errorDismiss": "Dismiss",
            }
        }
    }
}

ZH = {
    "tenant": {
        "projectManager": {
            "states": {
                "noTenantMessage": "请先选择工作空间",
                "noTenantSubtitle": "选择一个工作空间来查看和管理项目",
                "noResultsMessage": "没有找到匹配的项目",
                "noResultsSubtitle": "尝试使用不同的搜索关键词",
                "noProjectsMessage": "开始创建你的第一个项目",
                "noProjectsSubtitle": "创建项目来开始组织你的记忆和知识",
                "createProjectButton": "创建项目",
                "errorDismiss": "关闭",
            }
        }
    }
}


def deep_merge(base: dict, updates: dict) -> dict:
    out = dict(base)
    for key, value in updates.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def update(path: Path, additions: dict) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    merged = deep_merge(data, additions)
    path.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    update(LOCALES / "en-US.json", EN)
    update(LOCALES / "zh-CN.json", ZH)
    print("Wave C4 keys added.")


if __name__ == "__main__":
    main()
