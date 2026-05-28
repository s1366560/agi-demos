"""Wave B: Add i18n keys to web/src/locales/{zh-CN,en-US}.json.

Idempotent. Run from repo root:

    uv run python scripts/i18n_add_wave_b_keys.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

WEB_LOCALES = Path("web/src/locales")

ADDITIONS: dict[str, tuple[str, str]] = {
    # --- mcp.tools (McpToolsTabV2) ------------------------------------------
    "mcp.tools.allServers": ("All servers", "全部服务器"),
    "mcp.tools.loading": ("Loading tools...", "加载工具中..."),
    "mcp.tools.totalTools": ("Total tools", "工具总数"),
    "mcp.tools.serversWithTools": ("Servers with tools", "有工具的服务器"),
    "mcp.tools.showCount": (
        "Showing {{shown}} / {{total}}",
        "显示 {{shown}} / {{total}}",
    ),
    "mcp.tools.searchPlaceholder": (
        "Search tool name or description...",
        "搜索工具名称或描述...",
    ),
    "mcp.tools.filterByServer": ("Filter by server", "按服务器筛选"),
    "mcp.tools.emptyNoTools": ("No tools yet", "暂无工具"),
    "mcp.tools.emptyNoMatch": ("No matching tools", "无匹配工具"),
    "mcp.tools.hintSync": (
        "Sync an MCP server to discover available tools",
        "同步 MCP 服务器以发现可用工具",
    ),
    "mcp.tools.hintAdjust": (
        "Try adjusting your search or filters",
        "尝试调整搜索或筛选条件",
    ),
    # --- agent.executionTimeline --------------------------------------------
    "agent.executionTimeline.title": ("Execution plan", "执行计划"),
    "agent.executionTimeline.stepsCompleted": (
        "{{completed}}/{{total}} steps completed",
        "{{completed}}/{{total}} 步骤已完成",
    ),
    "agent.executionTimeline.matchedPattern": (
        "Matched pattern ({{percent}}%)",
        "匹配模式 ({{percent}}%)",
    ),
    "agent.executionTimeline.statusCompleted": ("Completed", "已完成"),
    "agent.executionTimeline.statusRunning": ("Running", "执行中"),
    "agent.executionTimeline.statusWaiting": ("Waiting", "等待中"),
    "agent.executionTimeline.toolsLabel": ("{{count}} tools", "{{count}} 工具"),
    "agent.executionTimeline.runningEllipsis": ("Running...", "执行中..."),
    "agent.executionTimeline.expandAll": ("Expand all", "展开全部"),
    "agent.executionTimeline.collapseAll": ("Collapse all", "收起全部"),
    # --- memory.edit (EditMemoryModal) --------------------------------------
    "memory.edit.title": ("Edit memory", "编辑记忆"),
    "memory.edit.titleLabel": ("Title", "标题"),
    "memory.edit.titlePlaceholder": ("Enter memory title", "输入记忆标题"),
    "memory.edit.contentLabel": ("Content", "内容"),
    "memory.edit.contentPlaceholder": ("Enter memory content...", "输入记忆内容..."),
    "memory.edit.tagsLabel": ("Tags", "标签"),
    "memory.edit.removeTagAria": ("Remove tag {{tag}}", "移除标签 {{tag}}"),
    "memory.edit.addTag": ("Add", "添加"),
    "memory.edit.optimisticLockWarning": (
        "This memory uses optimistic locking. If another user modified it "
        "concurrently, please reload and try again.",
        "⚠️ 此记忆使用乐观锁定。如果其他用户同时修改了此记忆，您需要刷新页面后重试。",
    ),
    "memory.edit.cancel": ("Cancel", "取消"),
    "memory.edit.saving": ("Saving...", "保存中..."),
    "memory.edit.save": ("Save changes", "保存更改"),
    # --- agent.costTracker --------------------------------------------------
    "agent.costTracker.inputTokens": (
        "Input tokens: {{count}}",
        "输入 Tokens: {{count}}",
    ),
    "agent.costTracker.outputTokens": (
        "Output tokens: {{count}}",
        "输出 Tokens: {{count}}",
    ),
    "agent.costTracker.totalTokens": ("Total: {{count}}", "总计: {{count}}"),
    "agent.costTracker.costLabel": ("Cost: {{value}}", "费用: {{value}}"),
    "agent.costTracker.modelLabel": ("Model: {{model}}", "模型: {{model}}"),
    "agent.costTracker.empty": ("No cost data yet", "暂无费用数据"),
    "agent.costTracker.modelPrefix": ("Model:", "模型："),
    "agent.costTracker.tokenUsage": ("Token usage", "Token 使用"),
    "agent.costTracker.inputShort": ("Input:", "输入:"),
    "agent.costTracker.outputShort": ("Output:", "输出:"),
    "agent.costTracker.estimatedCost": ("Estimated cost", "估算费用"),
    "agent.costTracker.updatedAt": (
        "Updated: {{time}}",
        "更新于: {{time}}",
    ),
    # --- mcp.apps (McpAppsTabV2) --------------------------------------------
    "mcp.apps.deleteSuccess": ("MCP app deleted", "MCP 应用已删除"),
    "mcp.apps.deleteFailed": ("Failed to delete MCP app", "删除 MCP 应用失败"),
    "mcp.apps.refreshSuccess": ("App refreshed", "应用已刷新"),
    "mcp.apps.retryFailed": ("Retry failed", "重试失败"),
    "mcp.apps.loading": ("Loading MCP apps...", "加载 MCP 应用中..."),
    "mcp.apps.totalApps": ("Total apps", "应用总数"),
    "mcp.apps.statusReady": ("Ready", "就绪"),
    "mcp.apps.statusLoading": ("Loading", "加载中"),
    "mcp.apps.statusError": ("Error", "错误"),
    "mcp.apps.searchPlaceholder": ("Search apps...", "搜索应用..."),
    "mcp.apps.refresh": ("Refresh", "刷新"),
    "mcp.apps.empty": ("No MCP apps", "暂无 MCP 应用"),
    "mcp.apps.emptyHint": (
        "Apps will appear here once MCP servers are discovered.",
        "发现 MCP 服务器后，应用将自动显示在此处",
    ),
    # --- mcp.appCard (McpAppCardV2) -----------------------------------------
    "mcp.appCard.runtimePrefix": ("Runtime: {{value}}", "运行：{{value}}"),
    "mcp.appCard.resourceUri": ("Resource URI", "资源地址"),
    "mcp.appCard.noResourceUri": ("No resource URI", "无资源地址"),
    "mcp.appCard.refreshWithStatus": (
        "Refresh {{status}}",
        "刷新 {{status}}",
    ),
    "mcp.appCard.retry": ("Retry", "重试"),
    "mcp.appCard.slowLoadHint": (
        "Loading is taking longer than usual; try refreshing.",
        "加载时间较长，请尝试刷新",
    ),
    "mcp.appCard.developerAI": ("AI", "AI"),
    "mcp.appCard.developerUser": ("User", "用户"),
    "mcp.appCard.open": ("Open", "打开"),
    "mcp.appCard.deleteConfirm": (
        "Are you sure you want to delete this app?",
        "确定要删除此应用吗？",
    ),
    "mcp.appCard.deleteOk": ("Delete", "删除"),
    "mcp.appCard.deleteCancel": ("Cancel", "取消"),
    # --- tenant.create (TenantCreateModal) ----------------------------------
    "tenant.createModal.title": ("Create workspace", "创建工作空间"),
    "tenant.createModal.nameLabel": ("Workspace name", "工作空间名称"),
    "tenant.createModal.namePlaceholder": (
        "Enter workspace name",
        "输入工作空间名称",
    ),
    "tenant.createModal.descriptionLabel": ("Description", "描述"),
    "tenant.createModal.descriptionPlaceholder": (
        "Describe what this workspace is for",
        "描述这个工作空间的用途",
    ),
    "tenant.createModal.descriptionHint": (
        "Optional: describe the workspace purpose",
        "可选：描述工作空间的用途",
    ),
    "tenant.createModal.planLabel": ("Plan", "计划类型"),
    "tenant.createModal.planFree": ("Free", "免费版"),
    "tenant.createModal.planBasic": ("Basic", "基础版"),
    "tenant.createModal.planPremium": ("Premium", "高级版"),
    "tenant.createModal.planEnterprise": ("Enterprise", "企业版"),
    "tenant.createModal.cancel": ("Cancel", "取消"),
    "tenant.createModal.creating": ("Creating...", "创建中..."),
    "tenant.createModal.submit": ("Create", "创建"),
    # --- agent.lifecycle (useAgentLifecycleState) ---------------------------
    "agent.lifecycle.notStarted.label": ("Not started", "未启动"),
    "agent.lifecycle.notStarted.description": (
        "Agent has not been initialised; it will start on the first request.",
        "Agent 尚未初始化，将在首次请求时自动启动",
    ),
    "agent.lifecycle.initializing.label": ("Initializing", "初始化中"),
    "agent.lifecycle.initializing.description": (
        "Loading tools, skills, and configuration",
        "正在加载工具、技能和配置",
    ),
    "agent.lifecycle.ready.label": ("Ready", "就绪"),
    "agent.lifecycle.ready.description": (
        "Agent is ready, {{count}} tools loaded",
        "Agent 已就绪，{{count}} 个工具",
    ),
    "agent.lifecycle.running.label": ("Running", "执行中"),
    "agent.lifecycle.running.description": (
        "Processing chat requests",
        "正在处理聊天请求",
    ),
    "agent.lifecycle.paused.label": ("Paused", "已暂停"),
    "agent.lifecycle.paused.description": (
        "Agent is paused and not accepting new requests",
        "Agent 已暂停，不接收新请求",
    ),
    "agent.lifecycle.shuttingDown.label": ("Shutting down", "关闭中"),
    "agent.lifecycle.shuttingDown.description": (
        "Agent is shutting down",
        "Agent 正在关闭",
    ),
    "agent.lifecycle.error.label": ("Error", "错误"),
    "agent.lifecycle.error.description": (
        "Agent encountered an error",
        "Agent 遇到错误",
    ),
    "agent.lifecycle.unknown.label": ("Unknown", "未知"),
    "agent.lifecycle.unknown.description": (
        "Agent state is unknown",
        "Agent 状态未知",
    ),
}


def _set_deep(tree: dict[str, Any], path: str, value: str) -> bool:
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
