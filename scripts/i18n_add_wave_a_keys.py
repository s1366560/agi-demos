"""Wave A: Add i18n keys to web/src/locales/{zh-CN,en-US}.json.

This script is idempotent: running it twice produces the same output. It
deep-merges new entries without clobbering existing ones unless the value
differs, in which case it prints a warning. Run from repo root:

    uv run python scripts/i18n_add_wave_a_keys.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

WEB_LOCALES = Path("web/src/locales")

# Each entry is a dotted path; value is a (en, zh) pair. We deliberately keep
# the additions small and localised to known UI surfaces.
ADDITIONS: dict[str, tuple[str, str]] = {
    # --- Relative time (utils/date.ts) --------------------------------------
    # common.time.justNow already exists in zh ("刚刚") — make it explicit.
    "common.time.justNow": ("just now", "刚刚"),
    "common.time.secondsAgo": ("{{count}}s ago", "{{count}}秒前"),
    "common.time.minutesAgo": ("{{count}}m ago", "{{count}}分钟前"),
    "common.time.hoursAgo": ("{{count}}h ago", "{{count}}小时前"),
    "common.time.yesterday": ("yesterday", "昨天"),
    "common.time.daysAgo": ("{{count}}d ago", "{{count}}天前"),
    "common.time.weeksAgo": ("{{count}}w ago", "{{count}}周前"),
    # --- Auth (stores/auth.ts) ----------------------------------------------
    "login.errors.invalidCredentials": (
        "Login failed. Please check your credentials.",
        "登录失败，请检查您的凭据",
    ),
    # --- Notification panel (components/shared/ui/NotificationPanel.tsx) ----
    "common.notifications.title": ("Notifications", "通知"),
    "common.notifications.empty": ("No notifications", "暂无通知"),
    "common.notifications.markAllRead": ("Mark all as read", "全部已读"),
    "common.notifications.markAsRead": ("Mark as read", "标记为已读"),
    "common.notifications.delete": ("Delete", "删除"),
    # --- Tenant selector (components/tenant/TenantSelector.tsx) -------------
    "tenant.selector.workspacesTitle": ("Workspaces", "工作空间"),
    "tenant.selector.newButton": ("New", "新建"),
    "tenant.selector.emptyMessage": ("No workspaces yet", "暂无工作空间"),
    "tenant.selector.createButton": ("Create workspace", "创建工作空间"),
    # --- Project manager (components/tenant/ProjectManager/*) ---------------
    "tenant.projectManager.searchPlaceholder": ("Search projects...", "搜索项目..."),
    "tenant.projectManager.deleteConfirm": (
        "Delete this project? This action cannot be undone.",
        "确定要删除这个项目吗？此操作不可恢复。",
    ),
    "tenant.projectManager.filterAll": ("All", "全部"),
    "tenant.projectManager.settingsTooltip": ("Project settings", "项目设置"),
    "tenant.projectManager.createdAt": ("Created {{date}}", "创建于 {{date}}"),
    # --- Project / agent teammates ------------------------------------------
    "project.agentTeammates.startConversation": ("Start conversation", "开始对话"),
}


def _set_deep(tree: dict[str, Any], path: str, value: str) -> bool:
    """Set ``path`` (dot-separated) in ``tree`` to ``value``.

    Returns True if the tree was modified, False if the existing value already
    matched. Prints a warning if an existing string value differs.
    """
    keys = path.split(".")
    cursor = tree
    for key in keys[:-1]:
        node = cursor.get(key)
        if node is None:
            new_node: dict[str, Any] = {}
            cursor[key] = new_node
            cursor = new_node
        elif isinstance(node, dict):
            cursor = node
        else:
            print(
                f"WARN: {path}: parent {key!r} is a string ({node!r}); skipping",
                file=sys.stderr,
            )
            return False
    leaf = keys[-1]
    existing = cursor.get(leaf)
    if existing == value:
        return False
    if isinstance(existing, str) and existing != value:
        print(
            f"NOTE: {path}: existing {existing!r} -> overwriting with {value!r}",
            file=sys.stderr,
        )
    cursor[leaf] = value
    return True


def main() -> int:
    if not WEB_LOCALES.is_dir():
        print(f"ERR: locales directory not found: {WEB_LOCALES}", file=sys.stderr)
        return 1

    for locale, idx in (("en-US", 0), ("zh-CN", 1)):
        path = WEB_LOCALES / f"{locale}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for dotted, pair in ADDITIONS.items():
            value = pair[idx]
            if _set_deep(data, dotted, value):
                changed = True
        if changed:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"updated {path}")
        else:
            print(f"no changes for {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
