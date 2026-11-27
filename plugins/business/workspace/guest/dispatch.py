"""Map admitted command names onto host capabilities."""

from __future__ import annotations

from plugins.business.guest_runtime.binding import bind_operation

OPERATIONS = {
    name: bind_operation(name)
    for name in (
        "app.workspace.directory.read",
        "app.workspace.detail.read",
        "app.workspace.create",
        "app.workspace.settings.update",
        "app.workspace.members.read",
        "app.workspace.members.write",
        "app.workspace.posts.read",
        "app.workspace.posts.write",
        "app.workspace.tasks.read",
        "app.workspace.tasks.write",
        "app.workspace.blackboard.read",
        "app.workspace.blackboard.write",
        "app.workspace.overview.read",
        "app.workspace.chat.read",
        "app.workspace.chat.send",
    )
}

TOOLS = {
    "workspace.list-directory": "app.workspace.directory.read",
    "workspace.read-workspace": "app.workspace.detail.read",
    "workspace.create-workspace": "app.workspace.create",
    "workspace.update-workspace": "app.workspace.settings.update",
    "workspace.list-members": "app.workspace.members.read",
    "workspace.change-members": "app.workspace.members.write",
    "workspace.list-posts": "app.workspace.posts.read",
    "workspace.change-posts": "app.workspace.posts.write",
    "workspace.list-tasks": "app.workspace.tasks.read",
    "workspace.change-tasks": "app.workspace.tasks.write",
    "workspace.blackboard-read": "app.workspace.blackboard.read",
    "workspace.blackboard-change": "app.workspace.blackboard.write",
    "workspace.read-project-overview": "app.workspace.overview.read",
    "workspace.read-group-chat": "app.workspace.chat.read",
    "workspace.send-group-message": "app.workspace.chat.send",
}
