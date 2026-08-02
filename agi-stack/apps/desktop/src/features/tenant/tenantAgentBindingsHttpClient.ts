import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  CreateTenantAgentBindingInput,
  TenantAgentBinding,
  TenantAgentBindingDefinition,
  TenantAgentBindingsAction,
  TenantAgentBindingsAvailability,
  TenantAgentBindingsClient,
  TenantAgentBindingsListQuery,
  TenantAgentBindingsMutationOptions,
  TenantAgentBindingsReadOptions,
  TenantAgentBindingsScope,
  TenantAgentBindingsSnapshot,
  TestTenantAgentBindingInput,
} from './tenantAgentBindingsClient';

const CONTRACT_VERSION = '3.0.0';
const READ_ACTIONS = Object.freeze<TenantAgentBindingsAction[]>([
  'view',
  'list',
]);
const MUTATION_ACTIONS = Object.freeze<TenantAgentBindingsAction[]>([
  'create',
  'delete',
  'set-enabled',
]);

export function createTenantAgentBindingsHttpClient(
  config: DesktopRuntimeConfig,
): TenantAgentBindingsClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async list(scope, query, options) {
      requireRuntimeScope(runtimeConfig, scope);
      if (runtimeConfig.mode === 'local') {
        const payload = await requestJson(
          runtimeConfig,
          bindingListPath(scope, query),
          { method: 'GET', signal: options?.signal },
        );
        return projectLocalSnapshot(payload, scope);
      }
      const [bindings, definitions, workspaceContext] = await Promise.all([
        requestJson(runtimeConfig, bindingListPath(scope, query), {
          method: 'GET',
          signal: options?.signal,
        }),
        requestJson(
          runtimeConfig,
          `/api/v1/agent/definitions?${new URLSearchParams({
            tenant_id: scope.tenantId,
            scope: 'tenant',
            enabled_only: 'true',
            limit: '100',
          })}`,
          { method: 'GET', signal: options?.signal },
        ),
        requestJson(runtimeConfig, '/api/v1/workspace-context', {
          method: 'GET',
          signal: options?.signal,
        }),
      ]);
      return projectCloudSnapshot(
        bindings,
        definitions,
        workspaceContext,
        scope,
      );
    },
    async create(scope, input, options) {
      requireRuntimeScope(runtimeConfig, scope);
      const payload = await requestJson(
        runtimeConfig,
        tenantMutationPath('/api/v1/agent/bindings', scope),
        {
          method: 'POST',
          body: createBindingBody(input),
          idempotencyKey: options?.idempotencyKey,
          signal: options?.signal,
        },
      );
      return readBinding(payload, scope, new Map(), contractReason(runtimeConfig));
    },
    async delete(scope, bindingId, options) {
      requireRuntimeScope(runtimeConfig, scope);
      requireIdentifier(bindingId, 'tenant_agent_binding_id_invalid');
      const payload = await requestJson(
        runtimeConfig,
        tenantMutationPath(
          `/api/v1/agent/bindings/${encodeURIComponent(bindingId)}`,
          scope,
        ),
        {
          method: 'DELETE',
          idempotencyKey: options?.idempotencyKey,
          signal: options?.signal,
        },
      );
      if (
        !isRecord(payload) ||
        payload.deleted !== true ||
        payload.id !== bindingId
      ) {
        throw contractError(contractReason(runtimeConfig));
      }
    },
    async setEnabled(scope, bindingId, enabled, options) {
      requireRuntimeScope(runtimeConfig, scope);
      requireIdentifier(bindingId, 'tenant_agent_binding_id_invalid');
      const payload = await requestJson(
        runtimeConfig,
        tenantMutationPath(
          `/api/v1/agent/bindings/${encodeURIComponent(bindingId)}/enabled`,
          scope,
        ),
        {
          method: 'PATCH',
          body: { enabled },
          idempotencyKey: options?.idempotencyKey,
          signal: options?.signal,
        },
      );
      return readBinding(payload, scope, new Map(), contractReason(runtimeConfig));
    },
    async test(scope, input, options) {
      requireRuntimeScope(runtimeConfig, scope);
      const payload = await requestJson(
        runtimeConfig,
        tenantMutationPath('/api/v1/agent/bindings/test', scope),
        {
          method: 'POST',
          body: testBindingBody(input),
          idempotencyKey: options?.idempotencyKey,
          signal: options?.signal,
        },
      );
      return readTestResult(payload, contractReason(runtimeConfig));
    },
  });
}

type RequestOptions = Readonly<{
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: Readonly<Record<string, unknown>>;
  idempotencyKey?: string;
  signal?: AbortSignal;
}>;

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  options: RequestOptions,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  if (options.idempotencyKey) {
    headers.set('Idempotency-Key', options.idempotencyKey);
  }
  const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
    method: options.method,
    headers,
    body:
      options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(
      errorMessage(response.status, payload),
      response.status,
      payload,
    );
  }
  if (!isJson || payload === null) {
    throw contractError(contractReason(config));
  }
  return payload;
}

function projectCloudSnapshot(
  rawBindings: unknown,
  rawDefinitions: unknown,
  rawContext: unknown,
  scope: TenantAgentBindingsScope,
): TenantAgentBindingsSnapshot {
  const reason = 'cloud_tenant_agent_bindings_contract_invalid';
  if (!Array.isArray(rawBindings)) throw contractError(reason);
  const definitions = readDefinitions(rawDefinitions, scope, reason);
  const definitionNames = new Map(
    definitions.map((definition) => [definition.id, definition.displayName]),
  );
  const authority = readCloudAuthority(rawContext, scope, reason);
  const allowedActions = [
    ...READ_ACTIONS,
    ...(authority.canManage ? MUTATION_ACTIONS : []),
    'test' as const,
  ];
  return Object.freeze({
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: CONTRACT_VERSION,
    allowedActions: Object.freeze(allowedActions),
    authorityRevision: authority.revision,
    bindings: Object.freeze(
      rawBindings.map((binding) =>
        readBinding(binding, scope, definitionNames, reason),
      ),
    ),
    definitions,
  });
}

function projectLocalSnapshot(
  payload: unknown,
  scope: TenantAgentBindingsScope,
): TenantAgentBindingsSnapshot {
  const reason = 'local_tenant_agent_bindings_contract_invalid';
  if (
    !isRecord(payload) ||
    payload.capability !== 'tenant_agent_bindings' ||
    !isAvailability(payload.availability) ||
    !isNullableReason(payload.reason_code) ||
    !isNonEmptyString(payload.service_version) ||
    !isNonEmptyString(payload.contract_version) ||
    !isActionArray(payload.allowed_actions) ||
    !isRecord(payload.scope) ||
    payload.scope.tenant_id !== scope.tenantId ||
    payload.scope.project_id !== null ||
    payload.scope.workspace_id !== null ||
    payload.scope.instance_id !== null ||
    !isNonnegativeInteger(payload.authority_revision) ||
    !Array.isArray(payload.bindings) ||
    !Array.isArray(payload.definitions)
  ) {
    throw contractError(reason);
  }
  if (
    payload.availability === 'unavailable' &&
    (payload.allowed_actions.length !== 0 ||
      payload.bindings.length !== 0 ||
      payload.definitions.length !== 0)
  ) {
    throw contractError(reason);
  }
  const definitions = readDefinitions(payload.definitions, scope, reason);
  const definitionNames = new Map(
    definitions.map((definition) => [definition.id, definition.displayName]),
  );
  return Object.freeze({
    scope,
    authority: 'local',
    availability: payload.availability,
    reasonCode: payload.reason_code,
    serviceVersion: payload.service_version,
    contractVersion: payload.contract_version,
    allowedActions: Object.freeze([...payload.allowed_actions]),
    authorityRevision: payload.authority_revision,
    bindings: Object.freeze(
      payload.bindings.map((binding) =>
        readBinding(binding, scope, definitionNames, reason),
      ),
    ),
    definitions,
  });
}

function readDefinitions(
  payload: unknown,
  scope: TenantAgentBindingsScope,
  reason: string,
): readonly TenantAgentBindingDefinition[] {
  const values =
    Array.isArray(payload)
      ? payload
      : isRecord(payload) && Array.isArray(payload.definitions)
        ? payload.definitions
        : null;
  if (values === null) throw contractError(reason);
  return Object.freeze(
    values.map((value) => {
      if (
        !isRecord(value) ||
        !isNonEmptyString(value.id) ||
        value.tenant_id !== scope.tenantId ||
        value.project_id !== null ||
        !isNonEmptyString(value.name) ||
        !isNullableString(value.display_name) ||
        value.enabled !== true
      ) {
        throw contractError(reason);
      }
      return Object.freeze({
        id: value.id,
        name: value.name,
        displayName: value.display_name?.trim() || value.name,
      });
    }),
  );
}

function readBinding(
  payload: unknown,
  scope: TenantAgentBindingsScope,
  definitionNames: ReadonlyMap<string, string>,
  reason: string,
): TenantAgentBinding {
  if (
    !isRecord(payload) ||
    !isNonEmptyString(payload.id) ||
    payload.tenant_id !== scope.tenantId ||
    !isNonEmptyString(payload.agent_id) ||
    !isNullableString(payload.channel_type) ||
    !isNullableString(payload.channel_id) ||
    !isNullableString(payload.account_id) ||
    !isNullableString(payload.peer_id) ||
    !isNullableString(payload.group_id) ||
    !isInteger(payload.priority) ||
    typeof payload.enabled !== 'boolean' ||
    !isNonEmptyString(payload.created_at) ||
    !isNonnegativeInteger(payload.specificity_score)
  ) {
    throw contractError(reason);
  }
  return Object.freeze({
    id: payload.id,
    tenantId: scope.tenantId,
    agentId: payload.agent_id,
    agentName: definitionNames.get(payload.agent_id) ?? payload.agent_id,
    channelType: payload.channel_type,
    channelId: payload.channel_id,
    accountId: payload.account_id,
    peerId: payload.peer_id,
    groupId: payload.group_id,
    priority: payload.priority,
    enabled: payload.enabled,
    createdAt: payload.created_at,
    specificityScore: payload.specificity_score,
  });
}

function readTestResult(payload: unknown, reason: string) {
  if (
    !isRecord(payload) ||
    !isNullableString(payload.agent_id) ||
    !isNullableString(payload.agent_name) ||
    !isNullableString(payload.binding_id) ||
    !isNonnegativeInteger(payload.specificity_score) ||
    !isFiniteUnitNumber(payload.confidence) ||
    typeof payload.matched !== 'boolean' ||
    !Array.isArray(payload.trace)
  ) {
    throw contractError(reason);
  }
  return Object.freeze({
    agentId: payload.agent_id,
    agentName: payload.agent_name,
    bindingId: payload.binding_id,
    specificityScore: payload.specificity_score,
    confidence: payload.confidence,
    matched: payload.matched,
    trace: Object.freeze(
      payload.trace.map((entry) => {
        if (
          !isRecord(entry) ||
          !isNonEmptyString(entry.binding_id) ||
          !isNonEmptyString(entry.agent_id) ||
          !isNonnegativeInteger(entry.specificity_score) ||
          !isNullableString(entry.channel_type) ||
          !isNullableString(entry.channel_id) ||
          !isNullableString(entry.account_id) ||
          !isNullableString(entry.peer_id) ||
          !isInteger(entry.priority) ||
          typeof entry.eliminated !== 'boolean' ||
          !isNullableString(entry.elimination_reason) ||
          typeof entry.selected !== 'boolean'
        ) {
          throw contractError(reason);
        }
        return Object.freeze({
          bindingId: entry.binding_id,
          agentId: entry.agent_id,
          specificityScore: entry.specificity_score,
          channelType: entry.channel_type,
          channelId: entry.channel_id,
          accountId: entry.account_id,
          peerId: entry.peer_id,
          priority: entry.priority,
          eliminated: entry.eliminated,
          eliminationReason: entry.elimination_reason,
          selected: entry.selected,
        });
      }),
    ),
  });
}

function readCloudAuthority(
  payload: unknown,
  scope: TenantAgentBindingsScope,
  reason: string,
): Readonly<{ revision: number; canManage: boolean }> {
  if (
    !isRecord(payload) ||
    !isRecord(payload.context) ||
    payload.context.tenant_id !== scope.tenantId ||
    !isNonnegativeInteger(payload.context.revision) ||
    !isNonEmptyString(payload.membership_role)
  ) {
    throw contractError(reason);
  }
  return Object.freeze({
    revision: payload.context.revision,
    canManage:
      payload.membership_role === 'admin' ||
      payload.membership_role === 'owner',
  });
}

function bindingListPath(
  scope: TenantAgentBindingsScope,
  query?: TenantAgentBindingsListQuery,
): string {
  const params = new URLSearchParams({ tenant_id: scope.tenantId });
  if (query?.agentId) params.set('agent_id', query.agentId);
  if (query?.enabledOnly !== undefined) {
    params.set('enabled_only', String(query.enabledOnly));
  }
  return `/api/v1/agent/bindings?${params}`;
}

function tenantMutationPath(
  path: string,
  scope: TenantAgentBindingsScope,
): string {
  return `${path}?${new URLSearchParams({ tenant_id: scope.tenantId })}`;
}

function createBindingBody(
  input: CreateTenantAgentBindingInput,
): Readonly<Record<string, unknown>> {
  requireIdentifier(input.agentId, 'tenant_agent_binding_agent_id_invalid');
  if (!isInteger(input.priority)) {
    throw contractError('tenant_agent_binding_priority_invalid');
  }
  return compact({
    agent_id: input.agentId,
    channel_type: optionalValue(input.channelType),
    channel_id: optionalValue(input.channelId),
    account_id: optionalValue(input.accountId),
    peer_id: optionalValue(input.peerId),
    group_id: optionalValue(input.groupId),
    priority: input.priority,
  });
}

function testBindingBody(
  input: TestTenantAgentBindingInput,
): Readonly<Record<string, unknown>> {
  requireIdentifier(
    input.channelType,
    'tenant_agent_binding_channel_type_invalid',
  );
  return compact({
    channel_type: input.channelType,
    channel_id: optionalValue(input.channelId),
    account_id: optionalValue(input.accountId),
    peer_id: optionalValue(input.peerId),
  });
}

function compact(
  input: Readonly<Record<string, unknown>>,
): Readonly<Record<string, unknown>> {
  return Object.freeze(
    Object.fromEntries(
      Object.entries(input).filter(([, value]) => value !== undefined),
    ),
  );
}

function optionalValue(value: string | null): string | undefined {
  return value?.trim() || undefined;
}

function requireRuntimeScope(
  config: DesktopRuntimeConfig,
  scope: TenantAgentBindingsScope,
): void {
  if (
    !isRecord(scope) ||
    scope.authority !== config.mode ||
    !isNonEmptyString(scope.tenantId) ||
    scope.tenantId !== config.tenantId
  ) {
    throw contractError('tenant_agent_bindings_runtime_scope_mismatch');
  }
}

function requireIdentifier(value: unknown, reason: string): asserts value is string {
  if (!isNonEmptyString(value)) throw contractError(reason);
}

function contractReason(config: DesktopRuntimeConfig): string {
  return `${config.mode}_tenant_agent_bindings_contract_invalid`;
}

function contractError(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  return `Tenant agent bindings request failed (${status})`;
}

function isAvailability(
  value: unknown,
): value is TenantAgentBindingsAvailability {
  return (
    value === 'available' ||
    value === 'degraded' ||
    value === 'unavailable' ||
    value === 'not_applicable'
  );
}

function isActionArray(value: unknown): value is TenantAgentBindingsAction[] {
  return (
    Array.isArray(value) &&
    value.every(
      (action) =>
        action === 'view' ||
        action === 'list' ||
        action === 'create' ||
        action === 'delete' ||
        action === 'set-enabled' ||
        action === 'test',
    )
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNullableReason(value: unknown): value is string | null {
  return value === null || isNonEmptyString(value);
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

function isFiniteUnitNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
}
