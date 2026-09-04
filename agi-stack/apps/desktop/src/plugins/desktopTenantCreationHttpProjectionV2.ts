import { desktopApiCredential } from '../api/client';
import { desktopApiAuthenticationAvailable, desktopApiFetch } from '../api/cloudRequestBroker';
import { TenantCreationError } from '../features/tenant-creation/tenantCreationClient';
import type { TenantCreationInput, TenantCreationRecord } from '../features/tenant-creation/tenantCreationModel';
import type { DesktopRuntimeConfig } from '../types';
import { cloneDesktopTenantCreationRuntimeConfigV2, requireDesktopTenantCreationRecordV2 } from './desktopTenantCreationOperationContractV2';

export type DesktopTenantCreationHttpAuthorityV2 = Readonly<{
  create: (input: TenantCreationInput, signal?: AbortSignal) => Promise<TenantCreationRecord>;
}>;

export function createDesktopTenantCreationHttpAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopTenantCreationHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopTenantCreationRuntimeConfigV2(config);
  return Object.freeze({
    async create(input, signal) {
      if (!desktopApiAuthenticationAvailable(runtimeConfig)) {
        throw new TenantCreationError('tenant_creation_authentication_required', 401);
      }
      const headers = new Headers({ Accept: 'application/json', 'Content-Type': 'application/json' });
      const credential = desktopApiCredential(runtimeConfig);
      if (credential) headers.set('Authorization', `Bearer ${credential}`);
      const response = await desktopApiFetch(runtimeConfig, '/api/v1/tenants/', {
        method: 'POST', headers, signal, body: JSON.stringify(input),
      });
      const contentType = response.headers.get('content-type') ?? '';
      const payload = contentType.toLowerCase().includes('application/json')
        ? await response.json().catch(() => null) : null;
      if (!response.ok) throw new TenantCreationError(reasonCodeForStatusV2(response.status), response.status);
      if (response.status !== 201) {
        throw new TenantCreationError('tenant_creation_contract_invalid', response.status);
      }
      try {
        return requireDesktopTenantCreationRecordV2(payload);
      } catch {
        throw new TenantCreationError('tenant_creation_contract_invalid', response.status);
      }
    },
  });
}

function reasonCodeForStatusV2(status: number): string {
  if (status === 400 || status === 422) return 'tenant_creation_request_invalid';
  if (status === 401) return 'tenant_creation_authentication_required';
  if (status === 403) return 'tenant_creation_forbidden';
  if (status === 409) return 'tenant_creation_conflict';
  if (status === 429) return 'tenant_creation_rate_limited';
  if (status === 502 || status === 503 || status === 504) return 'tenant_creation_authority_unavailable';
  return 'tenant_creation_request_failed';
}
