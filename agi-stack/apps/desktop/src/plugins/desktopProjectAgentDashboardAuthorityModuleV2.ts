import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  ProjectAgentDashboardClient,
  ProjectAgentDashboardSnapshot,
} from '../features/project-agent/projectAgentDashboardClient';
import type { ProjectAgentScope } from '../features/project-agent/projectAgentClient';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopProjectAgentDashboardHttpAuthorityV2 } from './desktopProjectAgentDashboardHttpProjectionV2';
import {
  prepareDesktopProjectAgentDashboardOperationV2,
  requireDesktopProjectAgentDashboardSnapshotV2,
  type DesktopProjectAgentDashboardOperationInputV2,
  type PreparedDesktopProjectAgentDashboardOperationV2,
} from './desktopProjectAgentDashboardOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type { DesktopProjectAgentDashboardOperationInputV2 } from './desktopProjectAgentDashboardOperationContractV2';

export const DESKTOP_PROJECT_AGENT_DASHBOARD_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-agent-dashboard-authority';
export const DESKTOP_PROJECT_AGENT_DASHBOARD_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-agent-dashboard-authority';
export const DESKTOP_PROJECT_AGENT_DASHBOARD_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectAgentDashboardAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<ProjectAgentDashboardSnapshot>;
}

export interface DesktopProjectAgentDashboardAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectAgentScope
  ) => DesktopProjectAgentDashboardAuthorityV2;
}

export interface DesktopProjectAgentDashboardOperationsV2 {
  readonly loadProjectAgentDashboard: (
    input: DesktopProjectAgentDashboardOperationInputV2
  ) => Promise<ProjectAgentDashboardSnapshot>;
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

export class DesktopProjectAgentDashboardAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectAgentDashboardAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectAgentDashboardAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_agent_dashboard_authority_config_invalid',
      'desktop project agent dashboard authority requires desktop-api-fetch strategy'
    );
  }
  const service: DesktopProjectAgentDashboardAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectAgentDashboardHttpAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_AGENT_DASHBOARD_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectAgentDashboardAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_AGENT_DASHBOARD_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectAgentDashboardAuthorityV2,
});

export function createDesktopProjectAgentDashboardOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null
): DesktopProjectAgentDashboardOperationsV2 {
  return Object.freeze({
    loadProjectAgentDashboard(input: DesktopProjectAgentDashboardOperationInputV2) {
      const prepared = prepareDesktopProjectAgentDashboardOperationV2(input);
      return runDesktopProjectAgentDashboardAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal)
      );
    },
  });
}

export function createDesktopProjectAgentDashboardClientV2(
  operations: Pick<DesktopProjectAgentDashboardOperationsV2, 'loadProjectAgentDashboard'>,
  config: DesktopRuntimeConfig
): ProjectAgentDashboardClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    load(scope, options) {
      return operations.loadProjectAgentDashboard({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopProjectAgentDashboardAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectAgentDashboardOperationInputV2,
  operation: (authority: DesktopProjectAgentDashboardAuthorityV2) => TResult | Promise<TResult>
): Promise<TResult> {
  return runDesktopProjectAgentDashboardAuthorityOperationV2(
    actions,
    prepareDesktopProjectAgentDashboardOperationV2(input),
    operation
  );
}

async function runDesktopProjectAgentDashboardAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectAgentDashboardOperationV2,
  operation: (authority: DesktopProjectAgentDashboardAuthorityV2) => TResult | Promise<TResult>
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectAgentDashboardAuthorityServiceV2>({
      service: DESKTOP_PROJECT_AGENT_DASHBOARD_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_AGENT_DASHBOARD_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectAgentDashboardAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectAgentDashboardServiceV2(candidate);
      const authority = requireProjectAgentDashboardAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope)
      );
      return operation(
        createRevocableProjectAgentDashboardAuthorityV2(
          authority,
          prepared.scope,
          () => operationActive
        )
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

function createRevocableProjectAgentDashboardAuthorityV2(
  authority: DesktopProjectAgentDashboardAuthorityV2,
  scope: ProjectAgentScope,
  isOperationActive: () => boolean
): DesktopProjectAgentDashboardAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectAgentDashboardSnapshotV2(result, scope);
    },
  });
}

function requireProjectAgentDashboardServiceV2(
  value: unknown
): DesktopProjectAgentDashboardAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectAgentDashboardAuthorityServiceV2;
}

function requireProjectAgentDashboardAuthorityV2(
  value: unknown
): DesktopProjectAgentDashboardAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.load !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectAgentDashboardAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectAgentDashboardAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_project_agent_dashboard_operation_released',
    'desktop project agent dashboard operation has been released'
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_agent_dashboard_service_invalid',
    'desktop project agent dashboard authority service is invalid'
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
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_AGENT_DASHBOARD_AUTHORITY_MODULE_REF_V2
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_agent_dashboard_authority_catalog_missing',
      'desktop project agent dashboard authority is absent from the generated catalog'
    );
  }
  return entry.contract_digest;
}
