import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';
import { createTenantOverviewHttpClient } from './tenantOverviewHttpClient';

const CLOUD_TENANT_OVERVIEW_SERVICE_VERSION = '0.1.0';

export async function loadTenantOverviewCapability(
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const tenantId = scopeIdentifier(config.tenantId);
  const scope = tenantCapabilityScope(tenantId);
  if (!tenantId) {
    return unavailable('tenant_overview_scope_unavailable', scope);
  }

  try {
    const authority = config.mode === 'local' ? 'local' : 'cloud';
    const snapshot = await createTenantOverviewHttpClient(config).load(
      { authority, tenantId },
      { signal },
    );
    if (
      snapshot.allowedActions.length !== 1 ||
      snapshot.allowedActions[0] !== 'view'
    ) {
      return unavailable('tenant_overview_contract_invalid', scope);
    }
    return {
      availability: snapshot.availability,
      reason_code: snapshot.reasonCode,
      service_version:
        authority === 'cloud'
          ? CLOUD_TENANT_OVERVIEW_SERVICE_VERSION
          : snapshot.serviceVersion,
      contract_version: snapshot.contractVersion,
      allowed_actions: ['view'],
      scope,
      authority_revision: snapshot.authorityRevision,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof DesktopApiError && error.status === 403) {
      return unavailable('tenant_overview_forbidden', scope);
    }
    if (error instanceof DesktopApiError && error.status === 0) {
      return unavailable('tenant_overview_contract_invalid', scope);
    }
    return unavailable('tenant_overview_authority_unavailable', scope);
  }
}

function unavailable(
  reasonCode: string,
  scope: DesktopCapabilityScope,
): DesktopCapabilityAvailability {
  return {
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    scope,
    authority_revision: null,
  };
}

function tenantCapabilityScope(
  tenantId: string | null,
): DesktopCapabilityScope {
  return {
    tenant_id: tenantId,
    project_id: null,
    workspace_id: null,
    instance_id: null,
  };
}

function scopeIdentifier(input: string): string | null {
  return input.length > 0 && input === input.trim() ? input : null;
}
