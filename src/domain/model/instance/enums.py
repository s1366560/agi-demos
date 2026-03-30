"""Instance-related enumerations.

Defines status, service type, and role enums for the Instance bounded context.
"""

from enum import Enum


class InstanceStatus(str, Enum):
    """Lifecycle status of an Instance."""

    creating = "creating"
    deploying = "deploying"
    running = "running"
    stopped = "stopped"
    error = "error"
    restarting = "restarting"
    scaling = "scaling"
    learning = "learning"
    deleting = "deleting"


class ServiceType(str, Enum):
    """Kubernetes service exposure type."""

    cluster_ip = "ClusterIP"
    node_port = "NodePort"
    load_balancer = "LoadBalancer"


class InstanceRole(str, Enum):
    """Role of a member within an Instance."""

    admin = "admin"
    editor = "editor"
    user = "user"
    viewer = "viewer"
