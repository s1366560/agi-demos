"""
Agent Container Module.

Provides containerized agent workers for HOT tier deployment:
- Dockerfile.agent: Container image definition
- agent_pool.proto: gRPC protocol definition
- server.py: gRPC server implementation

Usage:
    # Build the container image
    docker build -f src/infrastructure/agent/pool/container/Dockerfile.agent \
        -t memstack-agent-worker:latest .
    
    # Run a container
    docker run -d --name agent-hot-1 \
        -e AGENT_INSTANCE_ID=tenant:project:chat \
        -p 50051:50051 \
        memstack-agent-worker:latest
"""

from .server import AgentContainerConfig, AgentContainerServer

__all__ = [
    "AgentContainerConfig",
    "AgentContainerServer",
]
