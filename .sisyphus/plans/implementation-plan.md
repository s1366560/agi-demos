# Implementation Plan: nodeskclaw Feature Parity for agi-demos

**Status**: CORRECTED v6 -- M1-M5 resolved + B1-B3 fixed + B4 (deploy SSE router prefix) fixed + B5 (gene install API paths) fixed + F1 (uninstallGene DELETE method + instance_gene_id param) fixed + F2 (evolution events query-param path preserved) fixed + F3 (get_password_hash function name) fixed + F4 (SSE token-as-query-param for EventSource) fixed
**Created**: 2026-03-27
**Depends on**: `.sisyphus/plans/feature-gap-analysis.md`

---

## Architecture Decisions (Resolved)

### AD-1: Portal Dual-Prefix Routing -- DEFERRED

**Decision**: DEFER to P3. nodeskclaw's portal prefix (`/app/api/portal/`) provides instance-member-scoped access. In agi-demos, this maps to project-level RBAC, which already exists via tenant/project scoping. Implementing a separate portal prefix is unnecessary until explicit instance-member personas are needed.

**Rationale**: agi-demos already scopes all API calls by tenant_id + project_id. Adding a /portal prefix would duplicate existing access patterns without clear user benefit. Revisit only if user research identifies a need for a distinct "instance member" persona separate from project members.

### AD-2: Instance LLM Config Approach

**Decision**: Use agi-demos's existing LLM provider system (llm_providers router + provider_service) as the backend. Add per-instance provider override endpoints to `instances.py` router. Do NOT port nodeskclaw's NFS/remote_fs openclaw.json approach.

**Rationale**: agi-demos uses a centralized LLM provider manager (LiteLLM) with DB-backed config. Writing openclaw.json to NFS does not fit this architecture. Instead, add instance-scoped provider selection (which provider + model to use) stored in the instance's DB record.

### AD-3: MessageBus Middleware Pipeline -- SKIP

**Decision**: SKIP. agi-demos's Zustand + service call pattern provides equivalent functionality.

---

## Task Execution Groups

Tasks are grouped by dependency. Groups can be executed in parallel; tasks within a group should be sequential unless noted.

---

## Group A: Force Change Password (P0) -- Deps: None

### Task A1: Backend -- Add must_change_password to User model + migration

**Starting files**:
- Domain model: `src/domain/model/auth/user.py` (add field to User dataclass, line ~8)
- DB model: `src/infrastructure/adapters/secondary/persistence/models.py` (add column to User class, line ~47)
- Repository: `src/infrastructure/adapters/secondary/persistence/sql_user_repository.py` (update _to_domain/_to_db)

**Changes**:
1. Add `must_change_password: bool = False` to `User` dataclass in `user.py`
2. Add `must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')` to User ORM in `models.py`
3. Update `_to_domain()` and `_to_db()` in `sql_user_repository.py` to include the new field
4. Generate Alembic migration: `PYTHONPATH=. uv run alembic revision --autogenerate -m "add must_change_password to users"`
5. Apply migration: `PYTHONPATH=. uv run alembic upgrade head`

**Constraints**:
- Use soft-delete pattern if adding any delete logic
- Boolean default must be False (existing users should not be forced to change password)

**QA Scenario**:
- Tool: `uv run pytest src/tests/ -m "unit" -v -k "user"` -- verify user model tests still pass
- Tool: `PYTHONPATH=. uv run alembic current` -- verify migration applied
- Manual: Connect to DB, run `SELECT column_name, data_type FROM information_schema.columns WHERE table_name='users' AND column_name='must_change_password';` -- expect one row with `boolean` type

---

### Task A2: Backend -- Add force-change-password endpoint

**Starting files**:
- Auth router: `src/infrastructure/adapters/primary/web/routers/auth.py`
- Auth service: `src/application/services/auth_service_v2.py`
- Auth deps: `src/infrastructure/adapters/primary/web/dependencies/auth_dependencies.py`
- Token schema: `src/application/schemas/auth.py` (currently only has access_token + token_type -- needs must_change_password field)

**Changes**:
1. Add `POST /auth/force-change-password` endpoint in `auth.py`:
   - Request body: `{ "old_password": str | None, "new_password": str }` (old_password nullable for admin-forced resets)
   - Validates: new_password minimum length (8 chars); old_password required unless must_change_password is True
   - Calls `auth_service.change_password(user_id, old_password, new_password)`
   - On success: sets `must_change_password = False` on user, returns `{ "message": "Password changed successfully" }`
2. Add `change_password()` method to auth_service_v2.py:
   - Verify old password (if provided) using `verify_password()`
    - Hash new password using `get_password_hash()` (NOT `hash_password()` -- the actual function name in `auth_service_v2.py` is `get_password_hash()`)
   - Update user record (hashed_password + must_change_password=False)
   - Save via user repository
3. Modify `/auth/token` endpoint to include `must_change_password` in token response when True
4. Add Pydantic request/response schemas for the force-change-password endpoint
5. Modify `Token` schema in `src/application/schemas/auth.py` (currently only has `{access_token, token_type}`) to add `must_change_password: bool = False` field

**Reference**: nodeskclaw `PUT /auth/me/password` in `app/api/auth.py`, `auth_service.change_password()`

**QA Scenario**:
- Tool: `curl -X POST http://localhost:8000/api/v1/auth/force-change-password -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"old_password": "adminpassword", "new_password": "newpassword123"}'` -- expect 200 with success message
- Tool: `curl -X POST http://localhost:8000/api/v1/auth/token -d "username=admin@memstack.ai&password=newpassword123"` -- expect 200 with token (verify new password works)
- Manual: Set must_change_password=True in DB for test user, call `/auth/token` -- verify response includes `must_change_password: true` flag

---

### Task A3: Frontend -- ForceChangePassword page + route guard

**Starting files**:
- App routes: `web/src/App.tsx` (add route, add guard logic)
- Auth store: `web/src/stores/auth.ts` (add must_change_password to user state)
- Auth API: `web/src/services/api.ts` (add changePassword method to authAPI)
- User type: `web/src/types/memory.ts` (add must_change_password to User interface)
- Create NEW: `web/src/pages/ForceChangePassword.tsx`

**Changes**:
1. Add `must_change_password?: boolean` to `User` interface in `types/memory.ts`
2. Add `changePassword(oldPassword: string | null, newPassword: string): Promise<void>` to `authAPI` in `services/api.ts`
3. Update auth store login flow to capture `must_change_password` from token response
4. Create `ForceChangePassword.tsx`:
   - Ant Design Form with password + confirm password fields
   - Call `authAPI.changePassword()` on submit
   - On success: update auth store user (must_change_password=false), redirect to `/tenant`
   - Use `useTranslation()` for all strings
5. Add route in `App.tsx`: `/force-change-password` -> `ForceChangePassword`
6. Add router guard: wrap authenticated routes with a check -- if `user.must_change_password === true`, redirect to `/force-change-password`

**Constraints**:
- Use Ant Design components only (no native `<select>`, `<input type="password">` raw elements)
- Zustand `useShallow` for object selectors
- All strings through i18n

**QA Scenario**:
- Manual: Navigate to `http://localhost:3000/force-change-password` -- expect password change form
- Manual: Set must_change_password=True for test user in DB, login -- expect redirect to `/force-change-password` instead of `/tenant`
- Manual: Submit new password on force-change page -- expect redirect to `/tenant`; verify login works with new password
- Manual: Navigate to any `/tenant/*` route while must_change_password=True -- expect redirect to `/force-change-password`

---

## Group B: Instance Settings LLM Config (P0) -- Deps: None

### Task B1: Backend -- Add instance LLM config endpoints

**Starting files**:
- Instance router: `src/infrastructure/adapters/primary/web/routers/instances.py`
- LLM providers router: `src/infrastructure/adapters/primary/web/routers/llm_providers.py`
- Provider service: `src/application/services/provider_service.py`
- LLM provider manager: `src/application/services/llm_provider_manager.py`

**Changes**:
1. Add endpoints to `instances.py`:
   - `GET /instances/{instance_id}/llm-config` -- returns current LLM provider + model selection for the instance
   - `PUT /instances/{instance_id}/llm-config` -- updates instance LLM provider/model selection
   - Request body: `{ "provider_id": str, "model_name": str, "api_key_override": str | None }`
   - Response: `{ "instance_id": str, "provider_id": str, "model_name": str, "has_api_key_override": bool }`
2. Store LLM config using the existing `Instance.llm_providers` (dict[str, Any] JSON) field -- domain model at `src/domain/model/instance/instance.py` and ORM at `models.py` already have this column. No new column or migration needed.
3. Add service method in `provider_service.py` to validate provider/model selection
4. If API key override provided, encrypt using existing encryption service before storage

**Reference**: nodeskclaw `GET/PUT /instances/{instance_id}/llm-configs` in `app/api/llm_keys.py`

**QA Scenario**:
- Tool: `curl -X PUT http://localhost:8000/api/v1/instances/<id>/llm-config -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"provider_id": "<provider_id>", "model_name": "gemini-pro"}'` -- expect 200
- Tool: `curl http://localhost:8000/api/v1/instances/<id>/llm-config -H "Authorization: Bearer <token>"` -- expect JSON with configured provider/model
- Tool: `uv run pytest src/tests/ -v -k "instance"` -- verify instance tests pass

---

### Task B2: Frontend -- Instance Settings LLM configuration UI

**Starting files**:
- Page: `web/src/pages/tenant/InstanceSettings.tsx` (240 lines -- currently only name/desc/delete)
- Instance service: `web/src/services/instanceService.ts`
- Instance store: `web/src/stores/instance.ts`

**Changes**:
1. Add LLM config section to `InstanceSettings.tsx`:
   - Ant Design Select for provider (populated from provider list)
   - Ant Design Select for model (populated from selected provider's models)
   - Optional: API key override input (Input.Password with masked display)
   - Save button that calls instanceService.updateLlmConfig()
   - Load current config on mount
2. Add methods to `instanceService.ts`:
   - `getLlmConfig(instanceId: string): Promise<InstanceLlmConfig>`
   - `updateLlmConfig(instanceId: string, config: InstanceLlmConfigUpdate): Promise<InstanceLlmConfig>`
3. Add LLM config state and actions to `instance.ts` store
4. All strings via i18n

**Reference**: nodeskclaw `InstanceSettings.vue` with ModelSelect component

**QA Scenario**:
- Manual: Navigate to `/tenant/instances/<id>/settings` -- expect LLM configuration section below name/description
- Manual: Select a provider from dropdown -- expect model dropdown to populate with that provider's models
- Manual: Select model, click Save -- expect success message; refresh page, verify selection persisted
- Manual: Enter API key override, save -- expect `has_api_key_override: true` in response

---

## Group C: Workspace Settings (P0) -- Deps: None

### Task C1: Frontend -- Create WorkspaceSettings page

**Starting files**:
- Create NEW: `web/src/pages/tenant/WorkspaceSettings.tsx`
- App routes: `web/src/App.tsx` (add route)
- Workspace store: `web/src/stores/workspace.ts` (696 lines -- has members, agents)
- Workspace service: `web/src/services/workspaceService.ts` (has update(), remove(), listMembers(), listAgents() -- lacks addMember/removeMember/updateMemberRole helpers)
- Existing page: `web/src/pages/tenant/WorkspaceDetail.tsx` (reference for patterns)

**Changes**:
1. Create `WorkspaceSettings.tsx` with:
   - Workspace name/description editing form (Ant Design Form + Input/TextArea)
   - Member management section: list members with role badges, add member (search + select), remove member, change role
   - Danger zone: Delete workspace (Ant Design Popconfirm)
2. Add route: `/tenant/project/:projectId/workspaces/:workspaceId/settings` in `App.tsx`
3. Wire to workspaceService methods (update(), remove(), listMembers()). NOTE: addMember(), removeMember(), updateMemberRole() helpers do NOT exist in workspaceService.ts and MUST be created. Backend member endpoints exist at workspaces.py (GET/POST/PATCH/DELETE /{workspace_id}/members).
4. Navigate back to workspace list after delete
5. All strings via i18n

**Backend**: Workspace backend is FULL (V9 verified) -- endpoints for CRUD, members, agents already exist at:
- `src/infrastructure/adapters/primary/web/routers/workspaces.py`

**QA Scenario**:
- Manual: Navigate to `/tenant/project/<pid>/workspaces/<wid>/settings` -- expect settings form loaded with current workspace data
- Manual: Edit workspace name, save -- expect success message; go back to workspace list, verify name updated
- Manual: Add a member -- expect member appears in member list
- Manual: Remove a member -- expect member removed from list
- Manual: Delete workspace -- expect redirect to workspace list; workspace no longer in list

---

## Group D: OrgSettings Route Gaps (P0) -- Deps: None

### Task D1: Frontend -- Add missing generic OrgSettings routes

**Starting files**:
- App routes: `web/src/App.tsx` (lines ~635 for generic org-settings -- currently has info/members/clusters/audit but MISSING registry/smtp; the `:tenantId` org-settings group already has registry/smtp but NOT genes)
- OrgSettings layout: `web/src/pages/tenant/org-settings/OrgSettingsLayout.tsx`

**Changes**:
1. In `App.tsx` generic org-settings section (~line 635), add:
   - `<Route path="registry" element={<OrgRegistry />} />`
   - `<Route path="smtp" element={<OrgSmtp />} />`
   - `<Route path="genes" element={<OrgGenes />} />` (new page, see Task D2)
2. In tenantId org-settings section, add:
   - `<Route path="genes" element={<OrgGenes />} />`
3. **FIX OrgSettingsLayout navigation URLs (BLOCKER B1)**: `OrgSettingsLayout.tsx` currently builds nav URLs as `` `/tenant/${tenantId}/org-settings/${tab}` `` using `useParams()`. When accessed via the generic route `/tenant/org-settings/...`, `tenantId` is undefined, producing broken URLs like `/tenant//org-settings/...`. Fix:
   - In `OrgSettingsLayout.tsx`, change nav URL construction to use a conditional base path:
     ```tsx
     const { tenantId } = useParams();
     const basePath = tenantId
       ? `/tenant/${tenantId}/org-settings`
       : '/tenant/org-settings';
     // Then build tab URLs as: `${basePath}/${tabKey}`
     ```
   - Apply this `basePath` to ALL existing tab nav items (info, members, clusters, audit, registry, smtp) AND the new genes tab
   - Verify that `useNavigate()` or `<Link>` calls in the layout all use `basePath` consistently
4. Add navigation items to `OrgSettingsLayout.tsx` for: Registry, SMTP, Genes (these tabs must appear in BOTH the generic and tenantId route contexts)

**QA Scenario**:
- Manual: Navigate to `/tenant/org-settings/registry` (generic route, no tenantId) -- expect OrgRegistry page to load; verify URL in browser does NOT contain `//`
- Manual: Navigate to `/tenant/org-settings/smtp` (generic route) -- expect OrgSmtp page to load
- Manual: Navigate to `/tenant/org-settings/genes` (generic route) -- expect OrgGenes page to load
- Manual: Navigate to `/tenant/<tenantId>/org-settings/genes` (tenantId route) -- expect OrgGenes page to load
- Manual: In OrgSettingsLayout sidebar/tabs, click each tab (info, members, clusters, audit, registry, smtp, genes) -- verify ALL navigate correctly without broken URLs in BOTH route contexts (with and without tenantId)
- Manual: Inspect browser URL after clicking each tab in generic context -- verify NO double-slash (`//`) in URL path

---

### Task D2: Frontend + Backend -- Create OrgGenes page with persistence

**Starting files**:
- Create NEW: `web/src/pages/tenant/org-settings/OrgGenes.tsx`
- Gene market store: `web/src/stores/geneMarket.ts` (480 lines)
- Gene market service: `web/src/services/geneMarketService.ts`
- Backend tenants router: `src/infrastructure/adapters/primary/web/routers/tenants.py` (prefix `/api/v1/tenants` -- add gene policy endpoints here; NOT in `genes.py` which has prefix `/api/v1/genes` and would serve at wrong URL path)
- Tenant domain model: `src/domain/model/tenant/tenant.py` (reference for tenant_id scoping)
- DB models: `src/infrastructure/adapters/secondary/persistence/models.py` (add new ORM model)

**Changes**:

Backend (persistence -- BLOCKER B2 resolved):
1. Create domain model `OrgGenePolicy` dataclass in `src/domain/model/tenant/org_gene_policy.py`:
   ```python
   @dataclass(kw_only=True)
   class OrgGenePolicy:
       id: str = field(default_factory=lambda: str(uuid.uuid4()))
       tenant_id: str
       gene_id: str
       is_enabled: bool = True
       created_at: datetime = field(default_factory=datetime.utcnow)
       updated_at: datetime = field(default_factory=datetime.utcnow)
       deleted_at: Optional[datetime] = None
   ```
2. Create ORM model `OrgGenePolicyModel` in `models.py`:
   - Columns: `id (PK)`, `tenant_id (FK -> tenants.id)`, `gene_id (FK -> genes.id)`, `is_enabled (Boolean, default=True)`, `created_at`, `updated_at`, `deleted_at`
   - Partial unique index: `Index('ix_org_gene_policy_unique', 'tenant_id', 'gene_id', unique=True, postgresql_where=text("deleted_at IS NULL"))`
3. Generate Alembic migration: `PYTHONPATH=. uv run alembic revision --autogenerate -m "add org_gene_policies table"`
4. Apply migration: `PYTHONPATH=. uv run alembic upgrade head`
5. Create repository `SqlOrgGenePolicyRepository` in `src/infrastructure/adapters/secondary/persistence/sql_org_gene_policy_repository.py`
6. Add API endpoints in `tenants.py` router (which has prefix `/api/v1/tenants`, so endpoints are served at the correct paths):
   - `GET /tenants/{tenant_id}/gene-policies` -- list all gene policies for the tenant (returns gene_id + is_enabled pairs; genes without a policy row are implicitly enabled)
   - `PUT /tenants/{tenant_id}/gene-policies/{gene_id}` -- upsert gene policy: `{ "is_enabled": bool }`. Creates row if not exists, updates if exists. Returns the updated policy.
   - `DELETE /tenants/{tenant_id}/gene-policies/{gene_id}` -- soft-delete the policy (restores gene to default-enabled state)
7. Endpoints are already registered via tenants.py router inclusion in main.py -- no additional registration needed

Frontend:
8. Create `OrgGenes.tsx`:
   - Org-level gene policy management: allowed/blocked gene list
   - Ant Design Table with columns: Gene Name, Description, Status (Switch component for enable/disable)
   - Fetches gene list from existing gene market service + policy state from new `GET /tenants/{tenant_id}/gene-policies` endpoint
   - Toggle calls `PUT /tenants/{tenant_id}/gene-policies/{gene_id}` with `{ is_enabled: !currentState }`
   - Merge gene list with policy state: if no policy row for a gene, default to enabled
9. Add methods to `geneMarketService.ts`:
   - `getGenePolicies(tenantId: string): Promise<OrgGenePolicy[]>`
   - `updateGenePolicy(tenantId: string, geneId: string, isEnabled: boolean): Promise<OrgGenePolicy>`
10. All strings via i18n

**Reference**: nodeskclaw org-settings gene management concept

**QA Scenario**:
- Tool: `curl http://localhost:8000/api/v1/tenants/<tid>/gene-policies -H "Authorization: Bearer <token>"` -- expect array (empty initially = all genes enabled by default)
- Tool: `curl -X PUT http://localhost:8000/api/v1/tenants/<tid>/gene-policies/<gene_id> -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"is_enabled": false}'` -- expect 200 with policy object showing `is_enabled: false`
- Tool: `curl http://localhost:8000/api/v1/tenants/<tid>/gene-policies -H "Authorization: Bearer <token>"` -- expect array with the disabled gene policy
- Manual: Navigate to `/tenant/org-settings/genes` -- expect gene policy table with list of genes, each with a toggle switch
- Manual: Toggle a gene's enabled state via UI Switch -- expect state change persisted (refresh page, verify switch state unchanged)
- Manual: Toggle same gene back -- expect re-enabled
- Manual: Verify i18n: switch language, verify all labels translated
- Tool: `PYTHONPATH=. uv run alembic current` -- verify migration applied
- Tool: `uv run pytest src/tests/ -v -k "gene_polic"` -- verify any new tests pass

---

### Task D3: Backend + Frontend -- Wire OrgRegistry to real API

**Starting files**:
- Frontend page: `web/src/pages/tenant/org-settings/OrgRegistry.tsx` (701 lines, uses MOCK_REGISTRIES)
- Create NEW: `web/src/services/registryService.ts`
- Create NEW: `src/infrastructure/adapters/primary/web/routers/org_registry.py`
- Tenants router: `src/infrastructure/adapters/primary/web/routers/tenants.py` (for registration)

**Changes**:
Backend:
1. Create `org_registry.py` router with endpoints:
   - `GET /tenants/{tenant_id}/registries` -- list container registries
   - `POST /tenants/{tenant_id}/registries` -- add registry
   - `PUT /tenants/{tenant_id}/registries/{registry_id}` -- update registry
   - `DELETE /tenants/{tenant_id}/registries/{registry_id}` -- soft-delete registry
   - `POST /tenants/{tenant_id}/registries/{registry_id}/test` -- test connectivity
2. Create domain model: `RegistryConfig` dataclass with fields: id, tenant_id, name, type, url, username, password_encrypted, is_active, created_at, deleted_at
3. Create DB model + migration (with soft-delete: `deleted_at` column, partial unique index on `name` where `deleted_at IS NULL`)
4. Create repository: `SqlRegistryRepository`
5. Register router in main.py

Frontend:
6. Create `registryService.ts` with methods: list, create, update, delete, testConnectivity
7. Update `OrgRegistry.tsx`: replace `MOCK_REGISTRIES` with real API calls via registryService
8. Add registry store or use inline state (page is already 701 lines -- inline state acceptable)

**Reference**: nodeskclaw `app/api/registry.py` + `app/services/registry_service.py` (Docker Registry v2 auth)

**QA Scenario**:
- Tool: `curl http://localhost:8000/api/v1/tenants/<tid>/registries -H "Authorization: Bearer <token>"` -- expect empty array initially
- Tool: `curl -X POST http://localhost:8000/api/v1/tenants/<tid>/registries -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"name": "test-registry", "type": "docker", "url": "https://registry.example.com", "username": "user"}'` -- expect 201
- Manual: Navigate to `/tenant/org-settings/registry` -- expect real registries from API (not mock data)
- Manual: Add a registry via UI form, verify it appears in the list
- Manual: Test connectivity button -- expect success/failure feedback

---

## Group E: Missing Pages (P1) -- Deps: None

### Task E1: Frontend -- Evolution Log page + Fix gene install/uninstall API paths

**Starting files**:
- Create NEW: `web/src/pages/tenant/EvolutionLog.tsx`
- App routes: `web/src/App.tsx` (add route)
- Gene market service: `web/src/services/geneMarketService.ts` (has WRONG install/uninstall paths + missing instanceId on evolution log method)
- Gene market store: `web/src/stores/geneMarket.ts`

**Changes**:

**PREREQUISITE -- Fix geneMarketService.ts API path mismatches (BLOCKER B5, updated with F1+F2 corrections)**:
The following methods in `geneMarketService.ts` have INCORRECT API paths/methods that do NOT match the backend router (`genes.py` prefix `/api/v1/genes`):
- `installGene` currently calls `POST /api/v1/genes/install` -- WRONG. Backend route is `POST /api/v1/genes/instances/{instance_id}/install` (genes.py line ~460). Fix to: `httpClient.post(`/genes/instances/${instanceId}/install`, data)` (relative to httpClient baseURL `/api/v1`). Method signature must accept `instanceId` as parameter.
- `uninstallGene` currently calls `POST /api/v1/genes/uninstall` -- WRONG METHOD AND PATH. Backend route is `DELETE /api/v1/genes/instances/{instance_id}/genes/{instance_gene_id}` (genes.py line ~507-518). Fix to: `httpClient.delete(`/genes/instances/${instanceId}/genes/${instanceGeneId}`)`. Note: the backend uses `instance_gene_id` (the ID of the gene-instance association record), NOT `gene_id`. Method signature must accept both `instanceId` and `instanceGeneId` as parameters. Update all callers to pass `instanceGeneId` instead of `gene_id`.
- `listEvolutionEvents` currently calls `GET ${BASE_URL}/evolution` with params -- PATH IS ALREADY CORRECT. Backend route is `GET /api/v1/genes/evolution?instance_id=...` (genes.py line ~689-704, query-param-based). The existing `${BASE_URL}/evolution` path resolves to `/genes/evolution` which matches. Fix: update method signature to accept `instanceId` as a required first parameter, and include `instance_id` in the params object: `httpClient.get(`${BASE_URL}/evolution`, { params: { ...params, instance_id: instanceId } })`. Do NOT change the URL path -- there is NO `/genes/instances/{instance_id}/evolution-log` endpoint.
These 3 fixes MUST be applied before creating the EvolutionLog page.

**Page creation**:
1. Create `EvolutionLog.tsx`:
   - Ant Design Timeline component showing evolution events
   - Each event: gene name, event type (install/upgrade/remove), timestamp, details
   - Pagination (page/page_size)
   - Filter by event type
2. Add route: `/tenant/instances/:instanceId/evolution` in `App.tsx`
3. Add/update `getEvolutionLog(instanceId: string, page: number, pageSize: number)` to geneMarketService (uses existing correct path `${BASE_URL}/evolution` with `{ params: { instance_id: instanceId, page, page_size: pageSize } }` -- query-param-based, NOT path-param-based)
4. All strings via i18n

**Reference**: nodeskclaw `GET /genes/instances/{instance_id}/evolution-log`, EvolutionEventInfo schema: `{ id, instance_id, event_type, gene_name, gene_slug, gene_id, genome_id, details, created_at }`. NOTE: In agi-demos, the equivalent backend endpoint is `GET /api/v1/genes/evolution?instance_id=...` (query-param-based, NOT path-param-based). Do NOT create a nonexistent `/evolution-log` endpoint.

**QA Scenario**:
- Tool: Verify corrected API paths compile -- `pnpm lint` in `web/` should pass
- Tool: `curl -X POST http://localhost:8000/api/v1/genes/instances/<instance_id>/install -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"gene_id": "<gene_id>"}'` -- expect 200 (verify backend route works)
- Tool: `curl "http://localhost:8000/api/v1/genes/evolution?instance_id=<instance_id>" -H "Authorization: Bearer <token>"` -- expect array of evolution events (query-param-based endpoint)
- Manual: Navigate to `/tenant/instances/<id>/evolution` -- expect timeline view (empty if no events)
- Manual: Install a gene on the instance via UI, then check evolution log -- expect install event in timeline
- Manual: Verify pagination -- if >10 events, page controls work
- Manual: Verify i18n: switch language, verify all labels translated

---

### Task E2: Frontend -- Genome Detail page

**Starting files**:
- Create NEW: `web/src/pages/tenant/GenomeDetail.tsx`
- App routes: `web/src/App.tsx` (add route)
- Gene market service: `web/src/services/geneMarketService.ts`
- Gene market store: `web/src/stores/geneMarket.ts`

**Changes**:
1. Create `GenomeDetail.tsx`:
   - Display genome info: name, description, icon, visibility, avg_rating, install_count
   - List constituent genes (from gene_slugs) with links to gene detail
   - Install/uninstall genome button
   - Rating display (stars)
2. Add route: `/tenant/genes/genome/:genomeId` in `App.tsx`
3. Ensure geneMarketService has `getGenome(genomeId)` method
4. All strings via i18n

**Reference**: nodeskclaw Genome model: `{ id, name, slug, description, short_description, icon, gene_slugs, config_override, install_count, avg_rating, is_featured, is_published, visibility }`

**QA Scenario**:
- Manual: Navigate to `/tenant/genes/genome/<id>` -- expect genome detail with name, description, gene list
- Manual: Click a gene in the gene list -- expect navigation to gene detail page
- Manual: Click install -- expect genome installed (all constituent genes added)
- Manual: Verify i18n

---

### Task E3: Frontend -- Template Detail page

**Starting files**:
- Create NEW: `web/src/pages/tenant/TemplateDetail.tsx`
- App routes: `web/src/App.tsx` (add route)
- Instance service: `web/src/services/instanceService.ts`

**Changes**:
1. Create `TemplateDetail.tsx`:
   - Display template metadata: name, description, visibility, created_by
   - Show included genes/config (topology_snapshot, gene_assignments visualization)
   - "Deploy from Template" button (creates instance from template)
2. Add route: `/tenant/instance-templates/:templateId` in `App.tsx`
3. Add `getTemplate(templateId)` to instanceService if not present
4. All strings via i18n

**Reference**: nodeskclaw `GET /templates/{template_id}` returns `{ topology_snapshot, blackboard_snapshot, gene_assignments, metadata }`

**QA Scenario**:
- Manual: Navigate to `/tenant/instance-templates/<id>` -- expect template detail with gene assignments
- Manual: Click "Deploy from Template" -- expect instance creation flow initiated
- Manual: Verify i18n

---

### Task E4: Frontend + Backend -- Deploy Progress SSE Streaming

**Starting files**:
- Frontend page: `web/src/pages/tenant/DeployProgress.tsx` (251 lines -- timeline only, no SSE)
- Deploy store: `web/src/stores/deploy.ts`
- Deploy service: `web/src/services/deployService.ts`
- Backend router: `src/infrastructure/adapters/primary/web/routers/deploy.py` (prefix: `/api/v1/deploys`)
- Backend service: `src/application/services/deploy_service.py`

**Changes**:
Backend:
1. Add SSE endpoint in `deploy.py` with decorator `@router.get("/progress/{deploy_id}")`. Since the router prefix is `/api/v1/deploys`, this serves at `GET /api/v1/deploys/progress/{deploy_id}`. The endpoint:
   - Subscribes to Redis channel `deploy_progress:{deploy_id}`
   - Streams DeployProgress events as SSE
   - Terminates on status `success` or `failed`
   - **IMPORTANT (F4)**: Must also accept `token` as an optional query parameter for authentication, in addition to the standard `Authorization: Bearer` header. This is because browser `EventSource` API cannot set custom headers. The endpoint should check: (1) Authorization header first, (2) if not present, check `token` query param, (3) if neither, return 401. Example: `GET /api/v1/deploys/progress/{deploy_id}?token=<jwt>`
2. Modify deploy pipeline in `deploy_service.py` to publish DeployProgress events to Redis during execution
3. DeployProgress schema: `{ deploy_id, step, total_steps, current_step, status, message, percent, logs, step_names }`

Frontend:
4. Add EventSource/fetchEventSource to `DeployProgress.tsx`:
   - Connect to `/api/v1/deploys/progress/${deployId}` SSE endpoint on mount (NOTE: path is `/deploys/progress/`, NOT `/deploy/progress/`)
   - **IMPORTANT (F4)**: Browser `EventSource` API cannot set custom `Authorization` headers. Must pass JWT token as query parameter: `new EventSource(`/api/v1/deploys/progress/${deployId}?token=${accessToken}`)`. Get `accessToken` from auth store.
   - Update deploy store with real-time progress events
   - Show live log output component (auto-scrolling code block)
   - Handle reconnection on disconnect
5. Add SSE event handling to deploy store or component state
6. All strings via i18n

**Reference**: nodeskclaw `GET /deploy/progress/{deploy_id}` SSE endpoint, EventBus publish/subscribe pattern, DeployProgress schema

**QA Scenario**:
- Manual: Start a deploy, navigate to deploy progress page -- expect real-time step updates appearing
- Manual: Observe progress bar / percent increasing in real-time
- Manual: Observe log lines appearing in real-time as deploy executes
- Manual: When deploy completes, stream should close and final status shown
- Tool: `curl -N http://localhost:8000/api/v1/deploys/progress/<deploy_id> -H "Authorization: Bearer <token>"` -- expect SSE events streaming
- Tool: `curl -N "http://localhost:8000/api/v1/deploys/progress/<deploy_id>?token=<jwt>"` -- expect same SSE events streaming (verifies query-param auth works for EventSource compatibility)
- Tool: `curl -N http://localhost:8000/api/v1/deploys/progress/<deploy_id>` -- expect 401 Unauthorized (no auth provided)

---

## Group F: Gene Market Enhancements (P2) -- Deps: Group E

### Task F1: Frontend + Backend -- Gene Reviews system

**Starting files**:
- Gene market store: `web/src/stores/geneMarket.ts` (480 lines)
- Gene market service: `web/src/services/geneMarketService.ts`
- Backend genes router: `src/infrastructure/adapters/primary/web/routers/genes.py`

**Changes**:
Backend:
1. Add review model (domain + DB): `{ id, gene_id, user_id, rating, content, created_at, deleted_at }`
2. Add review endpoints in `genes.py`:
   - `GET /genes/{gene_id}/reviews` -- list reviews
   - `POST /genes/{gene_id}/reviews` -- create review
   - `DELETE /genes/{gene_id}/reviews/{review_id}` -- soft-delete review
3. Migration for reviews table

Frontend:
4. Add review section to GeneDetail page (or create ReviewList component)
5. Add review methods to geneMarketService and store
6. All strings via i18n

**QA Scenario**:
- Tool: `curl http://localhost:8000/api/v1/genes/<id>/reviews -H "Authorization: Bearer <token>"` -- expect array
- Manual: Navigate to gene detail, submit a review -- expect review appears in list
- Manual: Delete own review -- expect review removed

---

## Group G: Platform Features (P2) -- Deps: None

### Task G1: Backend + Frontend -- CE/EE Feature Gating Infrastructure

**Starting files**:
- Backend config: `src/configuration/config.py`
- Create NEW: `src/configuration/features.py`
- Frontend: `web/src/App.tsx`
- Create NEW: `web/src/utils/featureCheck.ts`

**Changes**:
Backend:
1. Create `features.py` with feature flag definitions (all CE features enabled by default)
2. Add `GET /system/features` endpoint returning enabled feature list
3. Include features in tenant config response

Frontend:
4. Create `featureCheck.ts` utility: `isFeatureEnabled(feature: string): boolean`
5. Add `FeatureGate` wrapper component for conditional rendering
6. Add `requireFeature` support to route definitions in `App.tsx`
7. Fetch features on auth store init

**QA Scenario**:
- Tool: `curl http://localhost:8000/api/v1/system/features -H "Authorization: Bearer <token>"` -- expect feature list
- Manual: Wrap a route with FeatureGate for a disabled feature -- expect redirect to 403 or home
- Manual: Enable the feature -- expect route accessible

---

### Task G2: Frontend -- OrgSetup Redirect Guard

**Starting files**:
- App routes: `web/src/App.tsx`
- Auth store: `web/src/stores/auth.ts`

**Changes**:
1. Add org setup completeness check to auth store (call tenant info on login, check required fields)
2. Add guard logic: if org not fully configured, redirect to `/tenant/org-settings/info`
3. Show setup wizard banner or redirect on first login

**QA Scenario**:
- Manual: Create new tenant with incomplete setup -- expect redirect to org-settings/info
- Manual: Complete setup -- expect redirect stops, normal navigation works

---

### Task G3: Backend + Frontend -- Events System

**Starting files**:
- Create NEW: `src/infrastructure/adapters/primary/web/routers/events.py`
- Create NEW: `web/src/pages/tenant/Events.tsx`
- Create NEW: `web/src/services/eventService.ts`

**Changes**:
Backend:
1. Create events router with:
   - `GET /events` -- list system events with filters (type, date range, pagination)
   - `GET /events/stream` -- SSE for real-time events (optional)
2. Event model: `{ id, type, message, source, metadata, created_at }`
3. Store events in DB (create model + migration)

Frontend:
4. Create Events.tsx page with event list (Ant Design Table), filters, date range picker
5. Add route in App.tsx
6. All strings via i18n

**Reference**: nodeskclaw `app/api/events.py` -- K8s event mapping

**QA Scenario**:
- Manual: Navigate to `/tenant/events` -- expect event list (empty initially)
- Tool: `curl http://localhost:8000/api/v1/events -H "Authorization: Bearer <token>"` -- expect array

---

### Task G4: Backend + Frontend -- Webhook Management

**Starting files**:
- Create NEW: `src/infrastructure/adapters/primary/web/routers/webhooks.py`
- Create NEW: `web/src/pages/tenant/Webhooks.tsx`
- Create NEW: `web/src/services/webhookService.ts`

**Changes**:
Backend:
1. Create webhook model: `{ id, tenant_id, name, url, secret, events, is_active, created_at, deleted_at }`
2. Create webhook router:
   - `GET /tenants/{tenant_id}/webhooks` -- list
   - `POST /tenants/{tenant_id}/webhooks` -- create
   - `PUT /tenants/{tenant_id}/webhooks/{webhook_id}` -- update
   - `DELETE /tenants/{tenant_id}/webhooks/{webhook_id}` -- soft-delete
   - `POST /tenants/{tenant_id}/webhooks/{webhook_id}/test` -- send test event
3. Migration with soft-delete pattern

Frontend:
4. Create Webhooks.tsx with CRUD UI (Ant Design Table + Modal forms)
5. Add route in App.tsx
6. All strings via i18n

**Reference**: nodeskclaw `app/api/webhooks.py`

**QA Scenario**:
- Manual: Navigate to `/tenant/webhooks` -- expect webhook list page
- Manual: Create webhook via UI -- expect webhook in list
- Manual: Click test -- expect test event sent (success feedback)
- Tool: `curl http://localhost:8000/api/v1/tenants/<tid>/webhooks -H "Authorization: Bearer <token>"` -- expect array

---

## Group H: i18n Retrofit (P2) -- Deps: None (can be parallelized)

### Task H1: Retrofit 16 pages with i18n

**Pages needing retrofit** (verified V8):
1. `web/src/pages/tenant/org-settings/OrgSettingsLayout.tsx`
2. `web/src/pages/tenant/WorkspaceList.tsx`
3. `web/src/pages/tenant/WorkspaceDetail.tsx`
4. `web/src/pages/tenant/WorkflowPatterns.tsx`
5. `web/src/pages/project/schema/EdgeTypeList.tsx`
6. `web/src/pages/project/schema/EntityTypeList.tsx`
7. `web/src/pages/project/communities/index.tsx`
8. `web/src/pages/project/CronJobs.tsx`
9. `web/src/pages/project/Settings.tsx`
10. `web/src/pages/tenant/PluginHub.tsx`
11. `web/src/pages/project/ChannelConfig.tsx`
12. `web/src/pages/admin/PoolDashboard.tsx`
13. `web/src/pages/admin/DeadLetterQueue.tsx`
14. `web/src/pages/tenant/ChartComponents.tsx`
15. `web/src/pages/project/Team.tsx`
16. `web/src/pages/project/CommunitiesList.tsx`

**Changes per page**:
1. Add `import { useTranslation } from 'react-i18next';`
2. Add `const { t } = useTranslation();` in component body
3. Replace all hardcoded English strings with `t('namespace.key')`
4. Add corresponding keys to `web/src/locales/en-US.json` and `web/src/locales/zh-CN.json`

**Constraints**:
- Must add BOTH en-US and zh-CN translations
- Keys must follow existing locale file structure/namespacing

**QA Scenario**:
- Manual: For each page, switch to zh-CN locale -- expect all visible text in Chinese
- Manual: Switch to en-US locale -- expect all visible text in English
- Tool: `grep -rL "useTranslation" web/src/pages/ --include="*.tsx"` -- expect 0 results after retrofit

---

## Group I: P3 Features (Low Priority) -- Deferred

These are documented but not scheduled for immediate implementation:

| Item | Decision | Rationale |
|------|----------|-----------|
| Portal dual-prefix routing | DEFERRED (AD-1) | Existing tenant/project RBAC sufficient |
| Tunnel management | DEFERRED | Infrastructure feature, no user demand |
| Corridors management | DEFERRED | Infrastructure feature, no user demand |
| Engines/runtime management | DEFERRED | agi-demos uses LiteLLM providers instead |
| Storage management | DEFERRED | Not in current product scope |
| Security WebSocket | DEFERRED | Audit logs provide similar functionality |
| Runtime admin | DEFERRED | Pool dashboard exists for admin monitoring |

---

## Execution Dependencies Graph

```
Group A (Force Password)     ── independent
Group B (Instance LLM)       ── independent
Group C (Workspace Settings) ── independent
Group D (OrgSettings Routes) ── independent
Group E (Missing Pages)      ── independent (E4 needs backend SSE)
Group F (Gene Reviews)       ── depends on Group E (E2 GenomeDetail)
Group G (Platform Features)  ── independent
Group H (i18n Retrofit)      ── independent (can parallelize all 16 pages)
```

**Recommended parallel execution**:
- Wave 1: Groups A, B, C, D (all P0, all independent)
- Wave 2: Groups E, H (P1 pages + P2 i18n, independent)
- Wave 3: Groups F, G (P2, after E completes)

---

## Summary

| Priority | Tasks | Estimated Effort |
|----------|-------|-----------------|
| P0 | A1-A3, B1-B2, C1, D1-D3 | 10 tasks |
| P1 | E1-E4 | 4 tasks |
| P2 | F1, G1-G4, H1 | 6 tasks |
| P3 | Deferred (7 items) | 0 tasks now |
| **Total Active** | **20 tasks** | |
