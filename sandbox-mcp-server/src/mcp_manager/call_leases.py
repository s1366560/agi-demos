"""Drain active tool calls before stopping a managed plugin process."""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable
from weakref import WeakKeyDictionary


@dataclass
class _Lease:
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    active: int = 0
    draining: bool = False


_leases: WeakKeyDictionary[object, dict[str, _Lease]] = WeakKeyDictionary()


def _lease(owner: object, name: str) -> _Lease:
    return _leases.setdefault(owner, {}).setdefault(name, _Lease())


def tool_call_lease(function: Callable[..., Any]) -> Callable[..., Any]:
    """Pin this process while an admitted tool call is running."""
    signature = inspect.signature(function)

    @wraps(function)
    async def wrapped(self: object, *args: Any, **kwargs: Any) -> Any:
        name = signature.bind(self, *args, **kwargs).arguments["server_name"]
        state = _lease(self, name)
        async with state.condition:
            if state.draining:
                raise RuntimeError("MCP server is stopping; new calls are not admitted")
            state.active += 1
        try:
            return await function(self, *args, **kwargs)
        finally:
            async with state.condition:
                state.active -= 1
                state.condition.notify_all()

    return wrapped


def drain_tool_calls(function: Callable[..., Any]) -> Callable[..., Any]:
    """Stop admission, wait for admitted calls, and only then stop the process."""
    signature = inspect.signature(function)

    @wraps(function)
    async def wrapped(self: object, *args: Any, **kwargs: Any) -> Any:
        name = signature.bind(self, *args, **kwargs).arguments["name"]
        state = _lease(self, name)
        async with state.condition:
            await state.condition.wait_for(lambda: not state.draining)
            state.draining = True
        try:
            async with state.condition:
                await state.condition.wait_for(lambda: state.active == 0)
            return await function(self, *args, **kwargs)
        finally:
            async with state.condition:
                state.draining = False
                state.condition.notify_all()

    return wrapped
