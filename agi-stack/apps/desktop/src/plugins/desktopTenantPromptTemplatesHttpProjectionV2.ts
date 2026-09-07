import type {
  DesktopRuntimeConfig,
  PromptTemplateCreateInput,
  PromptTemplateRecord,
} from '../types';
import {
  exactNativeRouteIdentifier,
  NativeRouteClientError,
  requestNativeRouteJson,
  requireRuntimeAuthority,
} from '../features/settings-routes/nativeRouteHttpClient';
import type {
  DesktopTenantPromptTemplatesAuthorityV2,
  DesktopTenantPromptTemplatesScopeV2,
} from './desktopTenantPromptTemplatesOperationContractV2';

export const DESKTOP_TENANT_PROMPT_TEMPLATES_LOCAL_REASON_V2 =
  'local_prompt_template_authority_unavailable';

export function createDesktopTenantPromptTemplatesHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopTenantPromptTemplatesAuthorityV2 {
  const runtime = Object.freeze({ ...config });
  const authority: DesktopTenantPromptTemplatesAuthorityV2 = {
    async list(scope: DesktopTenantPromptTemplatesScopeV2, signal?: AbortSignal) {
      const current = requireScope(runtime, scope);
      const path = `/api/v1/agent/templates?${listParams(current).toString()}`;
      return request(runtime, path, { signal }) as Promise<readonly PromptTemplateRecord[]>;
    },
    async create(
      scope: DesktopTenantPromptTemplatesScopeV2,
      input: PromptTemplateCreateInput,
      signal?: AbortSignal,
    ) {
      const current = requireScope(runtime, scope);
      const path = `/api/v1/agent/templates?tenant_id=${encodeURIComponent(current.tenantId)}`;
      return request(runtime, path, {
        method: 'POST',
        body:
          runtime.mode === 'local'
            ? localMutation(input, 0, crypto.randomUUID())
            : input,
        signal,
      }) as Promise<PromptTemplateRecord>;
    },
    async delete(
      scope: DesktopTenantPromptTemplatesScopeV2,
      templateId: string,
      expectedRevision?: number,
      signal?: AbortSignal,
    ) {
      const current = requireScope(runtime, scope);
      const id = exactNativeRouteIdentifier(
        templateId,
        'tenant_prompt_template_identifier_invalid',
      );
      const path =
        `/api/v1/agent/templates/${encodeURIComponent(id)}` +
        `?tenant_id=${encodeURIComponent(current.tenantId)}`;
      await request(runtime, path, {
        method: 'DELETE',
        ...(runtime.mode === 'local'
          ? { body: localMutation(null, expectedRevision) }
          : {}),
        signal,
      });
    },
  };
  return Object.freeze(authority);
}

function requireScope(
  config: DesktopRuntimeConfig,
  scope: DesktopTenantPromptTemplatesScopeV2,
): DesktopTenantPromptTemplatesScopeV2 {
  requireRuntimeAuthority(config, scope.authority, 'tenant_prompt_template_runtime_scope_mismatch');
  const tenantId = exactNativeRouteIdentifier(
    scope.tenantId,
    'tenant_prompt_template_tenant_scope_invalid',
  );
  if (tenantId !== config.tenantId) {
    throw new NativeRouteClientError('tenant_prompt_template_runtime_scope_mismatch', 409);
  }
  return Object.freeze({ authority: scope.authority, tenantId });
}

function listParams(scope: DesktopTenantPromptTemplatesScopeV2): URLSearchParams {
  return new URLSearchParams({ tenant_id: scope.tenantId, limit: '100', offset: '0' });
}

async function request(
  config: DesktopRuntimeConfig,
  path: string,
  options: Readonly<{
    method?: 'GET' | 'POST' | 'DELETE';
    body?: unknown;
    signal?: AbortSignal;
  }>,
): Promise<unknown> {
  try {
    return await requestNativeRouteJson(config, path, options);
  } catch (error) {
    if (
      config.mode === 'local' &&
      error instanceof NativeRouteClientError &&
      (error.status === 404 || error.status === 501)
    ) {
      throw new NativeRouteClientError(
        DESKTOP_TENANT_PROMPT_TEMPLATES_LOCAL_REASON_V2,
        error.status,
        error.payload,
      );
    }
    throw error;
  }
}

function localMutation(
  value: PromptTemplateCreateInput | null,
  expectedRevision: number | undefined,
  resourceId?: string,
): Readonly<Record<string, unknown>> {
  if (!Number.isSafeInteger(expectedRevision) || Number(expectedRevision) < 0) {
    throw new NativeRouteClientError('managed_resource_revision_required', 428, {
      code: 'managed_resource_revision_required',
    });
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
