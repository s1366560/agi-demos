import { DesktopApiError } from '../api/client';
import type { DesktopRuntimeConfig, ManagedSkill, ManagedSkillContent } from '../types';
import {
  NativeRouteClientError,
  requestNativeRouteJson,
} from '../features/settings-routes/nativeRouteHttpClient';
import { requireTenantManagementScope } from '../features/tenant-admin/tenantManagementHttp';
import type {
  DesktopTenantSkillDefinitionsAuthorityV2,
  DesktopTenantSkillDefinitionsScopeV2,
} from './desktopTenantSkillDefinitionsOperationContractV2';
const LOCAL_REASON = 'local_skill_definition_authority_unavailable';
class DesktopTenantSkillDefinitionsHttpErrorV2 extends DesktopApiError {
  readonly reasonCode: string;
  constructor(reasonCode: string, status: number, payload: unknown = null) {
    super(reasonCode, status, payload);
    this.name = 'DesktopTenantSkillDefinitionsHttpErrorV2';
    this.reasonCode = reasonCode;
  }
}
export function createDesktopTenantSkillDefinitionsHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopTenantSkillDefinitionsAuthorityV2 {
  const runtime = Object.freeze({ ...config });
  const scopeParams = (scope: DesktopTenantSkillDefinitionsScopeV2) => {
    requireTenantManagementScope(runtime, scope, 'native_equivalent', LOCAL_REASON);
    if (
      scope.projectId !== null &&
      (!scope.projectId ||
        scope.projectId !== scope.projectId.trim() ||
        (runtime.mode === 'local' && scope.projectId !== runtime.projectId))
    )
      throw new DesktopTenantSkillDefinitionsHttpErrorV2(
        'tenant_skill_definitions_project_scope_invalid',
        409,
      );
    return new URLSearchParams({ tenant_id: scope.tenantId });
  };
  const authority: DesktopTenantSkillDefinitionsAuthorityV2 = {
    async load(scope, signal) {
      scopeParams(scope);
      const params = new URLSearchParams({ limit: '100', tenant_id: scope.tenantId });
      if (scope.projectId !== null) params.set('project_id', scope.projectId);
      const payload = await request(runtime, `/api/v1/skills/?${params}`, { signal });
      return readCollection(payload) as readonly ManagedSkill[];
    },
    async create(scope, input, signal) {
      const params = scopeParams(scope);
      return (await request(runtime, `/api/v1/skills/?${params}`, {
        method: 'POST',
        body: mutation(runtime, input, 0, crypto.randomUUID()),
        signal,
      })) as ManagedSkill;
    },
    async getContent(scope, id, signal) {
      const params = scopeParams(scope);
      return (await request(runtime, `${itemPath(id)}/content?${params}`, {
        signal,
      })) as ManagedSkillContent;
    },
    async update(scope, id, input, revision, signal) {
      const params = scopeParams(scope);
      return (await request(runtime, `${itemPath(id)}?${params}`, {
        method: 'PUT',
        body: mutation(runtime, input, revision),
        signal,
      })) as ManagedSkill;
    },
    async updateContent(scope, id, fullContent, revision, signal) {
      const params = scopeParams(scope);
      return (await request(runtime, `${itemPath(id)}/content?${params}`, {
        method: 'PUT',
        body: mutation(runtime, { full_content: fullContent }, revision),
        signal,
      })) as ManagedSkill;
    },
    async setStatus(scope, id, status, revision, signal) {
      scopeParams(scope);
      const params = new URLSearchParams({ status, tenant_id: scope.tenantId });
      return (await request(runtime, `${itemPath(id)}/status?${params}`, {
        method: 'PATCH',
        ...(runtime.mode === 'local' ? { body: mutation(runtime, { status }, revision) } : {}),
        signal,
      })) as ManagedSkill;
    },
    async delete(scope, id, revision, signal) {
      const params = scopeParams(scope);
      const payload = await request(runtime, `${itemPath(id)}?${params}`, {
        method: 'DELETE',
        ...(runtime.mode === 'local' ? { body: mutation(runtime, null, revision) } : {}),
        signal,
      });
      if (
        runtime.mode === 'cloud'
          ? payload !== null
          : !record(payload) || payload.deleted !== true || payload.id !== id
      )
        throw new DesktopTenantSkillDefinitionsHttpErrorV2(
          'tenant_skill_definitions_delete_response_invalid',
          502,
        );
    },
  };
  return Object.freeze(authority);
}
async function request(
  config: DesktopRuntimeConfig,
  path: string,
  options: Readonly<{
    method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
    body?: unknown;
    signal?: AbortSignal;
  }>,
): Promise<unknown> {
  try {
    return await requestNativeRouteJson(config, path, options);
  } catch (error) {
    if (error instanceof NativeRouteClientError) {
      const reason =
        config.mode === 'local' && (error.status === 404 || error.status === 501)
          ? LOCAL_REASON
          : error.reasonCode;
      throw new DesktopTenantSkillDefinitionsHttpErrorV2(reason, error.status, error.payload);
    }
    throw error;
  }
}
function mutation(
  config: DesktopRuntimeConfig,
  value: unknown,
  expectedRevision: number | undefined,
  resourceId?: string,
): unknown {
  if (config.mode === 'cloud') return value;
  if (!Number.isSafeInteger(expectedRevision) || Number(expectedRevision) < 0)
    throw new DesktopTenantSkillDefinitionsHttpErrorV2('managed_resource_revision_required', 428, {
      code: 'managed_resource_revision_required',
    });
  return Object.freeze({
    contract_version: 2,
    expected_revision: expectedRevision,
    idempotency_key: crypto.randomUUID(),
    ...(resourceId === undefined ? {} : { resource_id: resourceId }),
    value,
    vault_refs: Object.freeze([]),
  });
}
function itemPath(id: string): string {
  return `/api/v1/skills/${encodeURIComponent(id)}`;
}
function readCollection(value: unknown): readonly unknown[] {
  if (Array.isArray(value)) return value;
  if (record(value))
    for (const key of ['skills', 'items', 'data']) {
      if (!Object.hasOwn(value, key)) continue;
      if (Array.isArray(value[key])) return value[key];
      break;
    }
  throw new DesktopTenantSkillDefinitionsHttpErrorV2(
    'tenant_skill_definitions_collection_contract_invalid',
    502,
  );
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
