import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import {
  DesktopApiClient,
  type WorkspaceAgentBindInput,
  type WorkspaceBindingAgentDefinition,
} from '../api/client';
import type { DesktopRuntimeConfig, WorkspaceAgentBinding } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_WORKSPACE_AGENT_BINDING_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/workspace-agent-binding-authority';
export const DESKTOP_WORKSPACE_AGENT_BINDING_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.workspace-agent-binding-authority';
export const DESKTOP_WORKSPACE_AGENT_BINDING_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopWorkspaceAgentBindingOperationScopeInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  workspaceId: string;
  signal?: AbortSignal;
}>;

export type DesktopWorkspaceAgentBindOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  workspaceId: string;
  input: WorkspaceAgentBindInput;
  signal?: AbortSignal;
}>;

export type DesktopWorkspaceAgentUnbindOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  workspaceId: string;
  bindingId: string;
  signal?: AbortSignal;
}>;

export interface DesktopWorkspaceAgentBindingAuthorityV2 {
  readonly listAgentDefinitions: (
    signal?: AbortSignal,
  ) => Promise<WorkspaceBindingAgentDefinition[]>;
  readonly bindAgent: (
    input: WorkspaceAgentBindInput,
    signal?: AbortSignal,
  ) => Promise<WorkspaceAgentBinding>;
  readonly unbindAgent: (bindingId: string, signal?: AbortSignal) => Promise<void>;
}

export interface DesktopWorkspaceAgentBindingAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    workspaceId: string,
  ) => DesktopWorkspaceAgentBindingAuthorityV2;
}

export interface DesktopWorkspaceAgentBindingOperationsV2 {
  readonly listWorkspaceBindingAgentDefinitions: (
    input: DesktopWorkspaceAgentBindingOperationScopeInputV2,
  ) => Promise<WorkspaceBindingAgentDefinition[]>;
  readonly bindWorkspaceAgent: (
    input: DesktopWorkspaceAgentBindOperationInputV2,
  ) => Promise<WorkspaceAgentBinding>;
  readonly unbindWorkspaceAgent: (
    input: DesktopWorkspaceAgentUnbindOperationInputV2,
  ) => Promise<void>;
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

type PreparedWorkspaceAgentBindingScopeV2 = Readonly<{
  config: DesktopRuntimeConfig;
  workspaceId: string;
  signal?: AbortSignal;
}>;

const SCOPE_INPUT_KEYS_V2 = new Set(['config', 'signal', 'workspaceId']);
const BIND_OPERATION_INPUT_KEYS_V2 = new Set(['config', 'input', 'signal', 'workspaceId']);
const UNBIND_OPERATION_INPUT_KEYS_V2 = new Set(['bindingId', 'config', 'signal', 'workspaceId']);
const BIND_INPUT_KEYS_V2 = new Set(['agentId', 'description', 'displayName']);
const DEFINITION_KEYS_V2 = new Set([
  'display_name',
  'enabled',
  'id',
  'model',
  'name',
  'project_id',
  'tenant_id',
]);
const BINDING_REQUIRED_KEYS_V2 = new Set(['agent_id', 'id', 'is_active', 'workspace_id']);
const BINDING_OPTIONAL_KEYS_V2 = new Set([
  'config',
  'created_at',
  'description',
  'display_name',
  'hex_q',
  'hex_r',
  'label',
  'status',
  'theme_color',
  'updated_at',
]);
const AUTHORITY_KEYS_V2 = new Set(['bindAgent', 'listAgentDefinitions', 'unbindAgent']);

export class DesktopWorkspaceAgentBindingAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopWorkspaceAgentBindingAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopWorkspaceAgentBindingAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_workspace_agent_binding_authority_config_invalid',
      'desktop workspace Agent-binding authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopWorkspaceAgentBindingAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopWorkspaceAgentBindingAuthorityV2,
  });
  context.provide(DESKTOP_WORKSPACE_AGENT_BINDING_AUTHORITY_SERVICE_V2, service);
}

export const desktopWorkspaceAgentBindingAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_WORKSPACE_AGENT_BINDING_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopWorkspaceAgentBindingAuthorityV2,
});

export function createDesktopWorkspaceAgentBindingOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopWorkspaceAgentBindingOperationsV2 {
  return Object.freeze({
    listWorkspaceBindingAgentDefinitions(input: DesktopWorkspaceAgentBindingOperationScopeInputV2) {
      const prepared = prepareWorkspaceAgentBindingScopeV2(input, SCOPE_INPUT_KEYS_V2);
      return runDesktopWorkspaceAgentBindingAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.listAgentDefinitions(prepared.signal),
      );
    },
    bindWorkspaceAgent(input: DesktopWorkspaceAgentBindOperationInputV2) {
      if (
        !isPlainRecordV2(input) ||
        !hasExactOptionalKeysV2(input, BIND_OPERATION_INPUT_KEYS_V2) ||
        !Object.hasOwn(input, 'input')
      ) {
        throw invalidWorkspaceAgentBindingInputV2();
      }
      const prepared = prepareWorkspaceAgentBindingScopeV2(input, BIND_OPERATION_INPUT_KEYS_V2);
      const bindInput = cloneWorkspaceAgentBindInputV2(input.input);
      return runDesktopWorkspaceAgentBindingAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.bindAgent(bindInput, prepared.signal),
      );
    },
    unbindWorkspaceAgent(input: DesktopWorkspaceAgentUnbindOperationInputV2) {
      if (
        !isPlainRecordV2(input) ||
        !hasExactOptionalKeysV2(input, UNBIND_OPERATION_INPUT_KEYS_V2) ||
        !Object.hasOwn(input, 'bindingId') ||
        !isCanonicalStringV2(input.bindingId)
      ) {
        throw invalidWorkspaceAgentBindingInputV2();
      }
      const prepared = prepareWorkspaceAgentBindingScopeV2(input, UNBIND_OPERATION_INPUT_KEYS_V2);
      const bindingId = input.bindingId;
      return runDesktopWorkspaceAgentBindingAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.unbindAgent(bindingId, prepared.signal),
      );
    },
  });
}

export function withDesktopWorkspaceAgentBindingAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopWorkspaceAgentBindingOperationScopeInputV2,
  operation: (
    authority: DesktopWorkspaceAgentBindingAuthorityV2,
    prepared: PreparedWorkspaceAgentBindingScopeV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopWorkspaceAgentBindingAuthorityOperationV2(
    actions,
    prepareWorkspaceAgentBindingScopeV2(input, SCOPE_INPUT_KEYS_V2),
    operation,
  );
}

async function runDesktopWorkspaceAgentBindingAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedWorkspaceAgentBindingScopeV2,
  operation: (
    authority: DesktopWorkspaceAgentBindingAuthorityV2,
    prepared: PreparedWorkspaceAgentBindingScopeV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopWorkspaceAgentBindingAuthorityServiceV2>({
      service: DESKTOP_WORKSPACE_AGENT_BINDING_AUTHORITY_SERVICE_V2,
      version: DESKTOP_WORKSPACE_AGENT_BINDING_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.config.tenantId,
        project_id: prepared.config.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopWorkspaceAgentBindingAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireWorkspaceAgentBindingServiceV2(candidate);
      const authority = requireWorkspaceAgentBindingAuthorityV2(
        service.bindOperation(prepared.config, prepared.workspaceId),
      );
      return operation(
        createRevocableDesktopWorkspaceAgentBindingAuthorityV2(
          authority,
          prepared,
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

function createDesktopWorkspaceAgentBindingAuthorityV2(
  config: DesktopRuntimeConfig,
  workspaceId: string,
): DesktopWorkspaceAgentBindingAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const operationWorkspaceId = requireMatchingWorkspaceIdV2(operationConfig, workspaceId);
  const transport = new DesktopApiClient(operationConfig);
  return Object.freeze({
    listAgentDefinitions(signal?: AbortSignal) {
      const operationSignal = cloneOptionalSignalV2(signal);
      return transport
        .listWorkspaceBindingAgentDefinitionsForProject(
          operationConfig.projectId,
          operationConfig.tenantId,
          operationSignal,
        )
        .then((value) => cloneWorkspaceBindingAgentDefinitionsV2(value, operationConfig));
    },
    bindAgent(input: WorkspaceAgentBindInput, signal?: AbortSignal) {
      const operationInput = cloneWorkspaceAgentBindInputV2(input);
      const operationSignal = cloneOptionalSignalV2(signal);
      return transport
        .bindWorkspaceAgentForProject(
          operationConfig.projectId,
          operationWorkspaceId,
          operationInput,
          operationConfig.tenantId,
          operationSignal,
        )
        .then((value) =>
          cloneWorkspaceAgentBindingV2(value, operationWorkspaceId, operationInput.agentId),
        );
    },
    unbindAgent(bindingId: string, signal?: AbortSignal) {
      if (!isCanonicalStringV2(bindingId)) throw invalidWorkspaceAgentBindingInputV2();
      const operationSignal = cloneOptionalSignalV2(signal);
      return transport
        .unbindWorkspaceAgentForProject(
          operationConfig.projectId,
          operationWorkspaceId,
          bindingId,
          operationConfig.tenantId,
          operationSignal,
        )
        .then(assertVoidWorkspaceAgentBindingResponseV2);
    },
  });
}

function createRevocableDesktopWorkspaceAgentBindingAuthorityV2(
  authority: DesktopWorkspaceAgentBindingAuthorityV2,
  expected: PreparedWorkspaceAgentBindingScopeV2,
  isOperationActive: () => boolean,
): DesktopWorkspaceAgentBindingAuthorityV2 {
  return Object.freeze({
    listAgentDefinitions(signal?: AbortSignal) {
      assertWorkspaceAgentBindingOperationActiveV2(isOperationActive);
      const operationSignal = cloneOptionalSignalV2(signal);
      assertExpectedWorkspaceAgentBindingSignalV2(expected, operationSignal);
      return Promise.resolve(authority.listAgentDefinitions(operationSignal)).then((value) =>
        cloneWorkspaceBindingAgentDefinitionsV2(value, expected.config),
      );
    },
    bindAgent(input: WorkspaceAgentBindInput, signal?: AbortSignal) {
      assertWorkspaceAgentBindingOperationActiveV2(isOperationActive);
      const operationInput = cloneWorkspaceAgentBindInputV2(input);
      const operationSignal = cloneOptionalSignalV2(signal);
      assertExpectedWorkspaceAgentBindingSignalV2(expected, operationSignal);
      return Promise.resolve(authority.bindAgent(operationInput, operationSignal)).then((value) =>
        cloneWorkspaceAgentBindingV2(value, expected.workspaceId, operationInput.agentId),
      );
    },
    unbindAgent(bindingId: string, signal?: AbortSignal) {
      assertWorkspaceAgentBindingOperationActiveV2(isOperationActive);
      if (!isCanonicalStringV2(bindingId)) throw invalidWorkspaceAgentBindingInputV2();
      const operationSignal = cloneOptionalSignalV2(signal);
      assertExpectedWorkspaceAgentBindingSignalV2(expected, operationSignal);
      return Promise.resolve(authority.unbindAgent(bindingId, operationSignal)).then(
        assertVoidWorkspaceAgentBindingResponseV2,
      );
    },
  });
}

function prepareWorkspaceAgentBindingScopeV2(
  input: DesktopWorkspaceAgentBindingOperationScopeInputV2,
  allowedKeys: Set<string>,
): PreparedWorkspaceAgentBindingScopeV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasExactOptionalKeysV2(input, allowedKeys) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'workspaceId')
  ) {
    throw invalidWorkspaceAgentBindingInputV2();
  }
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const workspaceId = requireMatchingWorkspaceIdV2(config, input.workspaceId);
  const signal = cloneOptionalSignalV2(input.signal);
  return Object.freeze({
    config,
    workspaceId,
    ...(signal === undefined ? {} : { signal }),
  });
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidWorkspaceAgentBindingInputV2();
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
    !isCanonicalStringV2(copy.apiBaseUrl) ||
    !isCanonicalStringV2(copy.tenantId) ||
    !isCanonicalStringV2(copy.projectId)
  ) {
    throw invalidWorkspaceAgentBindingInputV2();
  }
  return Object.freeze(copy);
}

function requireMatchingWorkspaceIdV2(config: DesktopRuntimeConfig, workspaceId: unknown): string {
  if (!isCanonicalStringV2(workspaceId) || config.workspaceId !== workspaceId) {
    throw invalidWorkspaceAgentBindingInputV2();
  }
  return workspaceId;
}

function cloneWorkspaceAgentBindInputV2(value: WorkspaceAgentBindInput): WorkspaceAgentBindInput {
  if (
    !isPlainRecordV2(value) ||
    !hasExactOptionalKeysV2(value, BIND_INPUT_KEYS_V2) ||
    !Object.hasOwn(value, 'agentId') ||
    !isCanonicalStringV2(value.agentId) ||
    (value.displayName !== undefined && typeof value.displayName !== 'string') ||
    (value.description !== undefined && typeof value.description !== 'string')
  ) {
    throw invalidWorkspaceAgentBindingInputV2();
  }
  const displayName = value.displayName?.trim() ?? '';
  const description = value.description?.trim() ?? '';
  if (displayName.length > 120 || description.length > 500) {
    throw invalidWorkspaceAgentBindingInputV2();
  }
  return Object.freeze({
    agentId: value.agentId,
    ...(displayName ? { displayName } : {}),
    ...(description ? { description } : {}),
  });
}

function cloneOptionalSignalV2(value: unknown): AbortSignal | undefined {
  if (value === undefined) return undefined;
  if (typeof AbortSignal === 'undefined' || !(value instanceof AbortSignal)) {
    throw invalidWorkspaceAgentBindingInputV2();
  }
  return value;
}

function assertExpectedWorkspaceAgentBindingSignalV2(
  expected: PreparedWorkspaceAgentBindingScopeV2,
  signal: AbortSignal | undefined,
): void {
  if (signal !== expected.signal) throw invalidWorkspaceAgentBindingInputV2();
}

function cloneWorkspaceBindingAgentDefinitionsV2(
  value: unknown,
  config: DesktopRuntimeConfig,
): WorkspaceBindingAgentDefinition[] {
  if (!Array.isArray(value)) throw invalidWorkspaceAgentBindingResponseV2();
  const seenIds = new Set<string>();
  const copy = value.map((candidate) => {
    if (
      !isPlainRecordV2(candidate) ||
      !hasExactKeysV2(candidate, DEFINITION_KEYS_V2) ||
      !isCanonicalStringV2(candidate.id) ||
      seenIds.has(candidate.id) ||
      candidate.tenant_id !== config.tenantId ||
      (candidate.project_id !== null && candidate.project_id !== config.projectId) ||
      !isCanonicalStringV2(candidate.name) ||
      !isNullableCanonicalStringV2(candidate.display_name) ||
      candidate.enabled !== true ||
      !isNullableCanonicalStringV2(candidate.model)
    ) {
      throw invalidWorkspaceAgentBindingResponseV2();
    }
    seenIds.add(candidate.id);
    return Object.freeze({
      id: candidate.id,
      tenant_id: config.tenantId,
      project_id: candidate.project_id,
      name: candidate.name,
      display_name: candidate.display_name,
      enabled: true as const,
      model: candidate.model,
    });
  });
  return Object.freeze(copy) as WorkspaceBindingAgentDefinition[];
}

function cloneWorkspaceAgentBindingV2(
  value: unknown,
  workspaceId: string,
  agentId: string,
): WorkspaceAgentBinding {
  if (
    !isPlainRecordV2(value) ||
    !hasRequiredAndOptionalKeysV2(value, BINDING_REQUIRED_KEYS_V2, BINDING_OPTIONAL_KEYS_V2) ||
    !isCanonicalStringV2(value.id) ||
    value.workspace_id !== workspaceId ||
    value.agent_id !== agentId ||
    typeof value.is_active !== 'boolean' ||
    !isOptionalNullableCanonicalStringV2(value.display_name) ||
    !isOptionalNullableCanonicalStringV2(value.description) ||
    !isOptionalNullableJsonRecordV2(value.config) ||
    !isOptionalNullableSafeIntegerV2(value.hex_q) ||
    !isOptionalNullableSafeIntegerV2(value.hex_r) ||
    !isOptionalNullableCanonicalStringV2(value.theme_color) ||
    !isOptionalNullableCanonicalStringV2(value.label) ||
    !isOptionalNullableCanonicalStringV2(value.status) ||
    !isOptionalCanonicalStringV2(value.created_at) ||
    !isOptionalNullableCanonicalStringV2(value.updated_at)
  ) {
    throw invalidWorkspaceAgentBindingResponseV2();
  }
  return Object.freeze({
    id: value.id,
    workspace_id: workspaceId,
    agent_id: agentId,
    is_active: value.is_active,
    ...(value.display_name === undefined ? {} : { display_name: value.display_name }),
    ...(value.description === undefined ? {} : { description: value.description }),
    ...(value.config === undefined ? {} : { config: cloneOptionalJsonRecordV2(value.config) }),
    ...(value.hex_q === undefined ? {} : { hex_q: value.hex_q }),
    ...(value.hex_r === undefined ? {} : { hex_r: value.hex_r }),
    ...(value.theme_color === undefined ? {} : { theme_color: value.theme_color }),
    ...(value.label === undefined ? {} : { label: value.label }),
    ...(value.status === undefined ? {} : { status: value.status }),
    ...(value.created_at === undefined ? {} : { created_at: value.created_at }),
    ...(value.updated_at === undefined ? {} : { updated_at: value.updated_at }),
  });
}

function assertVoidWorkspaceAgentBindingResponseV2(value: unknown): void {
  if (value !== undefined) throw invalidWorkspaceAgentBindingResponseV2();
}

function cloneOptionalJsonRecordV2(
  value: Record<string, unknown> | null,
): Record<string, unknown> | null {
  return value === null ? null : cloneJsonRecordV2(value, new WeakSet<object>());
}

function cloneJsonRecordV2(
  value: Record<string, unknown>,
  ancestors: WeakSet<object>,
): Record<string, unknown> {
  if (ancestors.has(value)) throw invalidWorkspaceAgentBindingResponseV2();
  ancestors.add(value);
  const copy: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(value)) {
    copy[key] = cloneJsonValueV2(entry, ancestors);
  }
  ancestors.delete(value);
  return Object.freeze(copy);
}

function cloneJsonValueV2(value: unknown, ancestors: WeakSet<object>): unknown {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  ) {
    return value;
  }
  if (Array.isArray(value)) {
    if (ancestors.has(value)) throw invalidWorkspaceAgentBindingResponseV2();
    ancestors.add(value);
    const copy = value.map((entry) => cloneJsonValueV2(entry, ancestors));
    ancestors.delete(value);
    return Object.freeze(copy);
  }
  if (isPlainRecordV2(value)) return cloneJsonRecordV2(value, ancestors);
  throw invalidWorkspaceAgentBindingResponseV2();
}

function requireWorkspaceAgentBindingServiceV2(
  value: unknown,
): DesktopWorkspaceAgentBindingAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, new Set(['bindOperation'])) ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidWorkspaceAgentBindingServiceV2();
  }
  return value as unknown as DesktopWorkspaceAgentBindingAuthorityServiceV2;
}

function requireWorkspaceAgentBindingAuthorityV2(
  value: unknown,
): DesktopWorkspaceAgentBindingAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.listAgentDefinitions !== 'function' ||
    typeof value.bindAgent !== 'function' ||
    typeof value.unbindAgent !== 'function'
  ) {
    throw invalidWorkspaceAgentBindingServiceV2();
  }
  return value as unknown as DesktopWorkspaceAgentBindingAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopWorkspaceAgentBindingAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function assertWorkspaceAgentBindingOperationActiveV2(isOperationActive: () => boolean): void {
  if (!isOperationActive()) {
    throw new RuntimeV2Error(
      'desktop_workspace_agent_binding_operation_released',
      'desktop workspace Agent-binding operation has been released',
    );
  }
}

function invalidWorkspaceAgentBindingInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_agent_binding_input_invalid',
    'desktop workspace Agent-binding operation input is invalid',
  );
}

function invalidWorkspaceAgentBindingResponseV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_agent_binding_response_invalid',
    'desktop workspace Agent-binding response is invalid',
  );
}

function invalidWorkspaceAgentBindingServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_agent_binding_service_invalid',
    'desktop workspace Agent-binding authority service is invalid',
  );
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function hasExactKeysV2(value: Record<string, unknown>, expected: Set<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function hasExactOptionalKeysV2(value: Record<string, unknown>, allowed: Set<string>): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function hasRequiredAndOptionalKeysV2(
  value: Record<string, unknown>,
  required: Set<string>,
  optional: Set<string>,
): boolean {
  const keys = Object.keys(value);
  return (
    [...required].every((key) => Object.hasOwn(value, key)) &&
    keys.every((key) => required.has(key) || optional.has(key))
  );
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isNullableCanonicalStringV2(value: unknown): value is string | null {
  return value === null || isCanonicalStringV2(value);
}

function isOptionalCanonicalStringV2(value: unknown): value is string | undefined {
  return value === undefined || isCanonicalStringV2(value);
}

function isOptionalNullableCanonicalStringV2(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || isCanonicalStringV2(value);
}

function isOptionalNullableSafeIntegerV2(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || Number.isSafeInteger(value);
}

function isOptionalNullableJsonRecordV2(
  value: unknown,
): value is Record<string, unknown> | null | undefined {
  if (value === undefined || value === null) return true;
  if (!isPlainRecordV2(value)) return false;
  try {
    cloneJsonRecordV2(value, new WeakSet<object>());
    return true;
  } catch {
    return false;
  }
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_WORKSPACE_AGENT_BINDING_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_workspace_agent_binding_authority_catalog_missing',
      'desktop workspace Agent-binding authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
