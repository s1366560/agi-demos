import type { CurrentUser, WorkspaceContextResponse, WorkspaceMemberSummary } from '../../types';
import type { DesktopRouteContext } from './desktopRouteRegistry';

export const DESKTOP_ROUTE_PERMISSION_CONTRACT_VERSION = '3.0.0';

const SNAPSHOT_KEYS = Object.freeze([
  'contract_version',
  'subject_id',
  'scope',
  'permissions',
  'authority_revision',
  'reason_code',
]);
const SCOPE_KEYS = Object.freeze([
  'tenant_id',
  'project_id',
  'workspace_id',
  'instance_id',
  'conversation_id',
]);
const PERMISSION_ORDER = Object.freeze([
  'authenticated',
  'global_admin',
  'tenant_member',
  'tenant_admin',
  'tenant_owner',
  'project_member',
  'workspace_member',
]);
const GLOBAL_ADMIN_ROLES = new Set(['system_admin']);

export type DesktopRoutePermissionScope = Readonly<{
  tenant_id: string | null;
  project_id: string | null;
  workspace_id: string | null;
  instance_id: string | null;
  conversation_id: string | null;
}>;

export type DesktopRoutePermissionSnapshot = Readonly<{
  contract_version: typeof DESKTOP_ROUTE_PERMISSION_CONTRACT_VERSION;
  subject_id: string;
  scope: DesktopRoutePermissionScope;
  permissions: readonly string[];
  authority_revision: number;
  reason_code: string | null;
}>;

export type DesktopRoutePermissionAuthorityReasonCode =
  | 'desktop_route_permission_snapshot_invalid'
  | 'desktop_route_permission_scope_mismatch'
  | 'desktop_route_permission_revision_stale';

export class DesktopRoutePermissionAuthorityError extends Error {
  readonly reasonCode: DesktopRoutePermissionAuthorityReasonCode;

  constructor(reasonCode: DesktopRoutePermissionAuthorityReasonCode) {
    super(reasonCode);
    this.name = 'DesktopRoutePermissionAuthorityError';
    this.reasonCode = reasonCode;
  }
}

export type DesktopRoutePermissionAuthorityClient = Readonly<{
  getCurrentUser: (signal: AbortSignal) => Promise<CurrentUser>;
  getWorkspaceContext: (signal: AbortSignal) => Promise<WorkspaceContextResponse>;
  listWorkspaceMembers: (
    context: DesktopRouteContext,
    signal: AbortSignal,
  ) => Promise<readonly WorkspaceMemberSummary[]>;
}>;

export type DesktopRoutePermissionResolverOptions = Readonly<{
  client: DesktopRoutePermissionAuthorityClient;
}>;

export type DesktopRoutePermissionSnapshotResolver = (
  context: DesktopRouteContext,
  signal: AbortSignal,
) => Promise<DesktopRoutePermissionSnapshot>;

export function createCloudDesktopRoutePermissionResolver(
  options: DesktopRoutePermissionResolverOptions,
): DesktopRoutePermissionSnapshotResolver {
  return createDesktopRoutePermissionResolver(options);
}

export function createLocalDesktopRoutePermissionResolver(
  options: DesktopRoutePermissionResolverOptions,
): DesktopRoutePermissionSnapshotResolver {
  return createDesktopRoutePermissionResolver(options);
}

export function parseDesktopRoutePermissionSnapshot(
  value: unknown,
): DesktopRoutePermissionSnapshot {
  if (!isExactRecord(value, SNAPSHOT_KEYS)) throw invalidSnapshot();
  if (value.contract_version !== DESKTOP_ROUTE_PERMISSION_CONTRACT_VERSION) {
    throw invalidSnapshot();
  }
  const subjectId = requireIdentifier(value.subject_id);
  const scope = parseScope(value.scope);
  const permissions = parsePermissions(value.permissions);
  const authorityRevision = requireRevision(value.authority_revision);
  const reasonCode = requireNullableReasonCode(value.reason_code);
  return Object.freeze({
    contract_version: DESKTOP_ROUTE_PERMISSION_CONTRACT_VERSION,
    subject_id: subjectId,
    scope,
    permissions,
    authority_revision: authorityRevision,
    reason_code: reasonCode,
  });
}

export function desktopRoutePermissionSnapshotMatchesContext(
  snapshot: DesktopRoutePermissionSnapshot,
  context: DesktopRouteContext,
): boolean {
  return (
    snapshot.scope.tenant_id === (context.tenantId ?? null) &&
    snapshot.scope.project_id === (context.projectId ?? null) &&
    snapshot.scope.workspace_id === (context.workspaceId ?? null) &&
    snapshot.scope.instance_id === (context.instanceId ?? null)
  );
}

function createDesktopRoutePermissionResolver(
  options: DesktopRoutePermissionResolverOptions,
): DesktopRoutePermissionSnapshotResolver {
  return async (context, signal) => {
    throwIfAborted(signal);
    const [rawUser, rawWorkspaceContext] = await Promise.all([
      options.client.getCurrentUser(signal),
      options.client.getWorkspaceContext(signal),
    ]);
    throwIfAborted(signal);
    const user = parseCurrentUser(rawUser);
    const workspaceContext = parseWorkspaceContext(rawWorkspaceContext);
    assertAuthorityScope(context, workspaceContext);

    const permissions = new Set<string>(['authenticated']);
    if (
      user.is_superuser === true ||
      user.global_roles?.some((role) => GLOBAL_ADMIN_ROLES.has(role)) === true
    ) {
      permissions.add('global_admin');
    }
    permissions.add('tenant_member');
    projectTenantPermissions(permissions, workspaceContext.membership_role);
    permissions.add('project_member');

    const activeWorkspaceId = context.workspaceId ?? null;
    if (activeWorkspaceId !== null) {
      const workspaceContext = Object.freeze({
        ...context,
        workspaceId: activeWorkspaceId,
      });
      const members = await options.client.listWorkspaceMembers(workspaceContext, signal);
      throwIfAborted(signal);
      if (
        Array.isArray(members) &&
        members.some(
          (member) =>
            isRecord(member) &&
            member.workspace_id === activeWorkspaceId &&
            member.user_id === user.user_id,
        )
      ) {
        permissions.add('workspace_member');
      }
    }

    return parseDesktopRoutePermissionSnapshot({
      contract_version: DESKTOP_ROUTE_PERMISSION_CONTRACT_VERSION,
      subject_id: user.user_id,
      scope: {
        tenant_id: context.tenantId ?? null,
        project_id: context.projectId ?? null,
        workspace_id: context.workspaceId ?? null,
        instance_id: context.instanceId ?? null,
        conversation_id: null,
      },
      permissions: PERMISSION_ORDER.filter((permission) => permissions.has(permission)),
      authority_revision: workspaceContext.context.revision,
      reason_code: null,
    });
  };
}

function parseCurrentUser(value: unknown): CurrentUser {
  if (!isRecord(value)) throw invalidSnapshot();
  const userId = requireIdentifier(value.user_id);
  if (
    !Array.isArray(value.roles) ||
    !value.roles.every((role) => typeof role === 'string' && requireIdentifier(role))
  ) {
    throw invalidSnapshot();
  }
  if (
    value.global_roles !== undefined &&
    (!Array.isArray(value.global_roles) ||
      !value.global_roles.every((role) => typeof role === 'string' && requireIdentifier(role)))
  ) {
    throw invalidSnapshot();
  }
  if (value.is_superuser !== undefined && typeof value.is_superuser !== 'boolean') {
    throw invalidSnapshot();
  }
  return {
    ...(value as CurrentUser),
    user_id: userId,
    roles: [...value.roles],
    global_roles: Array.isArray(value.global_roles) ? [...value.global_roles] : [],
  };
}

function parseWorkspaceContext(value: unknown): WorkspaceContextResponse {
  if (!isRecord(value) || !isRecord(value.context)) throw invalidSnapshot();
  const context = value.context;
  return {
    context: {
      tenant_id: requireIdentifier(context.tenant_id),
      project_id: requireIdentifier(context.project_id),
      revision: requireRevision(context.revision),
      updated_at: requireIdentifier(context.updated_at),
    },
    membership_role: requireIdentifier(value.membership_role),
  };
}

function assertAuthorityScope(
  context: DesktopRouteContext,
  authority: WorkspaceContextResponse,
): void {
  if (
    (context.tenantId !== undefined && context.tenantId !== authority.context.tenant_id) ||
    (context.projectId !== undefined && context.projectId !== authority.context.project_id)
  ) {
    throw new DesktopRoutePermissionAuthorityError('desktop_route_permission_scope_mismatch');
  }
}

function projectTenantPermissions(permissions: Set<string>, membershipRole: string): void {
  if (membershipRole === 'admin' || membershipRole === 'owner') {
    permissions.add('tenant_admin');
  }
  if (membershipRole === 'owner') permissions.add('tenant_owner');
}

function parseScope(value: unknown): DesktopRoutePermissionScope {
  if (!isExactRecord(value, SCOPE_KEYS)) throw invalidSnapshot();
  return Object.freeze({
    tenant_id: nullableIdentifier(value.tenant_id),
    project_id: nullableIdentifier(value.project_id),
    workspace_id: nullableIdentifier(value.workspace_id),
    instance_id: nullableIdentifier(value.instance_id),
    conversation_id: nullableIdentifier(value.conversation_id),
  });
}

function parsePermissions(value: unknown): readonly string[] {
  if (!Array.isArray(value)) throw invalidSnapshot();
  const permissions = value.map(requireIdentifier);
  if (new Set(permissions).size !== permissions.length) throw invalidSnapshot();
  return Object.freeze(permissions);
}

function requireNullableReasonCode(value: unknown): string | null {
  return value === null ? null : requireIdentifier(value);
}

function nullableIdentifier(value: unknown): string | null {
  return value === null || value === undefined ? null : requireIdentifier(value);
}

function requireIdentifier(value: unknown): string {
  if (typeof value !== 'string' || value.length === 0 || value.trim() !== value) {
    throw invalidSnapshot();
  }
  return value;
}

function requireRevision(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw invalidSnapshot();
  }
  return value as number;
}

function isExactRecord(
  value: unknown,
  expectedKeys: readonly string[],
): value is Record<string, unknown> {
  if (!isRecord(value)) return false;
  const keys = Object.keys(value).sort();
  return (
    keys.length === expectedKeys.length &&
    [...expectedKeys].sort().every((key, index) => key === keys[index])
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function throwIfAborted(signal: AbortSignal): void {
  if (!signal.aborted) return;
  throw signal.reason ?? new DOMException('Aborted', 'AbortError');
}

function invalidSnapshot(): DesktopRoutePermissionAuthorityError {
  return new DesktopRoutePermissionAuthorityError('desktop_route_permission_snapshot_invalid');
}
