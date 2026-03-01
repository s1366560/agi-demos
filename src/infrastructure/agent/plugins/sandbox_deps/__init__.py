"""Dual-runtime dependency management for sandbox plugin tools.

This package implements host-side orchestration for installing and managing
dependencies inside sandbox Docker containers. It coordinates between the
host runtime (where ReActAgent runs) and the sandbox runtime (where MCP
tools and file system operations run).

Key components:
- models: Data models for execution context and dependency declarations
- security_gate: Package validation and allowlist enforcement
- state_store: Redis-backed state tracking for prepared environments
- sandbox_installer: Calls sandbox MCP tools for dependency installation
- orchestrator: Routes dependency installation to host pip or sandbox
"""
