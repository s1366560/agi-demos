import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type {
  AgentConversation,
  DesktopRuntimeConfig,
  PaginatedConversationsResponse,
} from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/workspace-conversation-catalog-authority';
export const DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.workspace-conversation-catalog-authority';
export const DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopWorkspaceConversationCatalogFiltersV2 = Readonly<{
  workspaceId: string | null;
  unboundOnly: boolean;
  signal?: AbortSignal;
}>;

export type DesktopWorkspaceConversationCatalogOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  workspaceId: string | null;
  unboundOnly: boolean;
  signal?: AbortSignal;
}>;

export interface DesktopWorkspaceConversationCatalogAuthorityV2 {
  readonly listConversations: (
    filters: DesktopWorkspaceConversationCatalogFiltersV2,
  ) => Promise<PaginatedConversationsResponse>;
}

export interface DesktopWorkspaceConversationCatalogAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopWorkspaceConversationCatalogAuthorityV2;
}

export interface DesktopWorkspaceConversationCatalogOperationsV2 {
  readonly listConversations: (
    input: DesktopWorkspaceConversationCatalogOperationInputV2,
  ) => Promise<PaginatedConversationsResponse>;
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

type PreparedWorkspaceConversationCatalogOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  filters: DesktopWorkspaceConversationCatalogFiltersV2;
}>;

const OPERATION_INPUT_KEYS_V2 = new Set(['config', 'signal', 'unboundOnly', 'workspaceId']);
const FILTER_KEYS_V2 = new Set(['signal', 'unboundOnly', 'workspaceId']);
const RESPONSE_KEYS_V2 = new Set(['has_more', 'items', 'limit', 'next_offset', 'offset', 'total']);
const CONVERSATION_REQUIRED_KEYS_V2 = new Set([
  'created_at',
  'id',
  'message_count',
  'project_id',
  'status',
  'tenant_id',
  'title',
  'user_id',
]);
const CONVERSATION_OPTIONAL_KEYS_V2 = new Set([
  'agent_config',
  'conversation_mode',
  'coordinator_agent_id',
  'current_mode',
  'focused_agent_id',
  'linked_workspace_task_id',
  'metadata',
  'participant_agents',
  'summary',
  'updated_at',
  'workspace_id',
  'workspace_name',
]);

export class DesktopWorkspaceConversationCatalogAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopWorkspaceConversationCatalogAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopWorkspaceConversationCatalogAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_workspace_conversation_catalog_authority_config_invalid',
      'desktop workspace conversation catalog authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopWorkspaceConversationCatalogAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopWorkspaceConversationCatalogAuthorityV2,
  });
  context.provide(DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_SERVICE_V2, service);
}

export const desktopWorkspaceConversationCatalogAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopWorkspaceConversationCatalogAuthorityV2,
  });

export function createDesktopWorkspaceConversationCatalogOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopWorkspaceConversationCatalogOperationsV2 {
  return Object.freeze({
    listConversations(input: DesktopWorkspaceConversationCatalogOperationInputV2) {
      const prepared = prepareWorkspaceConversationCatalogOperationV2(input);
      return runDesktopWorkspaceConversationCatalogAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.listConversations(prepared.filters),
      );
    },
  });
}

export function withDesktopWorkspaceConversationCatalogAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopWorkspaceConversationCatalogOperationInputV2,
  operation: (
    authority: DesktopWorkspaceConversationCatalogAuthorityV2,
    prepared: PreparedWorkspaceConversationCatalogOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopWorkspaceConversationCatalogAuthorityOperationV2(
    actions,
    prepareWorkspaceConversationCatalogOperationV2(input),
    operation,
  );
}

async function runDesktopWorkspaceConversationCatalogAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedWorkspaceConversationCatalogOperationV2,
  operation: (
    authority: DesktopWorkspaceConversationCatalogAuthorityV2,
    prepared: PreparedWorkspaceConversationCatalogOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopWorkspaceConversationCatalogAuthorityServiceV2>(
      {
        service: DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: 'project',
          tenant_id: prepared.config.tenantId,
          project_id: prepared.config.projectId,
        }),
      },
    );
  if (admission.status === 'rejected') {
    throw new DesktopWorkspaceConversationCatalogAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireWorkspaceConversationCatalogServiceV2(candidate);
      const authority = requireWorkspaceConversationCatalogAuthorityV2(
        service.bindOperation(prepared.config),
      );
      return operation(
        createRevocableDesktopWorkspaceConversationCatalogAuthorityV2(
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

function createDesktopWorkspaceConversationCatalogAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceConversationCatalogAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const transport = new DesktopApiClient(operationConfig);
  return Object.freeze({
    listConversations(filters: DesktopWorkspaceConversationCatalogFiltersV2) {
      const preparedFilters = prepareWorkspaceConversationCatalogFiltersV2(filters);
      return transport
        .listConversations(operationConfig.projectId, {
          workspaceId: preparedFilters.workspaceId,
          unboundOnly: preparedFilters.unboundOnly,
          ...(preparedFilters.signal === undefined ? {} : { signal: preparedFilters.signal }),
        })
        .then((value) =>
          assertWorkspaceConversationCatalogResponseV2(value, operationConfig, preparedFilters),
        );
    },
  });
}

function createRevocableDesktopWorkspaceConversationCatalogAuthorityV2(
  authority: DesktopWorkspaceConversationCatalogAuthorityV2,
  expected: PreparedWorkspaceConversationCatalogOperationV2,
  isOperationActive: () => boolean,
): DesktopWorkspaceConversationCatalogAuthorityV2 {
  return Object.freeze({
    listConversations(filters: DesktopWorkspaceConversationCatalogFiltersV2) {
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          'desktop_workspace_conversation_catalog_operation_released',
          'desktop workspace conversation catalog operation has been released',
        );
      }
      const preparedFilters = prepareWorkspaceConversationCatalogFiltersV2(filters);
      if (
        preparedFilters.workspaceId !== expected.filters.workspaceId ||
        preparedFilters.unboundOnly !== expected.filters.unboundOnly ||
        preparedFilters.signal !== expected.filters.signal
      ) {
        throw invalidWorkspaceConversationCatalogInputV2();
      }
      return Promise.resolve(authority.listConversations(preparedFilters)).then((value) =>
        assertWorkspaceConversationCatalogResponseV2(value, expected.config, expected.filters),
      );
    },
  });
}

function prepareWorkspaceConversationCatalogOperationV2(
  input: DesktopWorkspaceConversationCatalogOperationInputV2,
): PreparedWorkspaceConversationCatalogOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasExactOptionalKeysV2(input, OPERATION_INPUT_KEYS_V2) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'workspaceId') ||
    !Object.hasOwn(input, 'unboundOnly')
  ) {
    throw invalidWorkspaceConversationCatalogInputV2();
  }
  return Object.freeze({
    config: cloneDesktopRuntimeConfigV2(input.config),
    filters: prepareWorkspaceConversationCatalogFiltersV2({
      workspaceId: input.workspaceId,
      unboundOnly: input.unboundOnly,
      ...(input.signal === undefined ? {} : { signal: input.signal }),
    }),
  });
}

function prepareWorkspaceConversationCatalogFiltersV2(
  filters: DesktopWorkspaceConversationCatalogFiltersV2,
): DesktopWorkspaceConversationCatalogFiltersV2 {
  if (
    !isPlainRecordV2(filters) ||
    !hasExactOptionalKeysV2(filters, FILTER_KEYS_V2) ||
    !Object.hasOwn(filters, 'workspaceId') ||
    !Object.hasOwn(filters, 'unboundOnly') ||
    (filters.workspaceId !== null && !isCanonicalStringV2(filters.workspaceId)) ||
    typeof filters.unboundOnly !== 'boolean' ||
    (filters.workspaceId !== null && filters.unboundOnly)
  ) {
    throw invalidWorkspaceConversationCatalogInputV2();
  }
  const signal = cloneOptionalSignalV2(filters.signal);
  return Object.freeze({
    workspaceId: filters.workspaceId,
    unboundOnly: filters.unboundOnly,
    ...(signal === undefined ? {} : { signal }),
  });
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidWorkspaceConversationCatalogInputV2();
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
    throw invalidWorkspaceConversationCatalogInputV2();
  }
  return Object.freeze(copy);
}

function cloneOptionalSignalV2(value: unknown): AbortSignal | undefined {
  if (value === undefined) return undefined;
  if (typeof AbortSignal === 'undefined' || !(value instanceof AbortSignal)) {
    throw invalidWorkspaceConversationCatalogInputV2();
  }
  return value;
}

function assertWorkspaceConversationCatalogResponseV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  filters: DesktopWorkspaceConversationCatalogFiltersV2,
): PaginatedConversationsResponse {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, RESPONSE_KEYS_V2) ||
    !Array.isArray(value.items) ||
    !isUnsignedSafeIntegerV2(value.total) ||
    value.total !== value.items.length ||
    value.has_more !== false ||
    value.offset !== 0 ||
    value.limit !== 500 ||
    value.next_offset !== null
  ) {
    throw invalidWorkspaceConversationCatalogResponseV2();
  }
  const seenIds = new Set<string>();
  const items = value.items.map((item) => cloneConversationV2(item, config, filters, seenIds));
  Object.freeze(items);
  return Object.freeze({
    items,
    total: value.total,
    has_more: false,
    offset: 0,
    limit: 500,
    next_offset: null,
  });
}

function cloneConversationV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  filters: DesktopWorkspaceConversationCatalogFiltersV2,
  seenIds: Set<string>,
): AgentConversation {
  if (
    !isPlainRecordV2(value) ||
    !hasRequiredAndOptionalKeysV2(
      value,
      CONVERSATION_REQUIRED_KEYS_V2,
      CONVERSATION_OPTIONAL_KEYS_V2,
    ) ||
    !isCanonicalStringV2(value.id) ||
    seenIds.has(value.id) ||
    value.tenant_id !== config.tenantId ||
    value.project_id !== config.projectId ||
    !isCanonicalStringV2(value.user_id) ||
    !isCanonicalStringV2(value.title) ||
    value.status !== 'active' ||
    !isUnsignedSafeIntegerV2(value.message_count) ||
    !isCanonicalStringV2(value.created_at) ||
    !isOptionalNullableCanonicalStringV2(value.updated_at) ||
    !isOptionalNullableCanonicalStringV2(value.summary) ||
    !isOptionalNullableJsonRecordV2(value.agent_config) ||
    !isOptionalNullableJsonRecordV2(value.metadata) ||
    !isOptionalNullableCanonicalStringV2(value.conversation_mode) ||
    !isOptionalNullableCanonicalStringV2(value.current_mode) ||
    !isOptionalNullableCanonicalStringV2(value.workspace_id) ||
    !isOptionalNullableCanonicalStringV2(value.linked_workspace_task_id) ||
    !isOptionalNullableCanonicalStringV2(value.workspace_name) ||
    !isOptionalCanonicalStringArrayV2(value.participant_agents) ||
    !isOptionalNullableCanonicalStringV2(value.coordinator_agent_id) ||
    !isOptionalNullableCanonicalStringV2(value.focused_agent_id) ||
    (filters.workspaceId !== null && value.workspace_id !== filters.workspaceId) ||
    (filters.unboundOnly && value.workspace_id !== null)
  ) {
    throw invalidWorkspaceConversationCatalogResponseV2();
  }
  seenIds.add(value.id);
  const copy: AgentConversation = {
    id: value.id,
    tenant_id: config.tenantId,
    project_id: config.projectId,
    user_id: value.user_id,
    title: value.title,
    status: 'active',
    message_count: value.message_count,
    created_at: value.created_at,
    ...(value.updated_at === undefined ? {} : { updated_at: value.updated_at }),
    ...(value.summary === undefined ? {} : { summary: value.summary }),
    ...(value.agent_config === undefined
      ? {}
      : { agent_config: cloneOptionalJsonRecordV2(value.agent_config) }),
    ...(value.metadata === undefined
      ? {}
      : { metadata: cloneOptionalJsonRecordV2(value.metadata) }),
    ...(value.conversation_mode === undefined
      ? {}
      : { conversation_mode: value.conversation_mode }),
    ...(value.current_mode === undefined
      ? {}
      : { current_mode: value.current_mode as AgentConversation['current_mode'] }),
    ...(value.workspace_id === undefined ? {} : { workspace_id: value.workspace_id }),
    ...(value.linked_workspace_task_id === undefined
      ? {}
      : { linked_workspace_task_id: value.linked_workspace_task_id }),
    ...(value.workspace_name === undefined ? {} : { workspace_name: value.workspace_name }),
    ...(value.participant_agents === undefined
      ? {}
      : { participant_agents: Object.freeze([...value.participant_agents]) as string[] }),
    ...(value.coordinator_agent_id === undefined
      ? {}
      : { coordinator_agent_id: value.coordinator_agent_id }),
    ...(value.focused_agent_id === undefined ? {} : { focused_agent_id: value.focused_agent_id }),
  };
  return Object.freeze(copy);
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
  if (ancestors.has(value)) throw invalidWorkspaceConversationCatalogResponseV2();
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
    if (ancestors.has(value)) throw invalidWorkspaceConversationCatalogResponseV2();
    ancestors.add(value);
    const copy = value.map((entry) => cloneJsonValueV2(entry, ancestors));
    ancestors.delete(value);
    return Object.freeze(copy);
  }
  if (isPlainRecordV2(value)) return cloneJsonRecordV2(value, ancestors);
  throw invalidWorkspaceConversationCatalogResponseV2();
}

function requireWorkspaceConversationCatalogServiceV2(
  value: unknown,
): DesktopWorkspaceConversationCatalogAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, new Set(['bindOperation'])) ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidWorkspaceConversationCatalogServiceV2();
  }
  return value as unknown as DesktopWorkspaceConversationCatalogAuthorityServiceV2;
}

function requireWorkspaceConversationCatalogAuthorityV2(
  value: unknown,
): DesktopWorkspaceConversationCatalogAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, new Set(['listConversations'])) ||
    typeof value.listConversations !== 'function'
  ) {
    throw invalidWorkspaceConversationCatalogServiceV2();
  }
  return value as unknown as DesktopWorkspaceConversationCatalogAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopWorkspaceConversationCatalogAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidWorkspaceConversationCatalogInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_conversation_catalog_input_invalid',
    'desktop workspace conversation catalog operation input is invalid',
  );
}

function invalidWorkspaceConversationCatalogResponseV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_conversation_catalog_response_invalid',
    'desktop workspace conversation catalog response is invalid',
  );
}

function invalidWorkspaceConversationCatalogServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_conversation_catalog_service_invalid',
    'desktop workspace conversation catalog authority service is invalid',
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

function isUnsignedSafeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isOptionalNullableCanonicalStringV2(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || isCanonicalStringV2(value);
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

function isOptionalCanonicalStringArrayV2(value: unknown): value is string[] | undefined {
  return value === undefined || (Array.isArray(value) && value.every(isCanonicalStringV2));
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref === DESKTOP_WORKSPACE_CONVERSATION_CATALOG_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_workspace_conversation_catalog_authority_catalog_missing',
      'desktop workspace conversation catalog authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
