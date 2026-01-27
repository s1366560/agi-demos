I will completely remove the legacy `SSEEvent` and `SSEEventType` classes and their usages to unify the event system under `AgentDomainEvent`.

Steps:

1. **Cleanup** **`src/infrastructure/agent/core/processor.py`**: Remove unused imports of `SSEEvent` and `SSEEventType`.
2. **Cleanup** **`src/infrastructure/agent/core/react_agent.py`**: Remove unused imports of `SSEEvent` and `SSEEventType`.
3. **Cleanup** **`src/infrastructure/agent/core/__init__.py`**: Remove `SSEEvent` and `SSEEventType` from imports and `__all__` export list.
4. **Delete** **`src/infrastructure/agent/core/events.py`**: Delete this file as it only contains the deprecated legacy event classes.
5. **Verification**: Run a check to ensure no broken imports remain.

