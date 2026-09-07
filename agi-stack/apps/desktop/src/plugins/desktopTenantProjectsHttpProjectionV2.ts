import { DesktopApiError } from '../api/client';
import type {
  TenantProjectRecord,
  TenantProjectsListQuery,
  TenantProjectsListSnapshot,
  TenantProjectsMutationInput,
  TenantProjectsScope,
} from '../features/tenant/tenantProjectsClient';
import type { DesktopRuntimeConfig } from '../types';

type TenantProjectsAction = 'view' | 'list' | 'create' | 'update' | 'delete';

const CATALOG_ACTIONS_V2 = Object.freeze<TenantProjectsAction[]>(['view', 'list']);
const PROJECT_VIEW_ACTIONS_V2 = Object.freeze<TenantProjectsAction[]>(['view']);
const ACTION_ORDER_V2 = Object.freeze<TenantProjectsAction[]>([
  'view',
  'list',
  'create',
  'update',
  'delete',
]);
const SERVICE_VERSION_V2 = '0.1.0';
const CONTRACT_VERSION_V2 = '3.0.0';

export function projectDesktopTenantProjectsCloudSnapshotV2(
  payload: unknown,
  rawUser: unknown,
  rawWorkspaceContext: unknown,
  rawMemberSnapshots: readonly unknown[],
  scope: TenantProjectsScope,
): TenantProjectsListSnapshot {
  const reason = 'cloud_tenant_projects_contract_invalid';
  if (!isRecordV2(payload) || !Array.isArray(payload.projects)) {
    throw tenantProjectsContractErrorV2(reason);
  }
  const projectIds = payload.projects.map((project) => {
    if (!isRecordV2(project) || !isNonemptyV2(project.id)) {
      throw tenantProjectsContractErrorV2(reason);
    }
    return project.id;
  });
  if (
    new Set(projectIds).size !== projectIds.length ||
    rawMemberSnapshots.length !== projectIds.length
  ) {
    throw tenantProjectsContractErrorV2(reason);
  }
  const userId = cloudAuthorityUserIdV2(rawUser, reason);
  const tenantRole = cloudAuthorityTenantRoleV2(rawWorkspaceContext, scope, reason);
  const projectActions = new Map<string, readonly TenantProjectsAction[]>();
  rawMemberSnapshots.forEach((snapshot, index) => {
    const projectId = projectIds[index];
    if (projectId === undefined) throw tenantProjectsContractErrorV2(reason);
    projectActions.set(projectId, cloudProjectActionsV2(snapshot, userId, reason));
  });
  const allowedActions = [...CATALOG_ACTIONS_V2];
  if (tenantRole === 'owner' || tenantRole === 'admin') allowedActions.push('create');
  if ([...projectActions.values()].some((actions) => actions.includes('update'))) {
    allowedActions.push('update');
  }
  if ([...projectActions.values()].some((actions) => actions.includes('delete'))) {
    allowedActions.push('delete');
  }
  return projectListSnapshotV2(payload, scope, {
    allowedActions: Object.freeze(allowedActions),
    projectActions,
  });
}

export function projectDesktopTenantProjectsLocalSnapshotV2(
  payload: unknown,
  scope: TenantProjectsScope,
): TenantProjectsListSnapshot {
  return projectListSnapshotV2(payload, scope, null);
}

export function projectDesktopTenantProjectRecordV2(
  payload: unknown,
  scope: TenantProjectsScope,
  allowedActions: readonly TenantProjectsAction[] = Object.freeze([]),
  reason = `${scope.authority}_tenant_projects_contract_invalid`,
): TenantProjectRecord {
  if (
    !isRecordV2(payload) ||
    !isNonemptyV2(payload.id) ||
    payload.tenant_id !== scope.tenantId ||
    !isNonemptyV2(payload.name) ||
    !isOptionalNullableStringV2(payload.description) ||
    !isNonemptyV2(payload.owner_id) ||
    !isStringArrayV2(payload.member_ids) ||
    typeof payload.is_public !== 'boolean' ||
    !isNonemptyV2(payload.created_at) ||
    !isOptionalNullableStringV2(payload.updated_at) ||
    !isOptionalNullableRecordV2(payload.stats) ||
    !isOrderedActionSubsetV2(allowedActions)
  ) {
    throw tenantProjectsContractErrorV2(reason);
  }
  return Object.freeze({
    id: payload.id,
    tenantId: scope.tenantId,
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

export function desktopTenantProjectsListPathV2(
  config: DesktopRuntimeConfig,
  scope: TenantProjectsScope,
  query?: TenantProjectsListQuery,
): string {
  const params = new URLSearchParams({
    tenant_id: scope.tenantId,
    page: String(query?.page ?? 1),
    page_size: String(query?.pageSize ?? 20),
  });
  if (query?.search) params.set('search', query.search);
  if (query?.visibility && query.visibility !== 'all') {
    params.set('visibility', query.visibility);
  }
  if (query?.ownerId) params.set('owner_id', query.ownerId);
  return `${desktopTenantProjectsCollectionPathV2(config)}?${params}`;
}

export function desktopTenantProjectsCollectionPathV2(config: DesktopRuntimeConfig): string {
  return config.mode === 'local' ? '/api/v1/tenant-projects' : '/api/v1/projects/';
}

export function desktopTenantProjectPathV2(
  config: DesktopRuntimeConfig,
  projectId: string,
): string {
  const root = config.mode === 'local' ? '/api/v1/tenant-projects' : '/api/v1/projects';
  return `${root}/${encodeURIComponent(projectId)}`;
}

export function desktopTenantProjectDeletePathV2(
  config: DesktopRuntimeConfig,
  projectId: string,
): string {
  const path = desktopTenantProjectPathV2(config, projectId);
  return config.mode === 'local' ? `${path}/archive` : path;
}

export function desktopTenantProjectMutationBodyV2(
  scope: TenantProjectsScope,
  input: TenantProjectsMutationInput,
  includeTenant: boolean,
): Readonly<Record<string, unknown>> {
  return Object.freeze({
    ...(includeTenant ? { tenant_id: scope.tenantId } : {}),
    name: input.name,
    description: input.description,
    ...(input.isPublic === undefined ? {} : { is_public: input.isPublic }),
  });
}

export function tenantProjectsContractErrorV2(reason: string): DesktopApiError {
  return new DesktopApiError(reason, 0, { reason_code: reason });
}

type CloudAuthorityV2 = Readonly<{
  allowedActions: readonly TenantProjectsAction[];
  projectActions: ReadonlyMap<string, readonly TenantProjectsAction[]>;
}>;

function projectListSnapshotV2(
  payload: unknown,
  scope: TenantProjectsScope,
  cloudAuthority: CloudAuthorityV2 | null,
): TenantProjectsListSnapshot {
  const reason = `${scope.authority}_tenant_projects_contract_invalid`;
  if (
    !isRecordV2(payload) ||
    !Array.isArray(payload.projects) ||
    !isNonnegativeIntegerV2(payload.total) ||
    !isPositiveIntegerV2(payload.page) ||
    !isPositiveIntegerV2(payload.page_size)
  ) {
    throw tenantProjectsContractErrorV2(reason);
  }
  if (scope.authority === 'cloud') {
    if (cloudAuthority === null) throw tenantProjectsContractErrorV2(reason);
    return Object.freeze({
      scope: Object.freeze({ ...scope }),
      authority: 'cloud',
      availability: 'available',
      reasonCode: null,
      serviceVersion: SERVICE_VERSION_V2,
      contractVersion: CONTRACT_VERSION_V2,
      allowedActions: cloudAuthority.allowedActions,
      authorityRevision: null,
      projects: Object.freeze(
        payload.projects.map((project) => {
          const projectId = isRecordV2(project) && isNonemptyV2(project.id) ? project.id : '';
          const actions = cloudAuthority.projectActions.get(projectId);
          if (actions === undefined) throw tenantProjectsContractErrorV2(reason);
          return projectDesktopTenantProjectRecordV2(project, scope, actions, reason);
        }),
      ),
      total: payload.total,
      page: payload.page,
      pageSize: payload.page_size,
      ownerIds: Object.freeze(optionalStringArrayV2(payload.owner_ids, reason)),
    });
  }
  if (
    !isAvailabilityV2(payload.availability) ||
    !isNullableReasonV2(payload.reason_code) ||
    !isNonemptyV2(payload.service_version) ||
    !isNonemptyV2(payload.contract_version) ||
    !isOrderedActionSubsetV2(payload.allowed_actions) ||
    !isNonnegativeIntegerV2(payload.authority_revision) ||
    !isRecordV2(payload.scope) ||
    payload.scope.tenant_id !== scope.tenantId ||
    payload.scope.project_id !== null ||
    payload.scope.workspace_id !== null ||
    payload.scope.instance_id !== null
  ) {
    throw tenantProjectsContractErrorV2(reason);
  }
  const allowedActions = Object.freeze([...payload.allowed_actions]);
  if (
    payload.availability === 'unavailable' &&
    (allowedActions.length !== 0 || payload.projects.length !== 0)
  ) {
    throw tenantProjectsContractErrorV2(reason);
  }
  const recordActions = Object.freeze(
    allowedActions.filter(
      (action) => action === 'view' || action === 'update' || action === 'delete',
    ),
  );
  return Object.freeze({
    scope: Object.freeze({ ...scope }),
    authority: 'local',
    availability: payload.availability,
    reasonCode: payload.reason_code,
    serviceVersion: payload.service_version,
    contractVersion: payload.contract_version,
    allowedActions,
    authorityRevision: payload.authority_revision,
    projects: Object.freeze(
      payload.projects.map((project) =>
        projectDesktopTenantProjectRecordV2(project, scope, recordActions, reason),
      ),
    ),
    total: payload.total,
    page: payload.page,
    pageSize: payload.page_size,
    ownerIds: Object.freeze(optionalStringArrayV2(payload.owner_ids, reason)),
  });
}

function cloudAuthorityUserIdV2(payload: unknown, reason: string): string {
  if (!isRecordV2(payload) || !isNonemptyV2(payload.user_id)) {
    throw tenantProjectsContractErrorV2(reason);
  }
  return payload.user_id;
}

function cloudAuthorityTenantRoleV2(
  payload: unknown,
  scope: TenantProjectsScope,
  reason: string,
): string {
  if (
    !isRecordV2(payload) ||
    !isRecordV2(payload.context) ||
    payload.context.tenant_id !== scope.tenantId ||
    !isNonemptyV2(payload.membership_role)
  ) {
    throw tenantProjectsContractErrorV2(reason);
  }
  return payload.membership_role;
}

function cloudProjectActionsV2(
  payload: unknown,
  userId: string,
  reason: string,
): readonly TenantProjectsAction[] {
  if (!isRecordV2(payload) || !Array.isArray(payload.members)) {
    throw tenantProjectsContractErrorV2(reason);
  }
  const membership = payload.members.find(
    (member) => isRecordV2(member) && member.user_id === userId,
  );
  if (!isRecordV2(membership) || !isNonemptyV2(membership.role)) {
    throw tenantProjectsContractErrorV2(reason);
  }
  const actions = [...PROJECT_VIEW_ACTIONS_V2];
  if (membership.role === 'owner' || membership.role === 'admin') actions.push('update');
  if (membership.role === 'owner') actions.push('delete');
  return Object.freeze(actions);
}

function optionalStringArrayV2(value: unknown, reason: string): string[] {
  if (value === undefined) return [];
  if (!isStringArrayV2(value)) throw tenantProjectsContractErrorV2(reason);
  return [...value];
}

function isOrderedActionSubsetV2(value: unknown): value is TenantProjectsAction[] {
  if (!Array.isArray(value)) return false;
  let lastIndex = -1;
  for (const action of value) {
    const index = ACTION_ORDER_V2.indexOf(action as TenantProjectsAction);
    if (index <= lastIndex) return false;
    lastIndex = index;
  }
  return true;
}

function isAvailabilityV2(
  value: unknown,
): value is TenantProjectsListSnapshot['availability'] {
  return (
    value === 'available' ||
    value === 'degraded' ||
    value === 'unavailable' ||
    value === 'not_applicable'
  );
}

function isNullableReasonV2(value: unknown): value is string | null {
  return value === null || isNonemptyV2(value);
}

function isOptionalNullableStringV2(
  value: unknown,
): value is string | null | undefined {
  return value === undefined || value === null || typeof value === 'string';
}

function isOptionalNullableRecordV2(
  value: unknown,
): value is Record<string, unknown> | null | undefined {
  return value === undefined || value === null || isRecordV2(value);
}

function isStringArrayV2(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonemptyV2);
}

function isNonemptyV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isPositiveIntegerV2(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) > 0;
}

function isNonnegativeIntegerV2(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
