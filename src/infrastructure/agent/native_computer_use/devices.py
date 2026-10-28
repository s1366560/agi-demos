"""Expiring device registrations bound to one authenticated WebSocket."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict
from typing import Any, cast

from src.infrastructure.agent.native_computer_use.contracts import DeviceScope
from src.infrastructure.agent.native_computer_use.effects import argument_schema
from src.infrastructure.agent.native_computer_use.schema import validator
from src.infrastructure.agent.native_computer_use.store import (
    LEASE_SECONDS,
    PREFIX,
    BridgeStore,
    DeviceBridgeError,
    digest,
    encoded,
    identifier,
    scope_key,
    string,
)


def device_key(scope: DeviceScope) -> str:
    return f"{PREFIX}:device:{scope_key(**{k: v for k, v in asdict(scope).items() if k != 'device_id'})}:{digest(scope.device_id)}"


def owner_devices(user_id: str, tenant_id: str, project_id: str) -> str:
    owner = scope_key(user_id=user_id, tenant_id=tenant_id, project_id=project_id)
    return f"{PREFIX}:devices:{owner}"


def connection_devices(connection_id: str) -> str:
    return f"{PREFIX}:connection:{identifier(connection_id)}"


class DeviceRegistry(BridgeStore):
    async def register(
        self, scope: DeviceScope, connection_id: str, definitions: list[dict[str, Any]]
    ) -> None:
        from src.infrastructure.agent.native_computer_use.catalog import validate_tool_definition

        identifier(connection_id)
        if len(definitions) > 2048:
            raise DeviceBridgeError("computer_use_invalid_catalog")
        names: set[str] = set()
        for definition in definitions:
            name = definition.get("name")
            schema = definition.get("inputSchema")
            if (
                not isinstance(name, str)
                or name in names
                or not isinstance(schema, dict)
                or schema.get("type") != "object"
                or not isinstance(definition.get("description"), str)
            ):
                raise DeviceBridgeError("computer_use_invalid_catalog")
            validate_tool_definition(name, schema)
            names.add(name)
            validator(argument_schema(schema))
        if len(encoded(definitions).encode()) > 256 * 1024:
            raise DeviceBridgeError("computer_use_catalog_too_large")
        key = device_key(scope)

        def change(previous: dict[str, Any] | None) -> dict[str, Any]:
            if previous is not None and previous["connection_id"] != connection_id:
                raise DeviceBridgeError("device_busy")
            return {
                **asdict(scope),
                "connection_id": connection_id,
                "tool_definitions": definitions,
            }

        await self.update(key, change, ttl=LEASE_SECONDS)
        owner = owner_devices(scope.user_id, scope.tenant_id, scope.project_id)
        index = connection_devices(connection_id)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.sadd(owner, key)
            pipe.expire(owner, 24 * 3600)
            pipe.sadd(index, key)
            pipe.expire(index, LEASE_SECONDS)
            await pipe.execute()

    async def list(self, *, user_id: str, tenant_id: str, project_id: str) -> list[dict[str, Any]]:
        index = owner_devices(user_id, tenant_id, project_id)
        keys = await self.members(index)
        devices = []
        for raw_key in keys:
            key = string(raw_key)
            value = await self.read(key)
            if value is None:
                await self.remove_member(index, key)
            elif all(
                value.get(k) == v
                for k, v in {
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                }.items()
            ):
                devices.append(value)
        return devices

    async def heartbeat(self, connection_id: str) -> None:
        index = connection_devices(connection_id)
        for raw_key in await self.members(index):
            key = string(raw_key)
            async with self.redis.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(key)
                    value = await self.read(key)
                    if value is None or value["connection_id"] != connection_id:
                        continue
                    cast(Callable[[], object], pipe.multi)()
                    pipe.expire(key, LEASE_SECONDS)
                    await pipe.execute()
                except Exception as exc:
                    from redis.exceptions import WatchError

                    if not isinstance(exc, WatchError):
                        raise
        await self.redis.expire(index, LEASE_SECONDS)

    async def disconnect(self, connection_id: str) -> None:
        index = connection_devices(connection_id)
        for raw_key in await self.members(index):
            key = string(raw_key)

            def change(value: dict[str, Any] | None) -> dict[str, Any]:
                if value is None or value["connection_id"] != connection_id:
                    raise DeviceBridgeError("computer_use_device_disconnected")
                return {**value, "tool_definitions": []}

            with suppress(DeviceBridgeError):
                # A one-second tombstone prevents an old connection deleting a successor.
                await self.update(key, change, ttl=1)
        await self.redis.delete(index)
