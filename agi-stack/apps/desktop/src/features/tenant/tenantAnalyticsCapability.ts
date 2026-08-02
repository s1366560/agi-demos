import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';
import { createTenantAnalyticsHttpClient } from './tenantAnalyticsHttpClient';

export async function loadTenantAnalyticsCapability(
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const tenantId = scopeIdentifier(config.tenantId);
  const scope = tenantCapabilityScope(tenantId);
  if (!tenantId) return unavailable('tenant_analytics_scope_unavailable', scope);
  try {
    const snapshot = await createTenantAnalyticsHttpClient(config).load(
      { authority: config.mode, tenantId, period: '30d' },
      { signal },
    );
    if (
      snapshot.allowedActions.length !== 2 ||
      snapshot.allowedActions[0] !== 'view' ||
      snapshot.allowedActions[1] !== 'retry'
    ) {
      return unavailable('tenant_analytics_contract_invalid', scope);
    }
    return {
      availability: snapshot.availability,
      reason_code: snapshot.reasonCode,
      service_version:
        config.mode === 'cloud' ? '0.1.0' : snapshot.serviceVersion,
      contract_version: snapshot.contractVersion,
      allowed_actions: ['view', 'retry'],
      scope,
      authority_revision: snapshot.authorityRevision,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof DesktopApiError && error.status === 403) {
      return unavailable('tenant_analytics_forbidden', scope);
    }
    if (error instanceof DesktopApiError && error.status === 0) {
      return unavailable('tenant_analytics_contract_invalid', scope);
    }
    return unavailable('tenant_analytics_authority_unavailable', scope);
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
