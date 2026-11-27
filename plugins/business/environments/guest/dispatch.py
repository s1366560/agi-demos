"""Map admitted command names onto host capabilities."""

from __future__ import annotations

from plugins.business.guest_runtime.binding import bind_operation

OPERATIONS = {
    name: bind_operation(name)
    for name in (
        "app.environments.sandbox.read",
        "app.environments.sandbox.prepare",
        "app.environments.terminal.authorize",
        "app.environments.inventory.read",
        "app.environments.clusters.write",
        "app.environments.clusters.delete",
        "app.environments.sandbox.restart",
        "app.environments.sandbox.terminate",
        "app.environments.terminal.interact",
        "app.environments.desktop.interact",
        "app.environments.runners.read",
        "app.environments.runners.create",
        "app.environments.runners.register",
        "app.environments.deploys.read",
        "app.environments.deploys.write",
        "app.environments.templates.read",
        "app.environments.templates.write",
        "app.environments.instances.create",
        "app.environments.pool.read",
        "app.environments.pool.control",
        "app.environments.pool.tier",
    )
}

TOOLS = {
    "environments.sandbox-status": "app.environments.sandbox.read",
    "environments.prepare-sandbox": "app.environments.sandbox.prepare",
    "environments.authorize-run-terminal": "app.environments.terminal.authorize",
    "environments.environment-inventory": "app.environments.inventory.read",
    "environments.write-cluster": "app.environments.clusters.write",
    "environments.delete-cluster": "app.environments.clusters.delete",
    "environments.restart-sandbox": "app.environments.sandbox.restart",
    "environments.terminate-sandbox": "app.environments.sandbox.terminate",
    "environments.project-terminal": "app.environments.terminal.interact",
    "environments.project-desktop": "app.environments.desktop.interact",
    "environments.list-runner-pools": "app.environments.runners.read",
    "environments.create-runner-pool": "app.environments.runners.create",
    "environments.register-runner": "app.environments.runners.register",
    "environments.read-deploys": "app.environments.deploys.read",
    "environments.change-deploy": "app.environments.deploys.write",
    "environments.read-instance-templates": "app.environments.templates.read",
    "environments.change-instance-template": "app.environments.templates.write",
    "environments.create-runtime-instance": "app.environments.instances.create",
    "environments.read-runtime-pool": "app.environments.pool.read",
    "environments.control-runtime-pool": "app.environments.pool.control",
    "environments.set-runtime-pool-tier": "app.environments.pool.tier",
}
