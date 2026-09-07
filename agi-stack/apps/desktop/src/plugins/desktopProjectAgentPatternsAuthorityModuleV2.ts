import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type { ProjectAgentScope } from '../features/project-agent/projectAgentClient';
import type {
  ProjectAgentPatternsClient,
  ProjectAgentPatternsSnapshot,
} from '../features/project-agent/projectAgentPatternsClient';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopProjectAgentPatternsHttpAuthorityV2 } from './desktopProjectAgentPatternsHttpProjectionV2';
import {
  prepareDesktopProjectAgentPatternsOperationV2,
  requireDesktopProjectAgentPatternsSnapshotV2,
  type DesktopProjectAgentPatternsOperationInputV2,
  type PreparedDesktopProjectAgentPatternsOperationV2,
} from './desktopProjectAgentPatternsOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type { DesktopProjectAgentPatternsOperationInputV2 } from './desktopProjectAgentPatternsOperationContractV2';

export const DESKTOP_PROJECT_AGENT_PATTERNS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-agent-patterns-authority';
export const DESKTOP_PROJECT_AGENT_PATTERNS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-agent-patterns-authority';
export const DESKTOP_PROJECT_AGENT_PATTERNS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectAgentPatternsAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<ProjectAgentPatternsSnapshot>;
}

export interface DesktopProjectAgentPatternsAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectAgentScope,
  ) => DesktopProjectAgentPatternsAuthorityV2;
}

export interface DesktopProjectAgentPatternsOperationsV2 {
  readonly loadProjectAgentPatterns: (
    input: DesktopProjectAgentPatternsOperationInputV2,
  ) => Promise<ProjectAgentPatternsSnapshot>;
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

export class DesktopProjectAgentPatternsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectAgentPatternsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectAgentPatternsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_agent_patterns_authority_config_invalid',
      'desktop project agent patterns authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopProjectAgentPatternsAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectAgentPatternsHttpAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_AGENT_PATTERNS_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectAgentPatternsAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_AGENT_PATTERNS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectAgentPatternsAuthorityV2,
});

export function createDesktopProjectAgentPatternsOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectAgentPatternsOperationsV2 {
  return Object.freeze({
    loadProjectAgentPatterns(input: DesktopProjectAgentPatternsOperationInputV2) {
      const prepared = prepareDesktopProjectAgentPatternsOperationV2(input);
      return runDesktopProjectAgentPatternsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal),
      );
    },
  });
}

export function createDesktopProjectAgentPatternsClientV2(
  operations: Pick<DesktopProjectAgentPatternsOperationsV2, 'loadProjectAgentPatterns'>,
  config: DesktopRuntimeConfig,
): ProjectAgentPatternsClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    load(scope, options) {
      return operations.loadProjectAgentPatterns({
        config: operationConfig,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopProjectAgentPatternsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectAgentPatternsOperationInputV2,
  operation: (authority: DesktopProjectAgentPatternsAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopProjectAgentPatternsAuthorityOperationV2(
    actions,
    prepareDesktopProjectAgentPatternsOperationV2(input),
    operation,
  );
}

async function runDesktopProjectAgentPatternsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectAgentPatternsOperationV2,
  operation: (authority: DesktopProjectAgentPatternsAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectAgentPatternsAuthorityServiceV2>({
      service: DESKTOP_PROJECT_AGENT_PATTERNS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_AGENT_PATTERNS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectAgentPatternsAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectAgentPatternsServiceV2(candidate);
      const authority = requireProjectAgentPatternsAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableProjectAgentPatternsAuthorityV2(
          authority,
          prepared.scope,
          () => operationActive,
        ),
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

function createRevocableProjectAgentPatternsAuthorityV2(
  authority: DesktopProjectAgentPatternsAuthorityV2,
  scope: ProjectAgentScope,
  isOperationActive: () => boolean,
): DesktopProjectAgentPatternsAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.load(signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopProjectAgentPatternsSnapshotV2(result, scope);
    },
  });
}

function requireProjectAgentPatternsServiceV2(
  value: unknown,
): DesktopProjectAgentPatternsAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectAgentPatternsAuthorityServiceV2;
}

function requireProjectAgentPatternsAuthorityV2(
  value: unknown,
): DesktopProjectAgentPatternsAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.load !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectAgentPatternsAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectAgentPatternsAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_project_agent_patterns_operation_released',
    'desktop project agent patterns operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_agent_patterns_service_invalid',
    'desktop project agent patterns authority service is invalid',
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
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_AGENT_PATTERNS_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_agent_patterns_authority_catalog_missing',
      'desktop project agent patterns authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
