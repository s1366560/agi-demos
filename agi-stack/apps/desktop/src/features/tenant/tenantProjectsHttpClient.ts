import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  TenantProjectRecord,
  TenantProjectsAvailability,
  TenantProjectsClient,
  TenantProjectsListQuery,
  TenantProjectsListSnapshot,
  TenantProjectsMutationInput,
  TenantProjectsRequestOptions,
  TenantProjectsScope,
} from './tenantProjectsClient';
import {
  createTenantProjectsMutationKey,
  type TenantProjectsMutationAction,
} from './tenantProjectsClient';

const CATALOG_ACTIONS = Object.freeze(['view', 'list']);
const PROJECT_VIEW_ACTIONS = Object.freeze(['view']);

export function createTenantProjectsHttpClient(
  config: DesktopRuntimeConfig,
): TenantProjectsClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async list(scope, query = {}, options) {
      requireRuntimeScope(runtimeConfig, scope);
      const params = listQuery(scope.tenantId, query);
      const payload = await requestJson(
        runtimeConfig,
        `${collectionPath(runtimeConfig)}?${params.toString()}`,
        { method: 'GET', signal: options?.signal },
      );
      const cloudAuthority =
        scope.authority === 'cloud'
          ? await loadCloudProjectAuthority(
              runtimeConfig,
              payload,
              scope,
              options?.signal,
            )
          : null;
      return projectListSnapshot(payload, scope, cloudAuthority);
    },
    async get(scope, projectId, options) {
      requireRuntimeScope(runtimeConfig, scope);
      const id = requireIdentifier(projectId, 'project');
      const params = new URLSearchParams({ tenant_id: scope.tenantId });
      const payload = await requestJson(
        runtimeConfig,
        `${projectPath(runtimeConfig, id)}?${params.toString()}`,
        { method: 'GET', signal: options?.signal },
      );
      return projectRecord(payload, scope, contractReason(scope.authority));
    },
    async create(scope, input, options) {
      requireRuntimeScope(runtimeConfig, scope);
      const payload = await requestJson(runtimeConfig, collectionPath(runtimeConfig), {
        method: 'POST',
        body: mutationBody(scope, input, true),
        signal: options?.signal,
        idempotencyKey: mutationKey('create', options?.idempotencyKey),
      });
      return projectRecord(payload, scope, contractReason(scope.authority));
    },
    async update(scope, projectId, input, options) {
      requireRuntimeScope(runtimeConfig, scope);
      const id = requireIdentifier(projectId, 'project');
      const payload = await requestJson(
        runtimeConfig,
        projectPath(runtimeConfig, id),
        {
          method: 'PUT',
          body: mutationBody(scope, input, false),
          signal: options?.signal,
          idempotencyKey: mutationKey('update', options?.idempotencyKey),
        },
      );
      return projectRecord(payload, scope, contractReason(scope.authority));
    },
    async delete(scope, projectId, options) {
      requireRuntimeScope(runtimeConfig, scope);
      const id = requireIdentifier(projectId, 'project');
      await requestJson(runtimeConfig, deletePath(runtimeConfig, id), {
          method: runtimeConfig.mode === 'local' ? 'POST' : 'DELETE',
          signal: options?.signal,
          idempotencyKey: mutationKey('delete', options?.idempotencyKey),
          allowEmpty: true,
        });
    },
  });
}

type RequestOptions = Readonly<{
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: Readonly<Record<string, unknown>>;
  signal?: AbortSignal;
  idempotencyKey?: string;
  allowEmpty?: boolean;
}>;

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  options: RequestOptions,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  if (options.idempotencyKey) {
    headers.set('Idempotency-Key', options.idempotencyKey);
  }
  if (options.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
    method: options.method,
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });
  if (options.allowEmpty && response.status === 204) return null;
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(
      errorMessage(response.status, payload),
      response.status,
      payload,
    );
  }
  if (!isJson || payload === null) {
    throw contractError(`${config.mode}_tenant_projects_contract_invalid`);
  }
  return payload;
}

function projectListSnapshot(
  payload: unknown,
  scope: TenantProjectsScope,
  cloudAuthority: CloudProjectAuthority | null,
): TenantProjectsListSnapshot {
  const reason = contractReason(scope.authority);
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.projects) ||
    !isNonnegativeInteger(payload.total) ||
    !isPositiveInteger(payload.page) ||
    !isPositiveInteger(payload.page_size)
  ) {
    throw contractError(reason);
  }
  if (scope.authority === 'cloud') {
    if (cloudAuthority === null) throw contractError(reason);
    const projects = Object.freeze(
      payload.projects.map((project) => {
        const projectId =
          isRecord(project) && isNonEmptyString(project.id) ? project.id : '';
        const actions = cloudAuthority.projectActions.get(projectId);
        if (!actions) throw contractError(reason);
        return projectRecord(project, scope, reason, actions);
      }),
    );
    return Object.freeze({
      scope,
      authority: scope.authority,
      projects,
      total: payload.total,
      page: payload.page,
      pageSize: payload.page_size,
      ownerIds: Object.freeze(optionalStringArray(payload.owner_ids, reason)),
      availability: 'available',
      reasonCode: null,
      serviceVersion: 'cloud',
      contractVersion: '3.0.0',
      allowedActions: cloudAuthority.allowedActions,
      authorityRevision: null,
    });
  }
  if (
    !isAvailability(payload.availability) ||
    !isNullableReason(payload.reason_code) ||
    !isNonEmptyString(payload.service_version) ||
    !isNonEmptyString(payload.contract_version) ||
    !isStringArray(payload.allowed_actions) ||
    !isNonnegativeInteger(payload.authority_revision) ||
    !isRecord(payload.scope) ||
    payload.scope.tenant_id !== scope.tenantId ||
    payload.scope.project_id !== null ||
    payload.scope.workspace_id !== null ||
    payload.scope.instance_id !== null
  ) {
    throw contractError(reason);
  }
  const allowedActions = Object.freeze([...payload.allowed_actions]);
  return Object.freeze({
    scope,
    authority: scope.authority,
    projects: Object.freeze(
      payload.projects.map((project) =>
        projectRecord(
          project,
          scope,
          reason,
          projectActions(allowedActions),
        ),
      ),
    ),
    total: payload.total,
    page: payload.page,
    pageSize: payload.page_size,
    ownerIds: Object.freeze(optionalStringArray(payload.owner_ids, reason)),
    availability: payload.availability,
    reasonCode: payload.reason_code,
    serviceVersion: payload.service_version,
    contractVersion: payload.contract_version,
    allowedActions,
    authorityRevision: payload.authority_revision,
  });
}

function projectRecord(
  payload: unknown,
  scope: TenantProjectsScope,
  reason: string,
  allowedActions: readonly string[] = Object.freeze([]),
): TenantProjectRecord {
  if (
    !isRecord(payload) ||
    !isNonEmptyString(payload.id) ||
    payload.tenant_id !== scope.tenantId ||
    !isNonEmptyString(payload.name) ||
    !isOptionalNullableString(payload.description) ||
    !isNonEmptyString(payload.owner_id) ||
    !isStringArray(payload.member_ids) ||
    typeof payload.is_public !== 'boolean' ||
    !isNonEmptyString(payload.created_at) ||
    !isOptionalNullableString(payload.updated_at) ||
    !isOptionalNullableRecord(payload.stats)
  ) {
    throw contractError(reason);
  }
  return Object.freeze({
    id: payload.id,
    tenantId: payload.tenant_id,
    name: payload.name,
    description: payload.description ?? '',
    ownerId: payload.owner_id,
    memberIds: Object.freeze([...payload.member_ids]),
    allowedActions: Object.freeze([...allowedActions]),
    isPublic: payload.is_public,
    createdAt: payload.created_at,
    updatedAt: payload.updated_at ?? null,
    stats: Object.freeze({ ...(payload.stats ?? {}) }),
  });
}

type CloudProjectAuthority = Readonly<{
  allowedActions: readonly string[];
  projectActions: ReadonlyMap<string, readonly string[]>;
}>;

async function loadCloudProjectAuthority(
  config: DesktopRuntimeConfig,
  payload: unknown,
  scope: TenantProjectsScope,
  signal?: AbortSignal,
): Promise<CloudProjectAuthority> {
  const reason = contractReason(scope.authority);
  if (!isRecord(payload) || !Array.isArray(payload.projects)) {
    throw contractError(reason);
  }
  const projectIds = payload.projects.map((project) => {
    if (!isRecord(project) || !isNonEmptyString(project.id)) {
      throw contractError(reason);
    }
    return project.id;
  });
  if (new Set(projectIds).size !== projectIds.length) {
    throw contractError(reason);
  }
  const [user, workspaceContext, ...memberSnapshots] = await Promise.all([
    requestJson(config, '/api/v1/auth/me', { method: 'GET', signal }),
    requestJson(config, '/api/v1/workspace-context', { method: 'GET', signal }),
    ...projectIds.map((projectId) =>
      requestJson(
        config,
        `/api/v1/projects/${encodeURIComponent(projectId)}/members`,
        { method: 'GET', signal },
      ),
    ),
  ]);
  const userId = cloudAuthorityUserId(user, reason);
  const tenantRole = cloudAuthorityTenantRole(workspaceContext, scope, reason);
  const projectActionsById = new Map<string, readonly string[]>();
  memberSnapshots.forEach((snapshot, index) => {
    const projectId = projectIds[index];
    if (!projectId) throw contractError(reason);
    projectActionsById.set(
      projectId,
      cloudProjectActions(snapshot, userId, reason),
    );
  });
  const allowed = [...CATALOG_ACTIONS];
  if (tenantRole === 'owner' || tenantRole === 'admin') allowed.push('create');
  if ([...projectActionsById.values()].some((actions) => actions.includes('update'))) {
    allowed.push('update');
  }
  if ([...projectActionsById.values()].some((actions) => actions.includes('delete'))) {
    allowed.push('delete');
  }
  return Object.freeze({
    allowedActions: Object.freeze(allowed),
    projectActions: projectActionsById,
  });
}

function cloudAuthorityUserId(payload: unknown, reason: string): string {
  if (!isRecord(payload) || !isNonEmptyString(payload.user_id)) {
    throw contractError(reason);
  }
  return payload.user_id;
}

function cloudAuthorityTenantRole(
  payload: unknown,
  scope: TenantProjectsScope,
  reason: string,
): string {
  if (
    !isRecord(payload) ||
    !isRecord(payload.context) ||
    payload.context.tenant_id !== scope.tenantId ||
    !isNonEmptyString(payload.membership_role)
  ) {
    throw contractError(reason);
  }
  return payload.membership_role;
}

function cloudProjectActions(
  payload: unknown,
  userId: string,
  reason: string,
): readonly string[] {
  if (!isRecord(payload) || !Array.isArray(payload.members)) {
    throw contractError(reason);
  }
  const membership = payload.members.find(
    (member) => isRecord(member) && member.user_id === userId,
  );
  if (!isRecord(membership) || !isNonEmptyString(membership.role)) {
    throw contractError(reason);
  }
  const actions = [...PROJECT_VIEW_ACTIONS];
  if (membership.role === 'owner' || membership.role === 'admin') {
    actions.push('update');
  }
  if (membership.role === 'owner') actions.push('delete');
  return Object.freeze(actions);
}

function projectActions(actions: readonly string[]): readonly string[] {
  return Object.freeze(
    actions.filter(
      (action) =>
        action === 'view' || action === 'update' || action === 'delete',
    ),
  );
}

function listQuery(
  tenantId: string,
  query: TenantProjectsListQuery,
): URLSearchParams {
  const params = new URLSearchParams({
    tenant_id: tenantId,
    page: String(query.page ?? 1),
    page_size: String(query.pageSize ?? 20),
  });
  if (query.search?.trim()) params.set('search', query.search.trim());
  if (query.visibility && query.visibility !== 'all') {
    params.set('visibility', query.visibility);
  }
  if (query.ownerId?.trim()) params.set('owner_id', query.ownerId.trim());
  return params;
}

function mutationBody(
  scope: TenantProjectsScope,
  input: TenantProjectsMutationInput,
  includeTenant: boolean,
): Readonly<Record<string, unknown>> {
  const name = input.name.trim();
  if (!name || name.length > 200) {
    throw new Error('tenant_project_name_invalid');
  }
  const description = input.description.trim();
  if (description.length > 4_000) {
    throw new Error('tenant_project_description_invalid');
  }
  return Object.freeze({
    ...(includeTenant ? { tenant_id: scope.tenantId } : {}),
    name,
    description,
    ...(input.isPublic === undefined ? {} : { is_public: input.isPublic }),
  });
}

function requireRuntimeScope(
  config: DesktopRuntimeConfig,
  scope: TenantProjectsScope,
): void {
  if (config.mode !== scope.authority || config.tenantId !== scope.tenantId) {
    throw new Error('tenant_projects_runtime_scope_mismatch');
  }
}

function collectionPath(config: DesktopRuntimeConfig): string {
  return config.mode === 'local' ? '/api/v1/tenant-projects' : '/api/v1/projects/';
}

function projectPath(config: DesktopRuntimeConfig, projectId: string): string {
  const root = config.mode === 'local' ? '/api/v1/tenant-projects' : '/api/v1/projects';
  return `${root}/${encodeURIComponent(projectId)}`;
}

function deletePath(config: DesktopRuntimeConfig, projectId: string): string {
  const project = projectPath(config, projectId);
  return config.mode === 'local' ? `${project}/archive` : project;
}

function requireIdentifier(value: string, label: string): string {
  if (!value || value !== value.trim() || value.length > 512) {
    throw new Error(`tenant_${label}_identifier_invalid`);
  }
  return value;
}

function mutationKey(
  action: TenantProjectsMutationAction,
  provided: string | undefined,
): string {
  const key = provided ?? createTenantProjectsMutationKey(action);
  if (
    key.length === 0 ||
    key.length > 255 ||
    key !== key.trim() ||
    ![...key].every((character) => {
      const code = character.charCodeAt(0);
      return code >= 0x21 && code <= 0x7e;
    })
  ) {
    throw new Error('tenant_project_idempotency_key_invalid');
  }
  return key;
}

function contractReason(authority: TenantProjectsScope['authority']): string {
  return `${authority}_tenant_projects_contract_invalid`;
}

function contractError(reason: string): DesktopApiError {
  return new DesktopApiError(reason, 0, { reason_code: reason });
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string') return payload.detail;
  if (isRecord(payload) && typeof payload.reason_code === 'string') {
    return payload.reason_code;
  }
  return `Tenant Projects request failed (${status})`;
}

function optionalStringArray(value: unknown, reason: string): string[] {
  if (value === undefined) return [];
  if (!isStringArray(value)) throw contractError(reason);
  return [...value];
}

function isAvailability(value: unknown): value is TenantProjectsAvailability {
  return (
    value === 'available' ||
    value === 'degraded' ||
    value === 'unavailable' ||
    value === 'not_applicable'
  );
}

function isNullableReason(value: unknown): value is string | null {
  return value === null || isNonEmptyString(value);
}

function isOptionalNullableString(
  value: unknown,
): value is string | null | undefined {
  return value === undefined || value === null || typeof value === 'string';
}

function isOptionalNullableRecord(
  value: unknown,
): value is Record<string, unknown> | null | undefined {
  return value === undefined || value === null || isRecord(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonEmptyString);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) > 0;
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
