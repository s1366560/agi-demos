"""Enums for the Cluster bounded context."""

from enum import Enum


class ClusterProvider(str, Enum):
    """Supported cluster infrastructure providers."""

    vke = "vke"  # Volcengine Kubernetes Engine
    ack = "ack"  # Alibaba Container Service for Kubernetes
    tke = "tke"  # Tencent Kubernetes Engine
    custom = "custom"  # Self-managed K8s
    docker = "docker"  # Docker-based (dev/test)


class ClusterStatus(str, Enum):
    """Runtime connectivity status of a cluster."""

    connected = "connected"
    disconnected = "disconnected"
    connecting = "connecting"
