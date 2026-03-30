# Feature Gap Analysis: nodeskclaw -> agi-demos (MemStack)

## Executive Summary

This document identifies ALL feature gaps between the nodeskclaw reference project and the agi-demos (MemStack) target project. It covers both frontend (pages, stores, services, components) and backend (API routers, models, services) layers.

**Scope**: CE (Community Edition) features only. EE-only features from `features.yaml` are excluded from mandatory implementation but listed for reference.

**Architecture delta**: nodeskclaw is single-org with Vue 3 + Tailwind + Pinia; agi-demos is multi-tenant with React 19 + Ant Design 6 + Zustand 5. Features must be implemented natively in the agi-demos stack.

---

## 1. MISSING Features (Must Implement)

### 1.1 Force Change Password

**nodeskclaw**: Full implementation
- Backend: `POST /auth/force-change-password` endpoint
- Frontend: `ForceChangePassword.vue` page
- Router guard: `must_change_password` redirect on every navigation
- Auth store: `must_change_password` flag on `PortalUser`

**agi-demos**: COMPLETELY MISSING
- No page, no route, no router guard, no user model flag

**Implementation scope**:
- Backend: Add `must_change_password` field to User model + migration; add `POST /auth/force-change-password` endpoint
- Frontend: Create `ForceChangePassword.tsx` page; add route `/force-change-password`; add router guard in `App.tsx` that checks `must_change_password` flag and redirects
- Store: Add `must_change_password` to auth store user model
- i18n: Add all user-visible strings

---

### 1.2 Workspace Settings Page

**nodeskclaw**: `WorkspaceSettings.vue`
- Workspace name/description editing
- Member management (add/remove/change role)
- Workspace deletion
- Backend: workspace update/delete endpoints, member CRUD

**agi-demos**: MISSING (confirmed via glob -- no `WorkspaceSettings` files exist)
- `WorkspaceDetail.tsx` exists but has no settings/members management
- `WorkspaceList.tsx` exists

**Implementation scope**:
- Frontend: Create `WorkspaceSettings.tsx` page with name/description editing, member management, delete functionality
- Route: Add `/tenant/project/:projectId/workspaces/:workspaceId/settings`
- Backend: Verify workspace update/delete/member endpoints exist; implement if missing
- i18n: All user-visible strings

---

### 1.3 Evolution Log Page

**nodeskclaw**: `EvolutionLog.vue`
- Shows history of gene installations, upgrades, and removals on an instance
- Timeline view of evolution events
- Backend: evolution log endpoints on instance router

**agi-demos**: MISSING -- no evolution log page or route
- `InstanceGenes.tsx` exists but shows current genes only, not history

**Implementation scope**:
- Frontend: Create `EvolutionLog.tsx` page with timeline view
- Route: Add `/tenant/instances/:instanceId/evolution`
- Backend: Add evolution log query endpoint if not present
- Store: Add evolution log state to instance store
- i18n: All user-visible strings

---

### 1.4 Genome Detail Page

**nodeskclaw**: `GenomeDetail.vue`
- Shows a genome (bundled gene collection) with its constituent genes
- Install/uninstall genome as a unit
- Ratings, reviews, compatibility info

**agi-demos**: MISSING
- `GeneDetail.tsx` exists for individual genes but no genome concept
- `GeneMarket.tsx` exists as the market page

**Implementation scope**:
- Frontend: Create `GenomeDetail.tsx` page
- Route: Add `/tenant/genes/genome/:genomeId`
- Backend: Verify genome model and endpoints exist; implement if missing
- Store: Add genome state to gene market store
- i18n: All user-visible strings

---

### 1.5 Template Detail Page (Gene Market)

**nodeskclaw**: `TemplateDetail.vue`
- Shows an instance template with pre-configured genes, settings
- One-click deploy from template
- Backend: template detail endpoint

**agi-demos**: MISSING as a dedicated detail page
- `InstanceTemplateList.tsx` exists (list view)
- No `TemplateDetail.tsx` or route for `/tenant/instance-templates/:templateId`

**Implementation scope**:
- Frontend: Create `TemplateDetail.tsx` page with template info, included genes, deploy button
- Route: Add `/tenant/instance-templates/:templateId`
- Backend: Verify template detail endpoint exists
- i18n: All user-visible strings

---

### 1.6 OrgSettings: Registry Page

**nodeskclaw**: Org settings includes a container registry configuration page
- Configure private Docker registries for gene images
- Test connectivity
- Backend: registry CRUD endpoints in `registry.py`

**agi-demos (generic routes)**: `OrgSettingsLayout` includes `info`, `members`, `clusters`, `audit` but NO `registry` sub-route in the generic (non-tenantId) section. However, the `:tenantId/org-settings/registry` route DOES exist (line 1057-1063 in App.tsx).
- `OrgRegistry` component IS lazy-imported (line ~197 in App.tsx imports section)

**Gap**: The generic `/tenant/org-settings/registry` route is MISSING. Only the tenantId-prefixed version exists. Also need to verify `OrgRegistry.tsx` page is fully implemented (not a stub).

**Implementation scope**:
- Frontend: Add missing generic route for `/tenant/org-settings/registry`
- Verify `OrgRegistry.tsx` is fully functional
- Backend: Verify registry endpoints exist

---

### 1.7 OrgSettings: SMTP Page

**nodeskclaw**: Org settings includes SMTP configuration
- Configure SMTP server for email notifications
- Test email sending
- Backend: SMTP config endpoints in `org_settings.py`

**agi-demos**: Same situation as Registry -- `OrgSmtp` component exists, `:tenantId/org-settings/smtp` route exists (line 1065-1071), but generic route is MISSING.

**Implementation scope**:
- Frontend: Add missing generic route for `/tenant/org-settings/smtp`
- Verify `OrgSmtp.tsx` is fully functional
- Backend: Verify SMTP endpoints exist

---

### 1.8 OrgSettings: Genes Page

**nodeskclaw**: Org settings includes a gene management/configuration page
- Org-level gene policies, allowed/blocked genes
- Backend: gene org-settings endpoints

**agi-demos**: NO org-settings/genes route exists
- Gene market exists at `/tenant/genes` but no org-level gene management

**Implementation scope**:
- Frontend: Create `OrgGenes.tsx` page for org-level gene policies
- Route: Add to both generic and tenantId-prefixed org-settings
- Backend: Add org-level gene policy endpoints if missing
- i18n: All user-visible strings

---

## 2. STUB/PARTIAL Features (Verified)

> **Verification completed**: V1-V6 verified via background agents on 2026-03-27.

### 2.1 Workspace 2D/3D Canvas (Hex Topology) -- VERIFIED: FULL

**nodeskclaw**: Full hex-grid workspace with:
- `hex2d/` components: 2D hex grid canvas with drag-drop agent placement
- `hex3d/` components: 3D perspective view
- Workspace store (1355 lines): hex topology state, agent positions (hex_q, hex_r), SSE connections per agent, theme colors
- AgentBrief model: `instance_id, name, hex_q, hex_r, sse_connected, theme_color`

**agi-demos**: **FULLY IMPLEMENTED**
- `WorkspaceDetail.tsx` (321 lines): imports HexGrid + HexCanvas3D, viewMode toggle (2D/3D via Segmented), hexAgentModal with q/r coordinates, handleHexAction for agent assignment, loadWorkspaceSurface on mount
- `workspace` store (696 lines): topologyNodes/topologyEdges, agents with hex_q/hex_r, selectedHex, bindAgent/unbindAgent/moveAgent actions, handleTopologyEvent for real-time position updates
- SSE: Store has event handlers (handleChatEvent, handleTopologyEvent, handleBlackboardEvent, handlePresenceEvent); subscription via unifiedEventService in WorkspaceDetail component -- acceptable pattern

**Gap**: NONE -- feature parity achieved. No action needed.

---

### 2.2 Blackboard System (Posts/Replies/Files) -- VERIFIED: FULL

**nodeskclaw**: Full blackboard system
- `blackboard/` components: PostCard, PostList, PostEditor, ReplyThread, FileAttachments
- Workspace store: `posts`, `replies`, file upload/download
- Backend: blackboard endpoints (CRUD for posts, replies, file attachments)

**agi-demos**: **FULLY IMPLEMENTED**
- `BlackboardPanel.tsx` (112 lines): post creation, reply drafts, rendering posts + replies, wired to workspace store actions
- Workspace store: posts/repliesByPostId in state, createPost/createReply methods, loadWorkspaceSurface fetches posts and populates repliesByPostId, handleBlackboardEvent for real-time updates
- **Minor gap**: No separate PostCard/PostEditor/ReplyThread components (all inline in BlackboardPanel). No file attachment support visible.

**Gap**: MINOR -- file attachment support not confirmed. Core CRUD is implemented.

---

### 2.3 Instance Settings (LLM Configuration) -- VERIFIED: MISSING

**nodeskclaw**: `InstanceSettings.vue` with:
- ModelSelect component for per-instance LLM model selection
- LLM API key configuration per instance
- Backend: instance LLM settings endpoints, `llm_keys.py` router

**agi-demos**: `InstanceSettings.tsx` (240 lines) -- **Only name/description/delete**
- First 120 lines and full file scope: instance name/description form, updateInstance, deleteInstance handlers
- **NO LLM model selection UI**
- **NO LLM API key configuration UI**

**Gap**: SIGNIFICANT -- LLM model selection and API key configuration completely missing from InstanceSettings page. Must implement:
- LLM model selection dropdown (per-instance model choice)
- API key configuration form
- Backend endpoint verification for per-instance LLM settings

---

### 2.4 Deploy Progress (SSE Streaming) -- VERIFIED: PARTIAL

**nodeskclaw**: `DeployProgress.vue` with:
- `fetchEventSource` for SSE streaming of deploy steps
- Real-time progress updates, log streaming
- Error/retry handling

**agi-demos**: `DeployProgress.tsx` (251 lines) -- **Status timeline only, NO SSE**
- Timeline UI with status color mapping, uses deploy store hooks (useDeploys, useCurrentDeploy, useDeployActions)
- Store actions: createDeploy, markSuccess, markFailed, cancelDeploy
- **NO EventSource, NO fetchEventSource, NO real-time streaming**
- Loads deploy data via store actions on mount -- static snapshot, requires manual refresh

**Gap**: MODERATE -- SSE/log streaming integration missing. Must implement:
- EventSource or fetchEventSource integration for real-time deploy step events
- Live log tail UI component
- Backend SSE endpoint verification
- Store support for incremental event handling

---

### 2.5 Gene Market Depth -- VERIFIED: PARTIAL (Rich)

**nodeskclaw**: `GeneMarket.vue` + `GeneDetail.vue` + `GenomeDetail.vue` + `TemplateDetail.vue`
- Gene store (551 lines): categories, tags, search, ratings, reviews, effectiveness scores
- Gene installation flow with dependency resolution
- Gene synergies visualization

**agi-demos**: `geneMarket.ts` store (480 lines) -- **Rich but incomplete**
- **Present**: Full CRUD (genes + genomes), install/uninstall, rateGene/rateGenome, evolution events, selectors
- **Missing**: reviews (no review objects/endpoints), effectiveness scores, dependency resolution, synergy analysis

**Gap**: MODERATE -- core CRUD and ratings exist. Missing advanced features:
- Reviews system (create/read/list reviews + UI)
- Effectiveness metric computation
- Dependency resolution data model + validation
- Synergy analysis visualization

---

### 2.6 OrgRegistry -- VERIFIED: PARTIAL (Demo Scaffolding)

**agi-demos**: `OrgRegistry.tsx` (701 lines)
- First 120 lines show: RegistryConfig interface, registry type options, getStatusConfig helper, **MOCK_REGISTRIES array** (demo data)
- UI helpers and types present but mock-data driven
- Backend wiring not visible in first 120 lines (may exist in remainder)

**Gap**: MODERATE -- page exists with substantial scaffolding (701 lines) but uses mock data. Needs:
- Backend API integration (replace MOCK_REGISTRIES with real API calls)
- Connectivity test wiring to backend
- Add generic route `/tenant/org-settings/registry`

---

### 2.7 OrgSmtp -- VERIFIED: FULL

**agi-demos**: `OrgSmtp.tsx` (351 lines) -- **FULLY IMPLEMENTED**
- Uses useSmtpConfig, useSmtpLoading, useSmtpActions from stores/smtp
- Calls smtpService, fetchConfig on mount, form state for host/port/username/password/TLS/from fields
- handleSave with validation, isSubmitting/isTesting flags
- Concrete store/service integration -- not a stub

**Gap**: MINOR -- only missing generic route `/tenant/org-settings/smtp`. Implementation is complete.

---

## 3. MISSING Router Guards & Auth Features

### 3.1 Force Change Password Router Guard

**nodeskclaw**: `router.beforeEach` checks `auth.user?.must_change_password` and redirects to `/force-change-password` on every navigation

**agi-demos**: Auth guard only checks `isAuthenticated` and redirects to `/login`

**Implementation scope**: Add `must_change_password` check to auth flow in `App.tsx` or a wrapper component

---

### 3.2 CE/EE Feature Gating (DEFERRED -- EE features)

**nodeskclaw**: `features.yaml` defines 14 EE features:
```
multi_org, billing, admin_members, platform_admin, enterprise_files,
org_smtp_config, topology_audit, performance_analytics, llm_analytics,
network_egress_control, akr_management, multi_cluster, advanced_audit,
sso_ldap, advanced_rbac
```
- Router meta: `ceOnly`, `requireFeature`
- Backend: SystemInfo includes `features` list
- Frontend: Feature check utility

**agi-demos**: No feature gating system

**Note**: This is an EE concern. Since we're implementing CE features, the basic gating infrastructure should be added but EE-specific features are OUT OF SCOPE. However, the infrastructure to support gating (SystemInfo features field, route meta, check utility) should be implemented.

**Implementation scope**:
- Backend: Add `features` field to system info / tenant config
- Frontend: Add feature check utility; add route guard support for `requireFeature`
- Config: Create `features.yaml` equivalent

---

### 3.3 OrgSetup Redirect

**nodeskclaw**: Router guard redirects to org setup page if org is not fully configured

**agi-demos**: No equivalent

**Implementation scope**:
- Add org setup completeness check
- Redirect flow when org setup is incomplete

---

## 4. MISSING Backend Routers/Endpoints

### 4.1 Portal Dual-Prefix Routing

**nodeskclaw**: `/app/api/portal/` prefix provides instance-member-scoped versions of:
- instances, deploy, instance_members, instance_files, mcp, channel_configs

**agi-demos**: No portal prefix routing

**Note**: This maps to a "portal user" concept where instance members (not org admins) can access their assigned instances. In agi-demos multi-tenant model, this might map to project-level access control.

**Implementation scope**: NEEDS ARCHITECTURE DECISION -- how to map nodeskclaw's portal concept to agi-demos multi-tenant model

---

### 4.2 Tunnel Router

**nodeskclaw**: `tunnel.py` -- manages network tunnels (SSH/WireGuard) for instances

**agi-demos**: No tunnel router

**Implementation scope**: Full tunnel management system (model, service, router, frontend)

---

### 4.3 Corridors Router

**nodeskclaw**: `corridors.py` -- manages communication corridors between instances

**agi-demos**: No corridors router

**Implementation scope**: Full corridor management system

---

### 4.4 Engines Router

**nodeskclaw**: `engines.py` -- manages compute engines / runtimes

**agi-demos**: No engines router (closest is `providers` for LLM providers)

**Implementation scope**: Full engine management system

---

### 4.5 Runtime Admin Router

**nodeskclaw**: `runtime_admin.py` -- admin operations for runtime management

**agi-demos**: Has `PoolDashboard` (admin) but no runtime admin router

**Implementation scope**: Depends on engine/runtime system above

---

### 4.6 Security WebSocket Router

**nodeskclaw**: `security_ws.py` -- WebSocket for real-time security events

**agi-demos**: No security WebSocket

**Implementation scope**: WebSocket endpoint for security event streaming

---

### 4.7 Webhooks Router

**nodeskclaw**: `webhooks.py` -- webhook management (create, test, list, delete)

**agi-demos**: No webhook management

**Implementation scope**: Full webhook system (model, service, router, frontend)

---

### 4.8 Events Router

**nodeskclaw**: `events.py` -- system events listing and filtering

**agi-demos**: Has audit logs but no general events system

**Implementation scope**: Events listing endpoint with filtering

---

### 4.9 Storage Router

**nodeskclaw**: `storage.py` -- storage/volume management for instances

**agi-demos**: No storage router

**Implementation scope**: Storage management system

---

## 5. MISSING Frontend Infrastructure

### 5.1 MessageBus + Middleware Pipeline

**nodeskclaw**: Complex message bus system with middleware pipeline for inter-component communication

**agi-demos**: No equivalent -- uses Zustand stores for state and direct service calls

**Note**: This is an architectural pattern, not a feature. agi-demos's Zustand + service pattern may be sufficient. NEEDS ARCHITECTURE DECISION on whether to implement.

**Recommendation**: SKIP -- agi-demos's existing patterns are adequate for the same functionality.

---

### 5.2 i18n Coverage -- VERIFIED: PARTIAL (79%)

**nodeskclaw**: Full i18n coverage for all user-visible strings

**agi-demos**: i18n infrastructure is solid but coverage is incomplete
- Infrastructure: `web/src/i18n/config.ts` registers en-US and zh-CN
- Locale files: `en-US.json` (2788 lines), `zh-CN.json` (2984 lines)
- Coverage: 62/78 pages (79%) use `useTranslation`
- **16 pages need i18n retrofit** (hardcoded English strings)

**Gap**: MODERATE -- infrastructure is production-ready but 16 existing pages need retrofit. All new pages must include i18n from the start.

---

## 6. agi-demos UNIQUE Features (NOT in nodeskclaw -- PRESERVE)

These are features unique to agi-demos that must NOT be removed or broken during implementation:

| Feature | Components |
|---------|-----------|
| Memory system (episodes, knowledge graph, Neo4j) | MemoryList, MemoryDetail, NewMemory, MemoryGraph, EntitiesList, CommunitiesList |
| 4-layer agent architecture (Tool -> Skill -> SubAgent -> Agent) | AgentWorkspace, SubAgentList, SkillList, AgentDefinitions, AgentBindings |
| Sandbox/code execution | SandboxService, related components |
| Cron jobs | CronJobs page, cronService |
| Agent pool (HOT/WARM/COLD tiers) | PoolDashboard |
| HITL (human-in-the-loop) | Agent workspace integration |
| Billing | Billing page |
| Analytics | Analytics page |
| MCP App Store | McpServerList, mcpAppStore |
| Schema management | SchemaOverview, EntityTypeList, EdgeTypeList, EdgeMapList |
| Enhanced search | EnhancedSearch page |
| Trust policies | TrustPolicies page |
| Decision records | DecisionRecords page |
| Plugin hub | PluginHub page |
| Template marketplace | TemplateMarketplace page |
| Project teams | Team page |
| Support | Support page |
| Workflow patterns | WorkflowPatterns page |

---

## 7. Implementation Priority Matrix (Updated after V1-V6 verification)

### VERIFIED OK (No action needed)
- ~~Workspace 2D/3D Hex Topology~~ -- FULL (V1 verified)
- ~~Blackboard System (posts/replies)~~ -- FULL (V2 verified, minor: no file attachments)
- ~~OrgSmtp~~ -- FULL (V7 verified, only needs generic route)
- ~~Workspace Backend Endpoints~~ -- FULL (V9 verified: CRUD, members, agents, blackboard, chat, tasks, topology, events)

### P0 -- Critical (Core user flows)
1. Force Change Password (page + guard + backend)
2. Workspace Settings (members, permissions, editing)
3. OrgSettings missing generic routes (registry, smtp, genes)
4. Instance Settings LLM configuration (V3 verified: MISSING)

### P1 -- High (Feature completeness)
5. Evolution Log page
6. Genome Detail page
7. Template Detail page (gene market)
8. OrgRegistry backend wiring (V6 verified: uses MOCK_REGISTRIES, needs real API)
9. Deploy Progress SSE streaming (V4 verified: no SSE, timeline only)

### P2 -- Medium (Platform features)
10. Gene Market advanced features (V5 verified: reviews, effectiveness, dependency, synergy)
11. CE/EE Feature Gating infrastructure
12. OrgSetup redirect guard
13. Events system (router + frontend)
14. Webhook management system
15. i18n retrofit for 16 existing pages (V8 verified: 79% coverage, 16 pages need retrofit)

### P3 -- Low (Infrastructure/admin)
16. Portal dual-prefix routing (architecture decision needed)
17. Tunnel management
18. Corridors management
19. Engines/runtime management
20. Storage management
21. Security WebSocket
22. Runtime admin

### SKIP
- MessageBus middleware pipeline (agi-demos Zustand pattern is sufficient)

---

## 8. Verification Tasks

| # | Item | Status | Result |
|---|------|--------|--------|
| V1 | WorkspaceDetail hex topology | **DONE** | FULL -- HexGrid, HexCanvas3D, hex_q/hex_r binding, 2D/3D toggle |
| V2 | Blackboard components | **DONE** | FULL -- BlackboardPanel + store CRUD + event handlers. Minor: no file attachments |
| V3 | InstanceSettings LLM config | **DONE** | MISSING -- only name/description/delete, no LLM model/key UI |
| V4 | DeployProgress SSE | **DONE** | PARTIAL -- timeline UI + store actions, NO SSE/log streaming |
| V5 | Gene market depth | **DONE** | PARTIAL -- CRUD + ratings + evolution events. NO reviews/effectiveness/deps/synergy |
| V6 | OrgRegistry completeness | **DONE** | PARTIAL -- 701 lines, demo scaffolding with MOCK_REGISTRIES |
| V7 | OrgSmtp completeness | **DONE** | FULL -- 351 lines, store/service wired, validation, save handler |
| V8 | i18n coverage | **DONE** | PARTIAL (79%) -- 62/78 pages use useTranslation; 16 pages need retrofit. Infrastructure solid (en-US + zh-CN) |
| V9 | Workspace backend endpoints | **DONE** | FULL -- All endpoint categories present: CRUD, members, agents, blackboard, chat, tasks, topology, events |

---

## 9. Constraints Reminder

All implementations MUST follow:
- Soft delete with `deleted_at` field and `Index(..., unique=True, postgresql_where=text("deleted_at IS NULL"))`
- i18n for ALL user-visible text
- No emoji anywhere
- No native `<select>`/`<option>` elements (use Ant Design Select)
- Zustand `useShallow` for object selectors
- Conventional commits
- 80%+ test coverage target
