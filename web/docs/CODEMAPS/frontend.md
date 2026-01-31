# Frontend Codemap

**Last Updated:** 2025-01-31
**Framework:** React 19.2.3 + TypeScript 5.9.3
**Build Tool:** Vite 7.3.0
**Entry Point:** src/main.tsx

## Architecture Overview

```
+-----------------------------------------------------------------------+
|                         React Application                              |
+-----------------------------------------------------------------------+
|                                                                       |
|  +---------------------------+  +-------------------------------+     |
|  |      Zustand Stores       |  |       React Router           |     |
|  |  (State Management)       |  |     (Client Routing)         |     |
|  +---------------------------+  +-------------------------------+     |
|           |                                                      |     |
|           v                                                      v     |
|  +---------------------------+  +-------------------------------+     |
|  |      Layouts              |  |       Pages                   |     |
|  |  - TenantLayout           |  |  - Login                      |     |
|  |  - ProjectLayout          |  |  - AgentWorkspace            |     |
|  |  - SchemaLayout           |  |  - Project/tenant pages      |     |
|  +---------------------------+  +-------------------------------+     |
|           |                                                      |     |
|           +-------------------+----------------------------------+     |
|                               |                                        |
|                               v                                        |
|  +-------------------------------------------------------------------+|
|  |                         Components                                 ||
|  |  +----------------+  +----------------+  +----------------------+  ||
|  |  |  agent/        |  |  layout/       |  |  common/             |  ||
|  |  |  - chat/       |  |  - AppHeader   |  |  - ErrorBoundary     |  ||
|  |  |  - execution/  |  |  - Sidebars    |  |  - SkeletonLoader    |  ||
|  |  |  - patterns/   |  +----------------+  +----------------------+  ||
|  |  |  - sandbox/    |                                                 ||
|  |  +----------------+                                                 ||
|  +-------------------------------------------------------------------+|
|                                                                       |
|  +---------------------------+  +-------------------------------+     |
|  |      Services             |  |       Utils                  |     |
|  |  - agentService (SSE)     |  |  - SSE adapters              |     |
|  |  - httpClient (REST)     |  |  - Token resolver            |     |
|  +---------------------------+  +-------------------------------+     |
+-----------------------------------------------------------------------+
```

## Directory Structure

```
src/
├── main.tsx                  # Application bootstrap
├── App.tsx                   # Route definitions (lazy-loaded)
├── index.css                 # Global styles (Tailwind)
│
├── components/               # React components
│   ├── agent/               # Agent chat & execution UI
│   │   ├── chat/           # Message rendering, streaming
│   │   ├── execution/      # Timeline, tool calls, work plans
│   │   ├── patterns/       # Workflow pattern visualization
│   │   ├── sandbox/        # Sandbox output viewer
│   │   ├── layout/         # Agent-specific layouts
│   │   └── shared/         # Shared agent utilities
│   ├── layout/             # App-wide layouts
│   ├── common/             # Shared UI (EmptyState, Skeleton)
│   ├── graph/              # Knowledge graph visualization
│   ├── project/            # Project-specific components
│   ├── tenant/             # Tenant-specific components
│   └── shared/             # Shared modals, UI widgets
│
├── pages/                   # Route pages (lazy-loaded)
│   ├── Login.tsx           # Authentication page
│   ├── tenant/             # Tenant-level pages (16 pages)
│   │   ├── AgentWorkspace.tsx       # Main agent chat UI
│   │   ├── AgentDashboard.tsx       # Agent management
│   │   ├── TaskDashboard.tsx        # Temporal tasks
│   │   ├── ProjectList.tsx          # Projects CRUD
│   │   ├── SkillList.tsx            # Skills management
│   │   ├── SubAgentList.tsx         # Sub-agents
│   │   ├── McpServerList.tsx        # MCP servers
│   │   ├── TenantOverview.tsx       # Tenant stats
│   │   ├── Analytics.tsx            # Analytics
│   │   ├── Billing.tsx              # Billing
│   │   ├── UserList.tsx             # User management
│   │   ├── ProviderList.tsx         # LLM providers
│   │   ├── WorkflowPatterns.tsx     # Workflow patterns
│   │   ├── NewProject.tsx           # Create project
│   │   ├── EditProject.tsx          # Edit project
│   │   ├── NewTenant.tsx            # Create tenant
│   │   └── TenantSettings.tsx       # Tenant settings
│   └── project/            # Project-level pages
│       ├── ProjectOverview.tsx
│       ├── MemoryList.tsx
│       ├── MemoryDetail.tsx
│       ├── NewMemory.tsx
│       ├── MemoryGraph.tsx
│       ├── EntitiesList.tsx
│       ├── CommunitiesList.tsx
│       ├── EnhancedSearch.tsx
│       ├── Maintenance.tsx
│       ├── Settings.tsx
│       ├── Support.tsx
│       ├── schema/          # Schema management pages
│       └── agent/           # Agent-specific project pages
│
├── layouts/                 # Layout wrappers
│   ├── TenantLayout.tsx    # Agent-centric tenant layout
│   ├── ProjectLayout.tsx   # Project workbench layout
│   ├── SchemaLayout.tsx    # Schema editor layout
│   └── AgentLayout.tsx     # Agent chat layout
│
├── stores/                  # Zustand state stores
│   ├── agentV3.ts          # Main agent store (conversations, messages)
│   ├── auth.ts             # Authentication state
│   ├── tenant.ts           # Tenant management
│   ├── project.ts          # Project management
│   ├── memory.ts           # Memory management
│   ├── sandbox.ts          # Sandbox state
│   ├── skill.ts            # Skill state
│   ├── subagent.ts         # Sub-agent state
│   ├── mcp.ts              # MCP server state
│   ├── notification.ts     # Notifications
│   ├── theme.ts            # Theme preferences
│   └── agent/              # Agent sub-stores (modular)
│       ├── conversationsStore.ts
│       ├── executionStore.ts
│       ├── streamingStore.ts
│       ├── planModeStore.ts
│       └── timelineStore.ts
│
├── services/                # API & business logic
│   ├── agentService.ts     # Agent chat (WebSocket/SSE)
│   ├── agentEventReplayService.ts
│   ├── agentConfigService.ts
│   ├── planService.ts      # Plan mode operations
│   ├── api.ts              # REST API client
│   ├── client/             # HTTP client infrastructure
│   │   ├── httpClient.ts   # Axios wrapper
│   │   ├── ApiError.ts     # Error handling
│   │   ├── retry.ts        # Retry logic
│   │   ├── requestCache.ts # Request caching
│   │   ├── requestDeduplicator.ts
│   │   └── urlUtils.ts     # URL helpers
│   ├── memoryService.ts
│   ├── projectService.ts
│   ├── projectSandboxService.ts
│   ├── sandboxService.ts
│   ├── sandboxSSEService.ts
│   ├── sandboxWebSocketUtils.ts
│   ├── tenantService.ts
│   ├── patternService.ts
│   ├── skillService.ts
│   ├── subagentService.ts
│   ├── mcpService.ts
│   ├── graphService.ts
│   └── sse.ts              # SSE parser
│
├── types/                   # TypeScript types
│   ├── agent.ts            # Agent, conversation, SSE events
│   ├── memory.ts           # Memory, entity, graph types
│   ├── common.ts           # Shared types
│   └── sandbox.ts          # Sandbox types
│
├── hooks/                   # Custom React hooks
│   ├── useAgentLifecycleState.ts
│   ├── useBreadcrumbs.ts
│   ├── useDebounce.ts
│   ├── useLocalStorage.ts
│   ├── useMediaQuery.ts
│   ├── useNavigation.ts
│   ├── usePagination.ts
│   ├── usePlanModeEvents.ts
│   ├── useSandboxDetection.ts
│   ├── useTaskSSE.ts       # SSE connection for tasks
│   ├── useUnifiedAgentStatus.ts
│   └── useWebSocket.ts
│
├── utils/                   # Utility functions
│   ├── agentDataAdapters.ts
│   ├── date.ts
│   ├── logger.ts
│   ├── planModeSSEAdapter.ts
│   ├── sseEventAdapter.ts
│   └── tokenResolver.ts
│
├── config/                  # Configuration
├── i18n/                    # Internationalization
├── locales/                 # Translation files
├── theme/                   # Theme configuration (Ant Design + Tailwind)
├── contexts/                # React contexts
└── test/                    # Test utilities and fixtures
```

## Key Components

### Agent Components (components/agent/)

| Component | Purpose | Location |
|-----------|---------|----------|
| ChatLayout | Main agent chat container | components/agent/ChatLayout.tsx |
| MessageArea | Message list with virtual scrolling | components/agent/MessageArea.tsx |
| MessageBubble | Single message rendering | components/agent/MessageBubble.tsx |
| InputBar | User input with file upload | components/agent/InputBar.tsx |
| ConversationSidebar | Chat history sidebar | components/agent/ConversationSidebar.tsx |
| RightPanel | Execution details, plans, sandbox | components/agent/RightPanel.tsx |
| ExecutionTimeline | Tool execution timeline | components/agent/execution/ExecutionTimeline.tsx |
| WorkPlanProgress | Work plan step progress | components/agent/execution/WorkPlanProgress.tsx |
| PlanModeViewer | Plan mode editor | components/agent/PlanModeViewer.tsx |
| SandboxSection | Sandbox output viewer | components/agent/SandboxSection.tsx |
| ThoughtBubble | Agent reasoning display | components/agent/ThoughtBubble.tsx |
| ToolExecutionCard | Tool call result display | components/agent/ToolExecutionCard.tsx |

### Layout Components (layouts/)

| Component | Purpose | Features |
|-----------|---------|----------|
| TenantLayout | Agent-centric tenant pages | Conversation sidebar, header with nav |
| ProjectLayout | Project workbench | Project sidebar, breadcrumbs |
| SchemaLayout | Schema editor | Nested routing for schema types |
| AgentLayout | Dedicated agent chat page | Full-screen chat UI |

## Key Stores (Zustand)

| Store | State | Actions |
|-------|-------|---------|
| agentV3 | conversations, messages, timeline, streaming state, work plans | sendMessage, loadConversations, createNewConversation |
| auth | user, token, isAuthenticated | login, logout, checkAuth |
| tenant | tenants, currentTenant | listTenants, setCurrentTenant |
| project | projects, currentProject | listProjects, setCurrentProject |
| memory | memories, filters | listMemories, createMemory |
| sandbox | sandbox sessions, output | createSession, connectSSE |
| theme | theme mode (light/dark) | toggleTheme |

### Agent Sub-Stores (Modular)

Located in `stores/agent/` for separation of concerns:

| Store | Purpose |
|-------|---------|
| conversationsStore | Conversation list management |
| executionStore | Tool execution tracking |
| streamingStore | SSE streaming state |
| planModeStore | Plan mode toggling |
| timelineStore | Timeline event management |

## Routing Structure

```
/                          -> Redirect to /tenant or /login
/login                     -> Login page
/tenants/new              -> Create new tenant

/tenant                    -> AgentWorkspace (default)
/tenant/:conversation      -> AgentWorkspace with specific chat
/tenant/overview           -> TenantOverview
/tenant/projects           -> ProjectList
/tenant/projects/new       -> NewProject
/tenant/users              -> UserList
/tenant/providers          -> ProviderList
/tenant/analytics          -> Analytics
/tenant/billing            -> Billing
/tenant/settings           -> TenantSettings
/tenant/tasks              -> TaskDashboard
/tenant/agents             -> AgentDashboard
/tenant/agent-workspace    -> AgentWorkspace
/tenant/subagents          -> SubAgentList
/tenant/skills             -> SkillList
/tenant/mcp-servers        -> McpServerList

/tenant/:tenantId/*        -> Same routes above with tenantId

/project/:projectId        -> ProjectOverview
/project/:projectId/memories -> MemoryList
/project/:projectId/memories/new -> NewMemory
/project/:projectId/memory/:memoryId -> MemoryDetail
/project/:projectId/graph  -> MemoryGraph
/project/:projectId/entities -> EntitiesList
/project/:projectId/communities -> CommunitiesList
/project/:projectId/advanced-search -> EnhancedSearch
/project/:projectId/maintenance -> Maintenance
/project/:projectId/schema -> SchemaLayout
/project/:projectId/settings -> ProjectSettings
```

## Data Flow

### Agent Chat Flow

```
User Input (InputBar)
    |
    v
sendMessage() -> agentV3 store
    |
    v
agentService.chat() -> WebSocket/SSE connection
    |
    +---> Server sends events:
    |       - thought_delta: Stream reasoning
    |       - act: Tool execution start
    |       - observe: Tool result
    |       - text_delta: Response text
    |       - work_plan: Multi-step plan
    |       - complete: Done
    |
    v
AgentStreamHandler updates state
    |
    v
Components re-render via Zustand selectors
```

### Authentication Flow

```
Login page
    |
    v
authAPI.login() -> POST /auth/token
    |
    v
authStore.login() stores token + user
    |
    v
Protected routes accessible
    |
    v
httpClient injects Bearer token
```

### API Client Architecture

```
httpClient (Axios wrapper)
    |
    +---> Interceptors:
    |       - Request: Add Bearer token
    |       - Response: Handle 401/403
    |       - Error: Standardize errors
    |
    +---> Features:
    |       - Retry logic
    |       - Request deduplication
    |       - Response caching
    |
    v
API Services (tenantAPI, projectAPI, etc.)
```

## SSE Event Types

Agent chat uses Server-Sent Events for streaming:

| Event | Data | Handler |
|-------|------|---------|
| thought_delta | { delta: string } | onThoughtDelta |
| thought | { thought: string } | onThought |
| act | { tool_name, tool_input } | onAct |
| observe | { observation } | onObserve |
| text_delta | { delta: string } | onTextDelta |
| text_end | { full_text } | onTextEnd |
| work_plan | { plan_id, steps, current_step } | onWorkPlan |
| step_start | { current_step } | onStepStart |
| complete | { content, trace_url } | onComplete |
| decision_asked | { request_id, options } | onDecisionAsked |
| doom_loop_detected | { loop_count, intervention } | onDoomLoopDetected |

## External Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| react | 19.2.3 | UI framework |
| react-dom | 19.2.3 | DOM rendering |
| react-router-dom | 7.11.0 | Client routing |
| zustand | 5.0.9 | State management |
| antd | 6.1.1 | UI component library |
| axios | 1.13.2 | HTTP client |
| cytoscape | 3.33.1 | Graph visualization |
| i18next | 25.7.3 | Internationalization |
| react-markdown | 10.1.0 | Markdown rendering |
| @xterm/xterm | 6.0.0 | Terminal emulator (sandbox) |

## Build Configuration

- **Vite 7.3.0** - Build tool and dev server
- **TypeScript 5.9.3** - Strict mode enabled
- **Tailwind CSS 4.1.18** - Utility-first styling
- **Ant Design 6.1.1** - Component library with custom theme
- **Vitest 4.0.16** - Unit testing
- **Playwright 1.57.0** - E2E testing

## Important Files

| File | Purpose |
|------|---------|
| src/main.tsx | Application bootstrap |
| src/App.tsx | Route definitions (600+ lines) |
| src/stores/agentV3.ts | Main agent state (1200+ lines) |
| src/services/agentService.ts | Agent API client |
| src/types/agent.ts | Agent type definitions |
| src/utils/sseEventAdapter.ts | SSE event to timeline adapter |
| src/components/agent/index.ts | Agent components barrel export |
| src/components/index.ts | Root components barrel export |

## Related Areas

- Backend API: `src/infrastructure/adapters/primary/web/` (Python FastAPI)
- Agent System: `src/infrastructure/agent/` (Python ReAct Agent)
- Sandbox: `src/infrastructure/sandbox/` (Python Docker sandbox)

## Development Notes

### State Management Pattern
- Zustand for global state (stores/)
- Local state with useState for component-specific UI
- URL params for routing state (conversationId, projectId, tenantId)

### Code Splitting
- All route components are lazy-loaded with React.lazy()
- Suspense fallback shows spinner during load

### SSE Streaming
- Primary transport for agent chat (real-time)
- Fallback to REST for list/fetch operations
- Event replay support for reconnecting to running conversations

### Testing
- Unit tests: Vitest + @testing-library/react
- E2E tests: Playwright
- Test utilities in src/test/utils.tsx
- Fixtures in src/test/fixtures/
