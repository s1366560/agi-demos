import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type { DesktopRuntimeConfig, PlanSnapshot, WorkspaceTask } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/workspace-execution-snapshot-authority';
export const DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.workspace-execution-snapshot-authority';
export const DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopWorkspaceExecutionSnapshotIdentityV2 = Readonly<{
  tenant_id: string;
  project_id: string;
  workspace_id: string;
}>;

export type DesktopWorkspaceExecutionSnapshotOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  signal?: AbortSignal;
}>;

export interface DesktopWorkspaceExecutionSnapshotAuthorityV2 {
  readonly listTasks: (
    identity: DesktopWorkspaceExecutionSnapshotIdentityV2,
    signal?: AbortSignal
  ) => Promise<WorkspaceTask[]>;
  readonly getPlanSnapshot: (
    identity: DesktopWorkspaceExecutionSnapshotIdentityV2,
    signal?: AbortSignal
  ) => Promise<PlanSnapshot>;
}

export interface DesktopWorkspaceExecutionSnapshotAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig
  ) => DesktopWorkspaceExecutionSnapshotAuthorityV2;
}

export interface DesktopWorkspaceExecutionSnapshotOperationsV2 {
  readonly listTasks: (
    input: DesktopWorkspaceExecutionSnapshotOperationInputV2
  ) => Promise<WorkspaceTask[]>;
  readonly getPlanSnapshot: (
    input: DesktopWorkspaceExecutionSnapshotOperationInputV2
  ) => Promise<PlanSnapshot>;
}

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;

type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;

type AuthorityAdmissionRejectionV2 = ServiceAdmissionRejectionV2 | GenerationActionsUnavailableV2;

type PreparedWorkspaceExecutionSnapshotOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  identity: DesktopWorkspaceExecutionSnapshotIdentityV2;
  signal?: AbortSignal;
}>;

export class DesktopWorkspaceExecutionSnapshotAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopWorkspaceExecutionSnapshotAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopWorkspaceExecutionSnapshotAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_workspace_execution_snapshot_authority_config_invalid',
      'desktop workspace execution snapshot authority requires desktop-api-client strategy'
    );
  }
  const service: DesktopWorkspaceExecutionSnapshotAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopWorkspaceExecutionSnapshotAuthorityV2,
  });
  context.provide(DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_SERVICE_V2, service);
}

export const desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopWorkspaceExecutionSnapshotAuthorityV2,
  });

export function createDesktopWorkspaceExecutionSnapshotOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null
): DesktopWorkspaceExecutionSnapshotOperationsV2 {
  return Object.freeze({
    listTasks(input: DesktopWorkspaceExecutionSnapshotOperationInputV2) {
      const prepared = prepareWorkspaceExecutionSnapshotOperationV2(input);
      return runDesktopWorkspaceExecutionSnapshotAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.listTasks(prepared.identity, prepared.signal)
      );
    },
    getPlanSnapshot(input: DesktopWorkspaceExecutionSnapshotOperationInputV2) {
      const prepared = prepareWorkspaceExecutionSnapshotOperationV2(input);
      return runDesktopWorkspaceExecutionSnapshotAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.getPlanSnapshot(prepared.identity, prepared.signal)
      );
    },
  });
}

export function withDesktopWorkspaceExecutionSnapshotAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopWorkspaceExecutionSnapshotOperationInputV2,
  operation: (
    authority: DesktopWorkspaceExecutionSnapshotAuthorityV2,
    prepared: PreparedWorkspaceExecutionSnapshotOperationV2
  ) => TResult | Promise<TResult>
): Promise<TResult> {
  return runDesktopWorkspaceExecutionSnapshotAuthorityOperationV2(
    actions,
    prepareWorkspaceExecutionSnapshotOperationV2(input),
    operation
  );
}

async function runDesktopWorkspaceExecutionSnapshotAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedWorkspaceExecutionSnapshotOperationV2,
  operation: (
    authority: DesktopWorkspaceExecutionSnapshotAuthorityV2,
    prepared: PreparedWorkspaceExecutionSnapshotOperationV2
  ) => TResult | Promise<TResult>
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopWorkspaceExecutionSnapshotAuthorityServiceV2>(
      {
        service: DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: 'project',
          tenant_id: prepared.identity.tenant_id,
          project_id: prepared.identity.project_id,
        }),
      }
    );
  if (admission.status === 'rejected') {
    throw new DesktopWorkspaceExecutionSnapshotAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireWorkspaceExecutionSnapshotServiceV2(candidate);
      const authority = requireWorkspaceExecutionSnapshotAuthorityV2(
        service.bindOperation(prepared.config)
      );
      return operation(
        createRevocableDesktopWorkspaceExecutionSnapshotAuthorityV2(
          authority,
          () => operationActive
        ),
        prepared
      );
    });
  } catch (error) {
    operationFailed = true;
    throw error;
  } finally {
    operationActive = false;
    try {
      await admission.release();
    } catch (releaseError) {
      if (!operationFailed) throw releaseError;
    }
  }
}

function createDesktopWorkspaceExecutionSnapshotAuthorityV2(
  config: DesktopRuntimeConfig
): DesktopWorkspaceExecutionSnapshotAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  return Object.freeze({
    listTasks(identity: DesktopWorkspaceExecutionSnapshotIdentityV2, signal?: AbortSignal) {
      const operationIdentity = prepareTransportIdentityV2(operationConfig, identity, signal);
      return createTransportV2(operationConfig, operationIdentity)
        .listTasks(signal)
        .then((tasks) => assertTaskResponseScopeV2(tasks, operationIdentity));
    },
    getPlanSnapshot(identity: DesktopWorkspaceExecutionSnapshotIdentityV2, signal?: AbortSignal) {
      const operationIdentity = prepareTransportIdentityV2(operationConfig, identity, signal);
      return createTransportV2(operationConfig, operationIdentity)
        .getPlanSnapshot(signal)
        .then((plan) => assertPlanResponseScopeV2(plan, operationIdentity));
    },
  });
}

function createTransportV2(
  config: DesktopRuntimeConfig,
  identity: DesktopWorkspaceExecutionSnapshotIdentityV2
): DesktopApiClient {
  assertWorkspaceExecutionSnapshotScopeV2(config, identity);
  return new DesktopApiClient(
    Object.freeze({
      ...config,
      tenantId: identity.tenant_id,
      projectId: identity.project_id,
      workspaceId: identity.workspace_id,
    })
  );
}

function createRevocableDesktopWorkspaceExecutionSnapshotAuthorityV2(
  authority: DesktopWorkspaceExecutionSnapshotAuthorityV2,
  isOperationActive: () => boolean
): DesktopWorkspaceExecutionSnapshotAuthorityV2 {
  const requireActive = () => {
    if (!isOperationActive()) {
      throw new RuntimeV2Error(
        'desktop_workspace_execution_snapshot_operation_released',
        'desktop workspace execution snapshot operation has been released'
      );
    }
  };
  return Object.freeze({
    listTasks(identity: DesktopWorkspaceExecutionSnapshotIdentityV2, signal?: AbortSignal) {
      requireActive();
      return authority.listTasks(identity, signal);
    },
    getPlanSnapshot(identity: DesktopWorkspaceExecutionSnapshotIdentityV2, signal?: AbortSignal) {
      requireActive();
      return authority.getPlanSnapshot(identity, signal);
    },
  });
}

function prepareWorkspaceExecutionSnapshotOperationV2(
  input: DesktopWorkspaceExecutionSnapshotOperationInputV2
): PreparedWorkspaceExecutionSnapshotOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidWorkspaceExecutionSnapshotInputV2();
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const identity = cloneWorkspaceExecutionSnapshotIdentityV2({
    tenant_id: config.tenantId,
    project_id: config.projectId,
    workspace_id: config.workspaceId,
  });
  assertWorkspaceExecutionSnapshotScopeV2(config, identity);
  if (input.signal !== undefined && !isAbortSignalV2(input.signal)) {
    throw invalidWorkspaceExecutionSnapshotInputV2();
  }
  return Object.freeze({
    config,
    identity,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function prepareTransportIdentityV2(
  config: DesktopRuntimeConfig,
  identity: DesktopWorkspaceExecutionSnapshotIdentityV2,
  signal?: AbortSignal
): DesktopWorkspaceExecutionSnapshotIdentityV2 {
  const operationIdentity = cloneWorkspaceExecutionSnapshotIdentityV2(identity);
  if (signal !== undefined && !isAbortSignalV2(signal)) {
    throw invalidWorkspaceExecutionSnapshotInputV2();
  }
  assertWorkspaceExecutionSnapshotScopeV2(config, operationIdentity);
  return operationIdentity;
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidWorkspaceExecutionSnapshotInputV2();
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !isCanonicalStringV2(copy.tenantId) ||
    !isCanonicalStringV2(copy.projectId) ||
    !isCanonicalStringV2(copy.workspaceId)
  ) {
    throw invalidWorkspaceExecutionSnapshotInputV2();
  }
  return Object.freeze(copy);
}

function cloneWorkspaceExecutionSnapshotIdentityV2(
  identity: DesktopWorkspaceExecutionSnapshotIdentityV2
): DesktopWorkspaceExecutionSnapshotIdentityV2 {
  if (
    !isPlainRecordV2(identity) ||
    !isCanonicalStringV2(identity.tenant_id) ||
    !isCanonicalStringV2(identity.project_id) ||
    !isCanonicalStringV2(identity.workspace_id)
  ) {
    throw invalidWorkspaceExecutionSnapshotInputV2();
  }
  return Object.freeze({
    tenant_id: identity.tenant_id,
    project_id: identity.project_id,
    workspace_id: identity.workspace_id,
  });
}

function assertWorkspaceExecutionSnapshotScopeV2(
  config: DesktopRuntimeConfig,
  identity: DesktopWorkspaceExecutionSnapshotIdentityV2
): void {
  if (
    config.tenantId !== identity.tenant_id ||
    config.projectId !== identity.project_id ||
    config.workspaceId !== identity.workspace_id
  ) {
    throw new RuntimeV2Error(
      'desktop_workspace_execution_snapshot_scope_mismatch',
      'desktop workspace execution snapshot scope differs from the operation identity'
    );
  }
}

function assertTaskResponseScopeV2(
  tasks: WorkspaceTask[],
  identity: DesktopWorkspaceExecutionSnapshotIdentityV2
): WorkspaceTask[] {
  for (const task of tasks) {
    if (
      !isPlainRecordV2(task) ||
      (task.workspace_id !== undefined && task.workspace_id !== identity.workspace_id)
    ) {
      throw responseScopeMismatchV2();
    }
  }
  return tasks;
}

function assertPlanResponseScopeV2(
  plan: PlanSnapshot,
  identity: DesktopWorkspaceExecutionSnapshotIdentityV2
): PlanSnapshot {
  if (
    !isPlainRecordV2(plan) ||
    (plan.workspace_id !== undefined && plan.workspace_id !== identity.workspace_id) ||
    (plan.project_id !== undefined && plan.project_id !== identity.project_id)
  ) {
    throw responseScopeMismatchV2();
  }
  return plan;
}

function requireWorkspaceExecutionSnapshotServiceV2(
  value: unknown
): DesktopWorkspaceExecutionSnapshotAuthorityServiceV2 {
  if (!isPlainRecordV2(value) || typeof value.bindOperation !== 'function') {
    throw invalidWorkspaceExecutionSnapshotServiceV2();
  }
  return value as unknown as DesktopWorkspaceExecutionSnapshotAuthorityServiceV2;
}

function requireWorkspaceExecutionSnapshotAuthorityV2(
  value: unknown
): DesktopWorkspaceExecutionSnapshotAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    typeof value.listTasks !== 'function' ||
    typeof value.getPlanSnapshot !== 'function'
  ) {
    throw invalidWorkspaceExecutionSnapshotServiceV2();
  }
  return value as unknown as DesktopWorkspaceExecutionSnapshotAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopWorkspaceExecutionSnapshotAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidWorkspaceExecutionSnapshotInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_execution_snapshot_input_invalid',
    'desktop workspace execution snapshot operation input is invalid'
  );
}

function invalidWorkspaceExecutionSnapshotServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_execution_snapshot_service_invalid',
    'desktop workspace execution snapshot service is invalid'
  );
}

function responseScopeMismatchV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_execution_snapshot_response_scope_mismatch',
    'desktop workspace execution snapshot response differs from the operation identity'
  );
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref === DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_MODULE_REF_V2
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_workspace_execution_snapshot_authority_catalog_missing',
      'desktop workspace execution snapshot authority is absent from the generated catalog'
    );
  }
  return entry.contract_digest;
}
