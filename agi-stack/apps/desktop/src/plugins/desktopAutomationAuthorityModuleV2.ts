import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import {
  createDesktopAutomationApi,
  type AutomationRunInput,
  type DesktopAutomationApi,
} from '../features/automations/automationClient';
import type {
  AutomationCreateInput,
  AutomationDeleteInput,
  AutomationToggleInput,
  AutomationUpdateInput,
  DesktopRuntimeConfig,
} from '../types';
import {
  assertAutomationCapabilitiesV2,
  assertAutomationDeleteResponseV2,
  assertAutomationJobListV2,
  assertAutomationJobV2,
  assertAutomationRunListV2,
  assertAutomationRunReceiptV2,
  canonicalAutomationIdentifierV2,
  cloneAutomationCreateInputV2,
  cloneAutomationDeleteInputV2,
  cloneAutomationRunInputV2,
  cloneAutomationRuntimeConfigV2,
  cloneAutomationSignalV2,
  cloneAutomationToggleInputV2,
  cloneAutomationUpdateInputV2,
  invalidAutomationInputV2,
  isAutomationPlainRecordV2,
  resolveAutomationProjectIdV2,
} from './desktopAutomationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_AUTOMATION_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/automation-authority';
export const DESKTOP_AUTOMATION_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.automation-authority';
export const DESKTOP_AUTOMATION_AUTHORITY_VERSION_V2 = '1.0.0';

type DesktopAutomationMethodV2 = keyof DesktopAutomationApi;
type OperationKindV2 =
  | 'create-automation'
  | 'delete-automation'
  | 'get-automation-capabilities'
  | 'list-automation-runs'
  | 'list-automations'
  | 'run-automation'
  | 'toggle-automation'
  | 'update-automation';

export interface DesktopAutomationAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => DesktopAutomationApi;
}

export type DesktopAutomationOperationsV2 = DesktopAutomationApi;

export type DesktopAutomationOperationInputV2 =
  | Readonly<{
      kind: 'list-automations' | 'get-automation-capabilities';
      config: DesktopRuntimeConfig;
      projectId?: string;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'create-automation';
      config: DesktopRuntimeConfig;
      input: AutomationCreateInput;
      projectId?: string;
    }>
  | Readonly<{
      kind: 'update-automation';
      config: DesktopRuntimeConfig;
      automationId: string;
      input: AutomationUpdateInput;
      projectId?: string;
    }>
  | Readonly<{
      kind: 'toggle-automation';
      config: DesktopRuntimeConfig;
      automationId: string;
      input: AutomationToggleInput;
      projectId?: string;
    }>
  | Readonly<{
      kind: 'delete-automation';
      config: DesktopRuntimeConfig;
      automationId: string;
      input: AutomationDeleteInput;
      projectId?: string;
    }>
  | Readonly<{
      kind: 'list-automation-runs';
      config: DesktopRuntimeConfig;
      automationId: string;
      projectId?: string;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'run-automation';
      config: DesktopRuntimeConfig;
      automationId: string;
      input: AutomationRunInput;
      projectId?: string;
    }>;

type PreparedOperationV2 = Readonly<{
  kind: OperationKindV2;
  config: DesktopRuntimeConfig;
  projectId: string;
  automationId?: string;
  signal?: AbortSignal;
  input?:
    | AutomationCreateInput
    | AutomationDeleteInput
    | AutomationRunInput
    | AutomationToggleInput
    | AutomationUpdateInput;
}>;

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;
type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;
type AuthorityAdmissionRejectionV2 =
  | ServiceAdmissionRejectionV2
  | GenerationActionsUnavailableV2;

const AUTHORITY_METHODS_V2 = new Set<DesktopAutomationMethodV2>([
  'createAutomation',
  'deleteAutomation',
  'getAutomationCapabilities',
  'listAutomationRuns',
  'listAutomations',
  'runAutomation',
  'toggleAutomation',
  'updateAutomation',
]);

export class DesktopAutomationAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopAutomationAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopAutomationAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_automation_authority_config_invalid',
      'desktop Automation authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopAutomationAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopAutomationAuthorityV2,
  });
  context.provide(DESKTOP_AUTOMATION_AUTHORITY_SERVICE_V2, service);
}

export const desktopAutomationAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_AUTOMATION_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopAutomationAuthorityV2,
});

export function createDesktopAutomationOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
  resolveConfig: () => DesktopRuntimeConfig,
): DesktopAutomationOperationsV2 {
  return Object.freeze({
    async listAutomations(projectId?: string, signal?: AbortSignal) {
      const prepared = prepareOperationV2({
        kind: 'list-automations',
        config: resolveConfig(),
        projectId,
        signal,
      });
      return runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (authority) =>
        authority.listAutomations(prepared.projectId, prepared.signal),
      );
    },
    async getAutomationCapabilities(projectId?: string, signal?: AbortSignal) {
      const prepared = prepareOperationV2({
        kind: 'get-automation-capabilities',
        config: resolveConfig(),
        projectId,
        signal,
      });
      return runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (authority) =>
        authority.getAutomationCapabilities(prepared.projectId, prepared.signal),
      );
    },
    async createAutomation(input: AutomationCreateInput, projectId?: string) {
      const prepared = prepareOperationV2({
        kind: 'create-automation',
        config: resolveConfig(),
        input,
        projectId,
      });
      return runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (authority) =>
        authority.createAutomation(prepared.input as AutomationCreateInput, prepared.projectId),
      );
    },
    async updateAutomation(
      automationId: string,
      input: AutomationUpdateInput,
      projectId?: string,
    ) {
      const prepared = prepareOperationV2({
        kind: 'update-automation',
        config: resolveConfig(),
        automationId,
        input,
        projectId,
      });
      return runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (authority) =>
        authority.updateAutomation(
          prepared.automationId as string,
          prepared.input as AutomationUpdateInput,
          prepared.projectId,
        ),
      );
    },
    async toggleAutomation(
      automationId: string,
      input: AutomationToggleInput,
      projectId?: string,
    ) {
      const prepared = prepareOperationV2({
        kind: 'toggle-automation',
        config: resolveConfig(),
        automationId,
        input,
        projectId,
      });
      return runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (authority) =>
        authority.toggleAutomation(
          prepared.automationId as string,
          prepared.input as AutomationToggleInput,
          prepared.projectId,
        ),
      );
    },
    async deleteAutomation(
      automationId: string,
      input: AutomationDeleteInput,
      projectId?: string,
    ) {
      const prepared = prepareOperationV2({
        kind: 'delete-automation',
        config: resolveConfig(),
        automationId,
        input,
        projectId,
      });
      return runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (authority) =>
        authority.deleteAutomation(
          prepared.automationId as string,
          prepared.input as AutomationDeleteInput,
          prepared.projectId,
        ),
      );
    },
    async listAutomationRuns(
      automationId: string,
      projectId?: string,
      signal?: AbortSignal,
    ) {
      const prepared = prepareOperationV2({
        kind: 'list-automation-runs',
        config: resolveConfig(),
        automationId,
        projectId,
        signal,
      });
      return runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (authority) =>
        authority.listAutomationRuns(
          prepared.automationId as string,
          prepared.projectId,
          prepared.signal,
        ),
      );
    },
    async runAutomation(
      automationId: string,
      input: AutomationRunInput,
      projectId?: string,
    ) {
      const prepared = prepareOperationV2({
        kind: 'run-automation',
        config: resolveConfig(),
        automationId,
        input,
        projectId,
      });
      return runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (authority) =>
        authority.runAutomation(
          prepared.automationId as string,
          prepared.input as AutomationRunInput,
          prepared.projectId,
        ),
      );
    },
  });
}

export function withDesktopAutomationAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopAutomationOperationInputV2,
  operation: (
    authority: DesktopAutomationApi,
    prepared: PreparedOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runOperationV2(actions, prepareOperationV2(input), operation);
}

async function runOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedOperationV2,
  operation: (
    authority: DesktopAutomationApi,
    prepared: PreparedOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopAutomationAuthorityServiceV2>({
      service: DESKTOP_AUTOMATION_AUTHORITY_SERVICE_V2,
      version: DESKTOP_AUTOMATION_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.config.tenantId,
        project_id: prepared.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopAutomationAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireServiceV2(candidate);
      const authority = requireAuthorityV2(service.bindOperation(prepared.config));
      return operation(
        createGuardedAuthorityV2(
          authority,
          prepared.config,
          prepared.kind,
          () => operationActive,
        ),
        prepared,
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

function createDesktopAutomationAuthorityV2(config: DesktopRuntimeConfig): DesktopAutomationApi {
  const operationConfig = cloneAutomationRuntimeConfigV2(config);
  const authority = createDesktopAutomationApi(
    new DesktopApiClient(operationConfig),
    operationConfig,
  );
  return createGuardedAuthorityV2(authority, operationConfig, null, () => true);
}

function createGuardedAuthorityV2(
  authority: DesktopAutomationApi,
  config: DesktopRuntimeConfig,
  allowedKind: OperationKindV2 | null,
  isOperationActive: () => boolean,
): DesktopAutomationApi {
  const requireCall = (kind: OperationKindV2) => {
    if (!isOperationActive()) {
      throw new RuntimeV2Error(
        'desktop_automation_operation_released',
        'desktop Automation operation has been released',
      );
    }
    if (allowedKind !== null && kind !== allowedKind) {
      throw new RuntimeV2Error(
        'desktop_automation_operation_kind_mismatch',
        'desktop Automation operation differs from its acquired lease',
      );
    }
  };
  return Object.freeze({
    listAutomations(projectId?: string, signal?: AbortSignal) {
      requireCall('list-automations');
      const checkedProjectId = resolveAutomationProjectIdV2(config, projectId);
      const checkedSignal = cloneAutomationSignalV2(signal);
      return authority
        .listAutomations(checkedProjectId, checkedSignal)
        .then((value) => assertAutomationJobListV2(value, config));
    },
    getAutomationCapabilities(projectId?: string, signal?: AbortSignal) {
      requireCall('get-automation-capabilities');
      const checkedProjectId = resolveAutomationProjectIdV2(config, projectId);
      const checkedSignal = cloneAutomationSignalV2(signal);
      return authority
        .getAutomationCapabilities(checkedProjectId, checkedSignal)
        .then(assertAutomationCapabilitiesV2);
    },
    createAutomation(input: AutomationCreateInput, projectId?: string) {
      requireCall('create-automation');
      const checkedProjectId = resolveAutomationProjectIdV2(config, projectId);
      const request = cloneAutomationCreateInputV2(input);
      return authority
        .createAutomation(request, checkedProjectId)
        .then((value) => assertAutomationJobV2(value, config));
    },
    updateAutomation(
      automationId: string,
      input: AutomationUpdateInput,
      projectId?: string,
    ) {
      requireCall('update-automation');
      const checkedId = canonicalAutomationIdentifierV2(automationId);
      const checkedProjectId = resolveAutomationProjectIdV2(config, projectId);
      const request = cloneAutomationUpdateInputV2(input);
      return authority
        .updateAutomation(checkedId, request, checkedProjectId)
        .then((value) => assertAutomationJobV2(value, config, checkedId));
    },
    toggleAutomation(
      automationId: string,
      input: AutomationToggleInput,
      projectId?: string,
    ) {
      requireCall('toggle-automation');
      const checkedId = canonicalAutomationIdentifierV2(automationId);
      const checkedProjectId = resolveAutomationProjectIdV2(config, projectId);
      const request = cloneAutomationToggleInputV2(input);
      return authority
        .toggleAutomation(checkedId, request, checkedProjectId)
        .then((value) => assertAutomationJobV2(value, config, checkedId));
    },
    deleteAutomation(
      automationId: string,
      input: AutomationDeleteInput,
      projectId?: string,
    ) {
      requireCall('delete-automation');
      const checkedId = canonicalAutomationIdentifierV2(automationId);
      const checkedProjectId = resolveAutomationProjectIdV2(config, projectId);
      const request = cloneAutomationDeleteInputV2(input);
      return authority.deleteAutomation(checkedId, request, checkedProjectId).then((value) => {
        assertAutomationDeleteResponseV2(value);
      });
    },
    listAutomationRuns(
      automationId: string,
      projectId?: string,
      signal?: AbortSignal,
    ) {
      requireCall('list-automation-runs');
      const checkedId = canonicalAutomationIdentifierV2(automationId);
      const checkedProjectId = resolveAutomationProjectIdV2(config, projectId);
      const checkedSignal = cloneAutomationSignalV2(signal);
      return authority
        .listAutomationRuns(checkedId, checkedProjectId, checkedSignal)
        .then((value) => assertAutomationRunListV2(value, config, checkedId));
    },
    runAutomation(automationId: string, input: AutomationRunInput, projectId?: string) {
      requireCall('run-automation');
      const checkedId = canonicalAutomationIdentifierV2(automationId);
      const checkedProjectId = resolveAutomationProjectIdV2(config, projectId);
      const request = cloneAutomationRunInputV2(input);
      return authority
        .runAutomation(checkedId, request, checkedProjectId)
        .then((value) => assertAutomationRunReceiptV2(value, checkedId));
    },
  });
}

function prepareOperationV2(input: DesktopAutomationOperationInputV2): PreparedOperationV2 {
  if (!isAutomationPlainRecordV2(input) || typeof input.kind !== 'string') {
    throw invalidAutomationInputV2();
  }
  const config = cloneAutomationRuntimeConfigV2(input.config);
  const projectId = resolveAutomationProjectIdV2(config, input.projectId);
  switch (input.kind) {
    case 'list-automations':
    case 'get-automation-capabilities':
      return Object.freeze({
        kind: input.kind,
        config,
        projectId,
        signal: cloneAutomationSignalV2(input.signal),
      });
    case 'create-automation':
      return Object.freeze({
        kind: input.kind,
        config,
        projectId,
        input: cloneAutomationCreateInputV2(input.input),
      });
    case 'update-automation':
      return Object.freeze({
        kind: input.kind,
        config,
        projectId,
        automationId: canonicalAutomationIdentifierV2(input.automationId),
        input: cloneAutomationUpdateInputV2(input.input),
      });
    case 'toggle-automation':
      return Object.freeze({
        kind: input.kind,
        config,
        projectId,
        automationId: canonicalAutomationIdentifierV2(input.automationId),
        input: cloneAutomationToggleInputV2(input.input),
      });
    case 'delete-automation':
      return Object.freeze({
        kind: input.kind,
        config,
        projectId,
        automationId: canonicalAutomationIdentifierV2(input.automationId),
        input: cloneAutomationDeleteInputV2(input.input),
      });
    case 'list-automation-runs':
      return Object.freeze({
        kind: input.kind,
        config,
        projectId,
        automationId: canonicalAutomationIdentifierV2(input.automationId),
        signal: cloneAutomationSignalV2(input.signal),
      });
    case 'run-automation':
      return Object.freeze({
        kind: input.kind,
        config,
        projectId,
        automationId: canonicalAutomationIdentifierV2(input.automationId),
        input: cloneAutomationRunInputV2(input.input),
      });
    default:
      throw invalidAutomationInputV2();
  }
}

function requireServiceV2(value: unknown): DesktopAutomationAuthorityServiceV2 {
  if (
    !isAutomationPlainRecordV2(value) ||
    Object.keys(value).some((key) => key !== 'bindOperation') ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopAutomationAuthorityServiceV2;
}

function requireAuthorityV2(value: unknown): DesktopAutomationApi {
  if (
    !isAutomationPlainRecordV2(value) ||
    Object.keys(value).some((key) => !AUTHORITY_METHODS_V2.has(key as DesktopAutomationMethodV2)) ||
    [...AUTHORITY_METHODS_V2].some((method) => typeof value[method] !== 'function')
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopAutomationApi;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null && typeof actions.acquireServiceOperationLease === 'function') return actions;
  throw new DesktopAutomationAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_automation_service_invalid',
    'desktop Automation authority service is invalid',
  );
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_AUTOMATION_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_automation_authority_catalog_missing',
      'desktop Automation authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
