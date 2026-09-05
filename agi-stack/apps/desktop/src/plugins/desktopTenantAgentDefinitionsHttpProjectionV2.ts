import type {
  DesktopRuntimeConfig,
  ManagedAgentDefinition,
  ManagedAgentDefinitionMutation,
  ManagedExternalAcpAgent,
} from '../types';
import { DesktopApiError } from '../api/client';
import {
  requestTenantManagementJson,
  requireTenantManagementScope,
  type TenantManagementRequestOptions,
} from '../features/tenant-admin/tenantManagementHttp';
import type {
  DesktopTenantAgentDefinitionsAuthorityV2,
  DesktopTenantAgentDefinitionsScopeV2,
} from './desktopTenantAgentDefinitionsOperationContractV2';

const LOCAL_AUTHORITY_UNAVAILABLE = 'local_agent_definition_authority_unavailable';
const LOCAL_EXTERNAL_UNAVAILABLE = 'local_external_acp_registry_unavailable';

class DesktopTenantAgentDefinitionsHttpErrorV2 extends DesktopApiError {
  readonly reasonCode: string;

  constructor(reasonCode: string, status: number, payload: unknown) {
    super(reasonCode, status, payload);
    this.name = 'DesktopTenantAgentDefinitionsHttpErrorV2';
    this.reasonCode = reasonCode;
  }
}

export function createDesktopTenantAgentDefinitionsHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopTenantAgentDefinitionsAuthorityV2 {
  const runtimeConfig = Object.freeze({ ...config });
  const authority: DesktopTenantAgentDefinitionsAuthorityV2 = {
    async load(scope, signal) {
      const currentScope = requireScope(runtimeConfig, scope);
      const params = new URLSearchParams({ limit: '100', enabled_only: 'false' });
      if (currentScope.projectId !== null) params.set('project_id', currentScope.projectId);
      params.set('tenant_id', currentScope.tenantId);
      const payload = await request(
        runtimeConfig,
        `/api/v1/agent/definitions?${params.toString()}`,
        { signal },
        LOCAL_AUTHORITY_UNAVAILABLE,
      );
      return readDefinitions(payload);
    },
    async listExternal(scope, signal) {
      const currentScope = requireScope(runtimeConfig, scope);
      if (currentScope.projectId !== null) {
        throw projectionError('tenant_agent_definitions_external_scope_invalid', 422);
      }
      const payload = await request(
        runtimeConfig,
        `/api/v1/acp/tenants/${encodeURIComponent(currentScope.tenantId)}/external-agents`,
        { signal },
        LOCAL_EXTERNAL_UNAVAILABLE,
      );
      return readExternalAgents(payload);
    },
    async create(scope, input, signal) {
      const currentScope = requireScope(runtimeConfig, scope);
      const payload = await request(
        runtimeConfig,
        `/api/v1/agent/definitions?${tenantParams(currentScope)}`,
        {
          method: 'POST',
          body: mutationBody(runtimeConfig, input, 0, crypto.randomUUID()),
          signal,
        },
        LOCAL_AUTHORITY_UNAVAILABLE,
      );
      return payload as ManagedAgentDefinition;
    },
    async update(scope, definitionId, input, expectedRevision, signal) {
      const currentScope = requireScope(runtimeConfig, scope);
      const payload = await request(
        runtimeConfig,
        `${definitionPath(definitionId)}?${tenantParams(currentScope)}`,
        {
          method: 'PUT',
          body: mutationBody(runtimeConfig, input, expectedRevision),
          signal,
        },
        LOCAL_AUTHORITY_UNAVAILABLE,
      );
      return payload as ManagedAgentDefinition;
    },
    async setEnabled(scope, definitionId, enabled, expectedRevision, signal) {
      const currentScope = requireScope(runtimeConfig, scope);
      const params = new URLSearchParams({ tenant_id: currentScope.tenantId });
      if (currentScope.projectId !== null) params.set('project_id', currentScope.projectId);
      const payload = await request(
        runtimeConfig,
        `${definitionPath(definitionId)}/enabled?${params.toString()}`,
        {
          method: 'PATCH',
          body: mutationBody(runtimeConfig, Object.freeze({ enabled }), expectedRevision),
          signal,
        },
        LOCAL_AUTHORITY_UNAVAILABLE,
      );
      return payload as ManagedAgentDefinition;
    },
    async delete(scope, definitionId, expectedRevision, signal) {
      const currentScope = requireScope(runtimeConfig, scope);
      const payload = await request(
        runtimeConfig,
        `${definitionPath(definitionId)}?${tenantParams(currentScope)}`,
        {
          method: 'DELETE',
          ...(runtimeConfig.mode === 'local'
            ? { body: mutationBody(runtimeConfig, null, expectedRevision) }
            : {}),
          signal,
        },
        LOCAL_AUTHORITY_UNAVAILABLE,
      );
      return payload as Readonly<{ deleted: true; id: string }>;
    },
  };
  return Object.freeze(authority);
}

function requireScope(
  config: DesktopRuntimeConfig,
  scope: DesktopTenantAgentDefinitionsScopeV2,
): DesktopTenantAgentDefinitionsScopeV2 {
  requireTenantManagementScope(
    config,
    scope,
    'native_equivalent',
    LOCAL_AUTHORITY_UNAVAILABLE,
  );
  if (
    scope.projectId !== null &&
    (scope.projectId.length === 0 ||
      scope.projectId !== scope.projectId.trim() ||
      scope.projectId !== config.projectId)
  ) {
    throw projectionError('tenant_agent_definitions_project_scope_mismatch', 409);
  }
  return scope;
}

async function request(
  config: DesktopRuntimeConfig,
  path: string,
  options: TenantManagementRequestOptions &
    Readonly<{
      method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
      body?: Readonly<Record<string, unknown>>;
    }>,
  localReasonCode: string,
): Promise<unknown> {
  try {
    return await requestTenantManagementJson(config, path, options);
  } catch (error) {
    if (
      config.mode === 'local' &&
      error instanceof DesktopApiError &&
      (error.status === 404 || error.status === 501)
    ) {
      throw projectionError(localReasonCode, error.status, error.payload);
    }
    throw error;
  }
}

function mutationBody(
  config: DesktopRuntimeConfig,
  value: Readonly<Record<string, unknown>> | null,
  expectedRevision: number | undefined,
  resourceId?: string,
): Readonly<Record<string, unknown>> {
  if (config.mode === 'cloud') return value ?? Object.freeze({});
  if (!Number.isSafeInteger(expectedRevision) || Number(expectedRevision) < 0) {
    throw projectionError(
      'managed_resource_revision_required',
      428,
      Object.freeze({ code: 'managed_resource_revision_required' }),
    );
  }
  return Object.freeze({
    contract_version: 2,
    expected_revision: expectedRevision,
    idempotency_key: crypto.randomUUID(),
    ...(resourceId === undefined ? {} : { resource_id: resourceId }),
    value,
    vault_refs: Object.freeze([]),
  });
}

function readDefinitions(payload: unknown): readonly ManagedAgentDefinition[] {
  const value = readCollection(payload, ['definitions', 'items', 'data']);
  return Object.freeze([...value]) as readonly ManagedAgentDefinition[];
}

function readExternalAgents(payload: unknown): readonly ManagedExternalAcpAgent[] {
  const value = readCollection(payload, ['agents', 'items', 'externalAgents', 'data']);
  return Object.freeze([...value]) as readonly ManagedExternalAcpAgent[];
}

function readCollection(payload: unknown, keys: readonly string[]): readonly unknown[] {
  if (Array.isArray(payload)) return payload;
  if (record(payload)) {
    for (const key of keys) {
      if (!Object.hasOwn(payload, key)) continue;
      if (Array.isArray(payload[key])) return payload[key];
      break;
    }
  }
  throw projectionError(
    'tenant_agent_definitions_collection_contract_invalid',
    502,
  );
}

function tenantParams(scope: DesktopTenantAgentDefinitionsScopeV2): string {
  return new URLSearchParams({ tenant_id: scope.tenantId }).toString();
}

function definitionPath(definitionId: string): string {
  return `/api/v1/agent/definitions/${encodeURIComponent(definitionId)}`;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function projectionError(
  reasonCode: string,
  status: number,
  payload: unknown = null,
): DesktopTenantAgentDefinitionsHttpErrorV2 {
  return new DesktopTenantAgentDefinitionsHttpErrorV2(reasonCode, status, payload);
}
