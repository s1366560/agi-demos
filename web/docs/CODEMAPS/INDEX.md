# CodeMaps Index

Last updated: 2026-05-18.

This directory contains maintained codemaps for the MemStack web frontend.

## Available Codemaps

| Document | Description |
|---|---|
| [frontend.md](frontend.md) | Current web architecture, routes, stores, services, and data flow. |

## Current Frontend Facts

- React 19.2.3, TypeScript 5.9.3, Vite 7.3.0.
- React Router 7.11.0 with lazy-loaded routes.
- Ant Design 6.1.1 and Tailwind CSS 4.1.18.
- Zustand 5.0.9 and TanStack Query 5.99.2.
- Live agent transport is WebSocket via `WS /api/v1/agent/ws`.
- HTTP services use `httpClient` with `baseURL = "/api/v1"`.

## Related Docs

- [../../README.md](../../README.md)
- [../README.md](../README.md)
- [../../../docs/README.md](../../../docs/README.md)
