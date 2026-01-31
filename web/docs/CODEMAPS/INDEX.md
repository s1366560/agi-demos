# CodeMaps Index

**Last Updated:** 2025-01-31

This directory contains architectural documentation (codemaps) for the MemStack web frontend.

## Available Codemaps

| Document | Description | Last Updated |
|----------|-------------|--------------|
| [frontend.md](./frontend.md) | Frontend architecture overview | 2025-01-31 |

## Overview

The MemStack web frontend is a React 19.2.3 application built with TypeScript, using:
- **Vite 7.3.0** for fast development and optimized builds
- **Zustand 5.0.9** for state management
- **React Router 7.11.0** for client-side routing
- **Ant Design 6.1.1** + **Tailwind CSS 4.1.18** for UI components
- **Vitest 4.0.16** + **Playwright 1.57.0** for testing

## Key Architectural Patterns

### State Management
- Zustand stores for global state (auth, agent, tenant, project, etc.)
- Modular agent sub-stores for separation of concerns
- Persist middleware for localStorage integration

### Routing
- Lazy-loaded route components for code splitting
- Protected routes with authentication guards
- Nested layouts for tenant/project/schema contexts

### API Communication
- REST API via Axios wrapper (httpClient)
- Server-Sent Events (SSE) for agent streaming
- WebSocket support for sandbox connections
- Request deduplication and caching

### Component Organization
- Agent components: Chat, execution, patterns, sandbox
- Layout components: App-wide wrappers
- Page components: Route-specific (lazy-loaded)
- Shared components: Reusable UI elements

## Quick Navigation

### For New Developers
1. Start with [frontend.md](./frontend.md) for architecture overview
2. Review `src/main.tsx` for application bootstrap
3. Examine `src/App.tsx` for routing structure
4. Check `src/stores/` for state management patterns

### For Agent Development
1. Agent chat: `src/stores/agentV3.ts` + `src/services/agentService.ts`
2. Components: `src/components/agent/`
3. Types: `src/types/agent.ts`
4. SSE adapter: `src/utils/sseEventAdapter.ts`

### For UI Development
1. Theme: `src/theme/` (Ant Design + Tailwind)
2. Shared components: `src/components/shared/`
3. Layout components: `src/layouts/`
4. Common components: `src/components/common/`

### For API Integration
1. HTTP client: `src/services/client/httpClient.ts`
2. API services: `src/services/api.ts`
3. Error handling: `src/services/client/ApiError.ts`
4. Token resolver: `src/utils/tokenResolver.ts`

## Maintenance

When updating the frontend:
1. Update corresponding codemap section
2. Update "Last Updated" timestamp
3. Add new sections for major features
4. Keep diagrams in sync with code structure

## Related Documentation

- Root docs: `/docs/` (architecture, integration plans)
- Project README: `/web/README.md`
- CLAUDE.md: `/CLAUDE.md` (project instructions)
