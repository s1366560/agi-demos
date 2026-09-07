import type { DesktopRuntimeConfig, ManagedSubAgent } from '../types';
import { DesktopApiError } from '../api/client';
import {
  NativeRouteClientError,
  requestNativeRouteJson,
} from '../features/settings-routes/nativeRouteHttpClient';
import {
  requireTenantManagementScope,
  type TenantManagementRequestOptions,
} from '../features/tenant-admin/tenantManagementHttp';
import type {
  DesktopTenantSubAgentDefinitionsAuthorityV2,
  DesktopTenantSubAgentDefinitionsScopeV2,
} from './desktopTenantSubAgentDefinitionsOperationContractV2';

const LOCAL_AUTHORITY_UNAVAILABLE = 'local_subagent_definition_authority_unavailable';
const LOCAL_EXTERNAL_UNAVAILABLE = 'local_subagent_registry_unavailable';

class DesktopTenantSubAgentDefinitionsHttpErrorV2 extends DesktopApiError {
  readonly reasonCode: string;

  constructor(reasonCode: string, status: number, payload: unknown) {
    super(reasonCode, status, payload);
    this.name = 'DesktopTenantSubAgentDefinitionsHttpErrorV2';
    this.reasonCode = reasonCode;
  }
}

export function createDesktopTenantSubAgentDefinitionsHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopTenantSubAgentDefinitionsAuthorityV2 {
  const runtimeConfig = Object.freeze({ ...config });
  const authority: DesktopTenantSubAgentDefinitionsAuthorityV2 = {
    async load(scope, signal) {
      const currentScope = requireScope(runtimeConfig, scope);
      const params = new URLSearchParams({
        limit: '100',
        include_filesystem: 'true',
      });
      if (currentScope.projectId !== null) params.set('project_id', currentScope.projectId);
      params.set('tenant_id', currentScope.tenantId);
      const payload = await request(
        runtimeConfig,
        `/api/v1/subagents/?${params.toString()}`,
        { signal },
        LOCAL_AUTHORITY_UNAVAILABLE,
      );
      return readDefinitions(payload);
    },
    async importFilesystem(scope, name, signal) {
      const currentScope = requireScope(runtimeConfig, scope);
      if (runtimeConfig.mode === 'local') {
        throw projectionError(LOCAL_EXTERNAL_UNAVAILABLE, 501, {
          contract_version: 2,
          mode: 'local',
          capability: 'managed_subagents',
          availability: 'unavailable',
          reason_code: LOCAL_EXTERNAL_UNAVAILABLE,
          route: `/api/v1/subagents/filesystem/${encodeURIComponent(name)}/import`,
        });
      }
      const params = new URLSearchParams({ tenant_id: currentScope.tenantId });
      if (currentScope.projectId !== null) params.set('project_id', currentScope.projectId);
      return (await request(
        runtimeConfig,
        `/api/v1/subagents/filesystem/${encodeURIComponent(name)}/import?${params.toString()}`,
        { method: 'POST', signal },
        LOCAL_EXTERNAL_UNAVAILABLE,
      )) as ManagedSubAgent;
    },
    async create(scope, input, signal) {
      const currentScope = requireScope(runtimeConfig, scope);
      const payload = await request(
        runtimeConfig,
        `/api/v1/subagents/?${tenantParams(currentScope)}`,
        {
          method: 'POST',
          body: mutationBody(runtimeConfig, input, 0, crypto.randomUUID()),
          signal,
        },
        LOCAL_AUTHORITY_UNAVAILABLE,
      );
      return payload as ManagedSubAgent;
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
      return payload as ManagedSubAgent;
    },
    async setEnabled(scope, definitionId, enabled, expectedRevision, signal) {
      const currentScope = requireScope(runtimeConfig, scope);
      const params = new URLSearchParams({
        enabled: String(enabled),
        tenant_id: currentScope.tenantId,
      });
      const payload = await request(
        runtimeConfig,
        `${definitionPath(definitionId)}/enable?${params.toString()}`,
        {
          method: 'PATCH',
          ...(runtimeConfig.mode === 'local'
            ? {
                body: mutationBody(runtimeConfig, Object.freeze({ enabled }), expectedRevision),
              }
            : {}),
          signal,
        },
        LOCAL_AUTHORITY_UNAVAILABLE,
      );
      return payload as ManagedSubAgent;
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
      if (
        runtimeConfig.mode === 'cloud'
          ? payload !== null
          : !record(payload) || payload.deleted !== true || payload.id !== definitionId
      ) {
        throw projectionError('tenant_subagent_definitions_delete_response_invalid', 502);
      }
    },
  };
  return Object.freeze(authority);
}

function requireScope(
  config: DesktopRuntimeConfig,
  scope: DesktopTenantSubAgentDefinitionsScopeV2,
): DesktopTenantSubAgentDefinitionsScopeV2 {
  requireTenantManagementScope(config, scope, 'native_equivalent', LOCAL_AUTHORITY_UNAVAILABLE);
  if (
    scope.projectId !== null &&
    (scope.projectId.length === 0 ||
      scope.projectId !== scope.projectId.trim() ||
      (config.mode === 'local' && scope.projectId !== config.projectId))
  ) {
    throw projectionError('tenant_subagent_definitions_project_scope_mismatch', 409);
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
    return await requestNativeRouteJson(config, path, options);
  } catch (error) {
    if (
      config.mode === 'local' &&
      (error instanceof DesktopApiError || error instanceof NativeRouteClientError) &&
      (error.status === 404 || error.status === 501)
    ) {
      throw projectionError(localReasonCode, error.status, error.payload);
    }
    if (error instanceof NativeRouteClientError)
      throw projectionError(error.reasonCode, error.status, error.payload);
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

function readDefinitions(payload: unknown): readonly ManagedSubAgent[] {
  const value = readCollection(payload, ['subagents', 'items', 'data']);
  return Object.freeze([...value]) as readonly ManagedSubAgent[];
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
  throw projectionError('tenant_subagent_definitions_collection_contract_invalid', 502);
}

function tenantParams(scope: DesktopTenantSubAgentDefinitionsScopeV2): string {
  return new URLSearchParams({ tenant_id: scope.tenantId }).toString();
}

function definitionPath(definitionId: string): string {
  return `/api/v1/subagents/${encodeURIComponent(definitionId)}`;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function projectionError(
  reasonCode: string,
  status: number,
  payload: unknown = null,
): DesktopTenantSubAgentDefinitionsHttpErrorV2 {
  return new DesktopTenantSubAgentDefinitionsHttpErrorV2(reasonCode, status, payload);
}
