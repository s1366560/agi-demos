"""Enums for the Deploy bounded context."""

from enum import Enum


class DeployAction(str, Enum):
    """Action type for a deployment record."""

    create = "create"
    update = "update"
    scale = "scale"
    restart = "restart"
    rollback = "rollback"
    config_apply = "config_apply"
    delete = "delete"


class DeployStatus(str, Enum):
    """Lifecycle status of a deployment record."""

    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"
