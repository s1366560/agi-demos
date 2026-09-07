import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type { DesktopRuntimeConfig, WorkspaceAgentBinding, WorkspaceMemberSummary } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import {
  assertWorkspaceRosterSignalV2,
  cloneWorkspaceRosterAgentsV2,
  cloneWorkspaceRosterMembersV2,
  cloneWorkspaceRosterRuntimeConfigV2,
  cloneWorkspaceRosterSignalV2,
  hasExactOptionalKeysV2,
  isPlainRecordV2,
  workspaceRosterInputInvalidV2,
} from './desktopWorkspaceRosterContractV2';

export const DESKTOP_WORKSPACE_ROSTER_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/workspace-roster-authority';
export const DESKTOP_WORKSPACE_ROSTER_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.workspace-roster-authority';
export const DESKTOP_WORKSPACE_ROSTER_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopWorkspaceRosterOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  signal?: AbortSignal;
}>;

export interface DesktopWorkspaceRosterAuthorityV2 {
  readonly listWorkspaceMembers: (signal?: AbortSignal) => Promise<WorkspaceMemberSummary[]>;
  readonly listWorkspaceAgents: (signal?: AbortSignal) => Promise<WorkspaceAgentBinding[]>;
}

export interface DesktopWorkspaceRosterAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => DesktopWorkspaceRosterAuthorityV2;
}

export interface DesktopWorkspaceRosterOperationsV2 {
  readonly listWorkspaceMembers: (
    input: DesktopWorkspaceRosterOperationInputV2
  ) => Promise<WorkspaceMemberSummary[]>;
  readonly listWorkspaceAgents: (
    input: DesktopWorkspaceRosterOperationInputV2
  ) => Promise<WorkspaceAgentBinding[]>;
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

type PreparedWorkspaceRosterOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  signal?: AbortSignal;
}>;

const OPERATION_INPUT_KEYS_V2 = new Set(['config', 'signal']);
const AUTHORITY_KEYS_V2 = new Set(['listWorkspaceAgents', 'listWorkspaceMembers']);

export class DesktopWorkspaceRosterAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopWorkspaceRosterAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopWorkspaceRosterAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_workspace_roster_authority_config_invalid',
      'desktop workspace roster authority requires desktop-api-client strategy'
    );
  }
  const service: DesktopWorkspaceRosterAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopWorkspaceRosterAuthorityV2,
  });
  context.provide(DESKTOP_WORKSPACE_ROSTER_AUTHORITY_SERVICE_V2, service);
}

export const desktopWorkspaceRosterAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_WORKSPACE_ROSTER_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopWorkspaceRosterAuthorityV2,
});

export function createDesktopWorkspaceRosterOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null
): DesktopWorkspaceRosterOperationsV2 {
  return Object.freeze({
    listWorkspaceMembers(input: DesktopWorkspaceRosterOperationInputV2) {
      const prepared = prepareWorkspaceRosterOperationV2(input);
      return runDesktopWorkspaceRosterAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.listWorkspaceMembers(prepared.signal)
      );
    },
    listWorkspaceAgents(input: DesktopWorkspaceRosterOperationInputV2) {
      const prepared = prepareWorkspaceRosterOperationV2(input);
      return runDesktopWorkspaceRosterAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.listWorkspaceAgents(prepared.signal)
      );
    },
  });
}

export function withDesktopWorkspaceRosterAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopWorkspaceRosterOperationInputV2,
  operation: (
    authority: DesktopWorkspaceRosterAuthorityV2,
    prepared: PreparedWorkspaceRosterOperationV2
  ) => TResult | Promise<TResult>
): Promise<TResult> {
  return runDesktopWorkspaceRosterAuthorityOperationV2(
    actions,
    prepareWorkspaceRosterOperationV2(input),
    operation
  );
}

async function runDesktopWorkspaceRosterAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedWorkspaceRosterOperationV2,
  operation: (
    authority: DesktopWorkspaceRosterAuthorityV2,
    prepared: PreparedWorkspaceRosterOperationV2
  ) => TResult | Promise<TResult>
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopWorkspaceRosterAuthorityServiceV2>({
      service: DESKTOP_WORKSPACE_ROSTER_AUTHORITY_SERVICE_V2,
      version: DESKTOP_WORKSPACE_ROSTER_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.config.tenantId,
        project_id: prepared.config.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopWorkspaceRosterAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireWorkspaceRosterServiceV2(candidate);
      const authority = requireWorkspaceRosterAuthorityV2(service.bindOperation(prepared.config));
      return operation(
        createRevocableWorkspaceRosterAuthorityV2(authority, prepared, () => operationActive),
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

function createDesktopWorkspaceRosterAuthorityV2(
  config: DesktopRuntimeConfig
): DesktopWorkspaceRosterAuthorityV2 {
  const operationConfig = cloneWorkspaceRosterRuntimeConfigV2(config);
  const transport = new DesktopApiClient(operationConfig);
  return Object.freeze({
    listWorkspaceMembers(signal?: AbortSignal) {
      const operationSignal = cloneWorkspaceRosterSignalV2(signal);
      return transport
        .listWorkspaceMembers(operationSignal)
        .then((value) => cloneWorkspaceRosterMembersV2(value, operationConfig.workspaceId));
    },
    listWorkspaceAgents(signal?: AbortSignal) {
      const operationSignal = cloneWorkspaceRosterSignalV2(signal);
      return transport
        .listWorkspaceAgents(operationSignal)
        .then((value) => cloneWorkspaceRosterAgentsV2(value, operationConfig.workspaceId));
    },
  });
}

function createRevocableWorkspaceRosterAuthorityV2(
  authority: DesktopWorkspaceRosterAuthorityV2,
  prepared: PreparedWorkspaceRosterOperationV2,
  isOperationActive: () => boolean
): DesktopWorkspaceRosterAuthorityV2 {
  return Object.freeze({
    listWorkspaceMembers(signal?: AbortSignal) {
      assertOperationActiveV2(isOperationActive);
      const operationSignal = cloneWorkspaceRosterSignalV2(signal);
      assertWorkspaceRosterSignalV2(prepared.signal, operationSignal);
      return Promise.resolve(authority.listWorkspaceMembers(operationSignal)).then((value) =>
        cloneWorkspaceRosterMembersV2(value, prepared.config.workspaceId)
      );
    },
    listWorkspaceAgents(signal?: AbortSignal) {
      assertOperationActiveV2(isOperationActive);
      const operationSignal = cloneWorkspaceRosterSignalV2(signal);
      assertWorkspaceRosterSignalV2(prepared.signal, operationSignal);
      return Promise.resolve(authority.listWorkspaceAgents(operationSignal)).then((value) =>
        cloneWorkspaceRosterAgentsV2(value, prepared.config.workspaceId)
      );
    },
  });
}

function prepareWorkspaceRosterOperationV2(
  input: DesktopWorkspaceRosterOperationInputV2
): PreparedWorkspaceRosterOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasExactOptionalKeysV2(input, OPERATION_INPUT_KEYS_V2) ||
    !Object.hasOwn(input, 'config')
  ) {
    throw workspaceRosterInputInvalidV2();
  }
  const config = cloneWorkspaceRosterRuntimeConfigV2(input.config);
  return Object.freeze({
    config,
    ...(input.signal === undefined ? {} : { signal: cloneWorkspaceRosterSignalV2(input.signal) }),
  });
}

function assertOperationActiveV2(isOperationActive: () => boolean): void {
  if (!isOperationActive()) {
    throw new RuntimeV2Error(
      'desktop_workspace_roster_operation_released',
      'desktop workspace roster operation has been released'
    );
  }
}

function requireWorkspaceRosterServiceV2(value: unknown): DesktopWorkspaceRosterAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidWorkspaceRosterServiceV2();
  }
  return value as unknown as DesktopWorkspaceRosterAuthorityServiceV2;
}

function requireWorkspaceRosterAuthorityV2(value: unknown): DesktopWorkspaceRosterAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== AUTHORITY_KEYS_V2.size ||
    !Object.keys(value).every((key) => AUTHORITY_KEYS_V2.has(key)) ||
    typeof value.listWorkspaceMembers !== 'function' ||
    typeof value.listWorkspaceAgents !== 'function'
  ) {
    throw invalidWorkspaceRosterServiceV2();
  }
  return value as unknown as DesktopWorkspaceRosterAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopWorkspaceRosterAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidWorkspaceRosterServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_roster_service_invalid',
    'desktop workspace roster authority service is invalid'
  );
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_WORKSPACE_ROSTER_AUTHORITY_MODULE_REF_V2
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_workspace_roster_authority_catalog_missing',
      'desktop workspace roster authority is absent from the generated catalog'
    );
  }
  return entry.contract_digest;
}
