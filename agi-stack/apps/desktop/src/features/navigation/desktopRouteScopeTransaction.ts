import type {
  DesktopRuntimeConfig,
  ProjectSummary,
  WorkspaceContextResponse,
  WorkspaceContextSnapshot,
  WorkspaceContextSwitchOutcome,
} from '../../types';
import {
  isSameDesktopRequestScope,
  workspaceContextMatchesSelection,
} from '../auth/authContextModel';
import type { DesktopRouteContext } from './desktopRouteRegistry';

export type DesktopRouteScopeTransactionReasonCode =
  | 'desktop_route_scope_context_invalid'
  | 'desktop_route_scope_project_required'
  | 'desktop_route_scope_workspace_unsupported'
  | 'desktop_route_scope_project_unavailable'
  | 'desktop_route_scope_authority_invalid'
  | 'desktop_route_scope_authority_mismatch'
  | 'desktop_route_scope_transaction_stale';

export class DesktopRouteScopeTransactionError extends Error {
  readonly reasonCode: DesktopRouteScopeTransactionReasonCode;

  constructor(reasonCode: DesktopRouteScopeTransactionReasonCode) {
    super(reasonCode);
    this.name = 'DesktopRouteScopeTransactionError';
    this.reasonCode = reasonCode;
  }
}

export type DesktopRouteScopeCurrent = Readonly<{
  config: DesktopRuntimeConfig;
  authRevision: number;
}>;

export type DesktopRouteScopeAuthority = Readonly<{
  listProjects: (
    tenantId: string,
    signal: AbortSignal,
  ) => Promise<ProjectSummary[]>;
  getWorkspaceContext: (
    signal: AbortSignal,
  ) => Promise<WorkspaceContextResponse>;
  switchWorkspaceContext: (
    tenantId: string,
    projectId: string,
    expectedRevision: number,
    idempotencyKey: string,
    signal: AbortSignal,
  ) => Promise<WorkspaceContextSwitchOutcome>;
}>;

export type DesktopRouteScopeCommit = Readonly<{
  config: DesktopRuntimeConfig;
  context: WorkspaceContextSnapshot;
  projects: readonly ProjectSummary[];
}>;

export type DesktopRouteScopeTransactionPorts = Readonly<{
  getCurrent: () => DesktopRouteScopeCurrent;
  createAuthority: (config: DesktopRuntimeConfig) => DesktopRouteScopeAuthority;
  commit: (value: DesktopRouteScopeCommit) => void;
  refresh: (
    value: DesktopRouteScopeCommit,
    signal: AbortSignal,
  ) => void | Promise<void>;
}>;

export type DesktopRouteScopeTransactionResult =
  | Readonly<{
      status: 'unchanged';
      config: DesktopRuntimeConfig;
    }>
  | Readonly<{
      status: 'applied';
      config: DesktopRuntimeConfig;
      context: WorkspaceContextSnapshot;
      projects: readonly ProjectSummary[];
    }>;

export type DesktopRouteScopeTransaction = Readonly<{
  switchScope: (
    context: DesktopRouteContext,
    signal: AbortSignal,
  ) => Promise<DesktopRouteScopeTransactionResult>;
}>;

export function resolveDesktopRouteTargetConfig(
  current: DesktopRuntimeConfig,
  context: DesktopRouteContext,
): DesktopRuntimeConfig {
  assertRouteContext(context);
  const tenantId = context.tenantId ?? current.tenantId;
  const tenantChanged = tenantId !== current.tenantId;
  const projectId = context.projectId ?? (tenantChanged ? '' : current.projectId);
  const projectChanged = projectId !== current.projectId;
  const workspaceId =
    context.workspaceId ?? (tenantChanged || projectChanged ? '' : current.workspaceId);

  return Object.freeze({
    ...current,
    tenantId,
    projectId,
    workspaceId,
  });
}

export function createDesktopRouteScopeTransaction(
  ports: DesktopRouteScopeTransactionPorts,
): DesktopRouteScopeTransaction {
  let latestRevision = 0;

  const switchScope = async (
    context: DesktopRouteContext,
    signal: AbortSignal,
  ): Promise<DesktopRouteScopeTransactionResult> => {
    const revision = ++latestRevision;
    throwIfAborted(signal);
    const captured = snapshotCurrent(ports.getCurrent());
    const targetConfig = resolveDesktopRouteTargetConfig(captured.config, context);

    if (isSameDesktopRequestScope(captured.config, targetConfig)) {
      return Object.freeze({
        status: 'unchanged',
        config: targetConfig,
      });
    }
    assertSupportedTarget(captured.config, targetConfig, context);
    assertCurrent(ports, captured, revision, latestRevision, signal);

    const authorityConfig = Object.freeze({
      ...captured.config,
      tenantId: targetConfig.tenantId,
      projectId: '',
      workspaceId: '',
    });
    const authority = ports.createAuthority(authorityConfig);

    assertCurrent(ports, captured, revision, latestRevision, signal);
    const listedProjects = await authority.listProjects(targetConfig.tenantId, signal);
    assertCurrent(ports, captured, revision, latestRevision, signal);
    const scopedProjects = requireTargetProject(
      listedProjects,
      targetConfig.tenantId,
      targetConfig.projectId,
    );

    assertCurrent(ports, captured, revision, latestRevision, signal);
    const currentResponse = await authority.getWorkspaceContext(signal);
    assertCurrent(ports, captured, revision, latestRevision, signal);
    const currentContext = requireAuthorityContext(currentResponse);

    let nextContext = currentContext;
    if (
      !workspaceContextMatchesSelection(
        currentContext,
        targetConfig.tenantId,
        targetConfig.projectId,
      )
    ) {
      assertCurrent(ports, captured, revision, latestRevision, signal);
      const switchResponse = await authority.switchWorkspaceContext(
        targetConfig.tenantId,
        targetConfig.projectId,
        currentContext.revision,
        globalThis.crypto.randomUUID(),
        signal,
      );
      assertCurrent(ports, captured, revision, latestRevision, signal);
      nextContext = requireAuthorityContext(switchResponse);
      if (nextContext.revision < currentContext.revision) {
        throw transactionError('desktop_route_scope_authority_invalid');
      }
    }

    if (
      !workspaceContextMatchesSelection(
        nextContext,
        targetConfig.tenantId,
        targetConfig.projectId,
      )
    ) {
      throw transactionError('desktop_route_scope_authority_mismatch');
    }
    assertCurrent(ports, captured, revision, latestRevision, signal);

    const value = freezeCommit({
      config: targetConfig,
      context: nextContext,
      projects: scopedProjects,
    });
    ports.commit(value);
    await ports.refresh(value, signal);
    return Object.freeze({
      status: 'applied',
      config: value.config,
      context: value.context,
      projects: value.projects,
    });
  };

  return Object.freeze({ switchScope });
}

function snapshotCurrent(current: DesktopRouteScopeCurrent): DesktopRouteScopeCurrent {
  if (!Number.isSafeInteger(current.authRevision) || current.authRevision < 0) {
    throw transactionError('desktop_route_scope_context_invalid');
  }
  return Object.freeze({
    config: Object.freeze({ ...current.config }),
    authRevision: current.authRevision,
  });
}

function assertRouteContext(context: DesktopRouteContext): void {
  for (const value of [
    context.tenantId,
    context.projectId,
    context.workspaceId,
    context.instanceId,
  ]) {
    if (value !== undefined && !isExactIdentifier(value)) {
      throw transactionError('desktop_route_scope_context_invalid');
    }
  }
}

function assertSupportedTarget(
  current: DesktopRuntimeConfig,
  target: DesktopRuntimeConfig,
  context: DesktopRouteContext,
): void {
  if (!isExactIdentifier(target.tenantId) || !isExactIdentifier(target.projectId)) {
    throw transactionError('desktop_route_scope_project_required');
  }
  if (
    context.workspaceId !== undefined &&
    (target.tenantId !== current.tenantId ||
      target.projectId !== current.projectId ||
      target.workspaceId !== current.workspaceId)
  ) {
    throw transactionError('desktop_route_scope_workspace_unsupported');
  }
}

function assertCurrent(
  ports: DesktopRouteScopeTransactionPorts,
  captured: DesktopRouteScopeCurrent,
  revision: number,
  latestRevision: number,
  signal: AbortSignal,
): void {
  throwIfAborted(signal);
  const current = ports.getCurrent();
  if (
    revision !== latestRevision ||
    current.authRevision !== captured.authRevision ||
    !isSameDesktopRequestScope(current.config, captured.config)
  ) {
    throw transactionError('desktop_route_scope_transaction_stale');
  }
}

function requireTargetProject(
  projects: readonly ProjectSummary[],
  tenantId: string,
  projectId: string,
): readonly ProjectSummary[] {
  if (!Array.isArray(projects)) {
    throw transactionError('desktop_route_scope_authority_invalid');
  }
  const scopedProjects = projects.filter((project) => project.tenant_id === tenantId);
  if (
    !scopedProjects.some(
      (project) => project.id === projectId && project.tenant_id === tenantId,
    )
  ) {
    throw transactionError('desktop_route_scope_project_unavailable');
  }
  return Object.freeze(scopedProjects.map((project) => Object.freeze({ ...project })));
}

function requireAuthorityContext(
  response: WorkspaceContextResponse | WorkspaceContextSwitchOutcome,
): WorkspaceContextSnapshot {
  if (!isRecord(response) || !isRecord(response.context)) {
    throw transactionError('desktop_route_scope_authority_invalid');
  }
  const context = response.context;
  if (
    !isExactIdentifier(context.tenant_id) ||
    !isExactIdentifier(context.project_id) ||
    !Number.isSafeInteger(context.revision) ||
    context.revision < 0 ||
    typeof context.updated_at !== 'string'
  ) {
    throw transactionError('desktop_route_scope_authority_invalid');
  }
  return Object.freeze({
    tenant_id: context.tenant_id,
    project_id: context.project_id,
    revision: context.revision,
    updated_at: context.updated_at,
  });
}

function freezeCommit(value: DesktopRouteScopeCommit): DesktopRouteScopeCommit {
  return Object.freeze({
    config: Object.freeze({ ...value.config }),
    context: Object.freeze({ ...value.context }),
    projects: Object.freeze(value.projects.map((project) => Object.freeze({ ...project }))),
  });
}

function throwIfAborted(signal: AbortSignal): void {
  if (!signal.aborted) return;
  throw signal.reason ?? new DOMException('Aborted', 'AbortError');
}

function isExactIdentifier(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.trim() === value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function transactionError(
  reasonCode: DesktopRouteScopeTransactionReasonCode,
): DesktopRouteScopeTransactionError {
  return new DesktopRouteScopeTransactionError(reasonCode);
}
