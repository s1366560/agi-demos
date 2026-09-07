import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type { ProjectAgentScope } from '../features/project-agent/projectAgentClient';
import type {
  ProjectAgentLogsClient,
  ProjectAgentLogsSnapshot,
} from '../features/project-agent/projectAgentLogsClient';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopProjectAgentLogsHttpAuthorityV2 } from './desktopProjectAgentLogsHttpProjectionV2';
import {
  prepareDesktopProjectAgentLogsOperationV2,
  requireDesktopProjectAgentLogsSnapshotV2,
  type DesktopProjectAgentLogsOperationInputV2,
  type PreparedDesktopProjectAgentLogsOperationV2,
} from './desktopProjectAgentLogsOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type { DesktopProjectAgentLogsOperationInputV2 } from './desktopProjectAgentLogsOperationContractV2';

export const DESKTOP_PROJECT_AGENT_LOGS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-agent-logs-authority';
export const DESKTOP_PROJECT_AGENT_LOGS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-agent-logs-authority';
export const DESKTOP_PROJECT_AGENT_LOGS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectAgentLogsAuthorityV2 {
  readonly load: (
    status?: string,
    limit?: number,
    signal?: AbortSignal
  ) => Promise<ProjectAgentLogsSnapshot>;
}

export interface DesktopProjectAgentLogsAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectAgentScope
  ) => DesktopProjectAgentLogsAuthorityV2;
}

export interface DesktopProjectAgentLogsOperationsV2 {
  readonly loadProjectAgentLogs: (
    input: DesktopProjectAgentLogsOperationInputV2
  ) => Promise<ProjectAgentLogsSnapshot>;
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

const AUTHORITY_KEYS_V2 = new Set(['load']);

export class DesktopProjectAgentLogsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectAgentLogsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectAgentLogsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_agent_logs_authority_config_invalid',
      'desktop project agent logs authority requires desktop-api-fetch strategy'
    );
  }
  const service: DesktopProjectAgentLogsAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectAgentLogsHttpAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_AGENT_LOGS_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectAgentLogsAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_AGENT_LOGS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectAgentLogsAuthorityV2,
});

export function createDesktopProjectAgentLogsOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null
): DesktopProjectAgentLogsOperationsV2 {
  return Object.freeze({
    loadProjectAgentLogs(input: DesktopProjectAgentLogsOperationInputV2) {
      const prepared = prepareDesktopProjectAgentLogsOperationV2(input);
      return runDesktopProjectAgentLogsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.status, prepared.limit, prepared.signal)
      );
    },
  });
}

export function createDesktopProjectAgentLogsClientV2(
  operations: Pick<DesktopProjectAgentLogsOperationsV2, 'loadProjectAgentLogs'>,
  config: DesktopRuntimeConfig
): ProjectAgentLogsClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    load(scope, options) {
      return operations.loadProjectAgentLogs({
        config: operationConfig,
        scope,
        ...(options?.status === undefined ? {} : { status: options.status }),
        ...(options?.limit === undefined ? {} : { limit: options.limit }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopProjectAgentLogsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectAgentLogsOperationInputV2,
  operation: (authority: DesktopProjectAgentLogsAuthorityV2) => TResult | Promise<TResult>
): Promise<TResult> {
  return runDesktopProjectAgentLogsAuthorityOperationV2(
    actions,
    prepareDesktopProjectAgentLogsOperationV2(input),
    operation
  );
}

async function runDesktopProjectAgentLogsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectAgentLogsOperationV2,
  operation: (authority: DesktopProjectAgentLogsAuthorityV2) => TResult | Promise<TResult>
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectAgentLogsAuthorityServiceV2>({
      service: DESKTOP_PROJECT_AGENT_LOGS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_AGENT_LOGS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectAgentLogsAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectAgentLogsServiceV2(candidate);
      const authority = requireProjectAgentLogsAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope)
      );
      return operation(
        createRevocableProjectAgentLogsAuthorityV2(authority, prepared.scope, () => operationActive)
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

function createRevocableProjectAgentLogsAuthorityV2(
  authority: DesktopProjectAgentLogsAuthorityV2,
  scope: ProjectAgentScope,
  isOperationActive: () => boolean
): DesktopProjectAgentLogsAuthorityV2 {
  return Object.freeze({
    async load(status?: string, limit?: number, signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(status, limit, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectAgentLogsSnapshotV2(result, scope);
    },
  });
}

function requireProjectAgentLogsServiceV2(
  value: unknown
): DesktopProjectAgentLogsAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectAgentLogsAuthorityServiceV2;
}

function requireProjectAgentLogsAuthorityV2(value: unknown): DesktopProjectAgentLogsAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.load !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectAgentLogsAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectAgentLogsAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_project_agent_logs_operation_released',
    'desktop project agent logs operation has been released'
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_agent_logs_service_invalid',
    'desktop project agent logs authority service is invalid'
  );
}

function hasExactKeysV2(value: Record<string, unknown>, expected: ReadonlySet<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_AGENT_LOGS_AUTHORITY_MODULE_REF_V2
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_agent_logs_authority_catalog_missing',
      'desktop project agent logs authority is absent from the generated catalog'
    );
  }
  return entry.contract_digest;
}
