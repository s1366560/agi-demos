import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';
import type { TenantAgentDashboardAction } from './tenantAgentDashboardClient';
import { createTenantAgentDashboardHttpClient } from './tenantAgentDashboardHttpClient';

const ACTION_ORDER = Object.freeze<TenantAgentDashboardAction[]>([
  'view-config',
  'update-config',
  'view-hook-catalog',
  'list-runs',
  'filter-runs',
  'inspect-run',
  'inspect-trace',
  'refresh',
  'retry',
]);

export async function loadTenantAgentDashboardCapability(
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const tenantId = scopeIdentifier(config.tenantId);
  const scope = tenantCapabilityScope(tenantId);
  if (!tenantId) {
    return unavailable('tenant_agent_dashboard_scope_unavailable', scope);
  }
  if (config.mode === 'local') {
    return unavailable('local_agent_dashboard_authority_unavailable', scope, '0.1.0');
  }
  try {
    const snapshot = await createTenantAgentDashboardHttpClient(config).load(
      { authority: 'cloud', tenantId },
      signal,
    );
    if (!isOrderedActionSubset(snapshot.allowedActions)) {
      return unavailable('tenant_agent_dashboard_contract_invalid', scope);
    }
    return {
      availability: snapshot.availability,
      reason_code: snapshot.reasonCode,
      service_version: snapshot.serviceVersion,
      contract_version: snapshot.contractVersion,
      allowed_actions: snapshot.allowedActions,
      scope,
      authority_revision: snapshot.authorityRevision,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof DesktopApiError && error.status === 403) {
      return unavailable('tenant_agent_dashboard_forbidden', scope);
    }
    if (error instanceof DesktopApiError && error.status === 0) {
      return unavailable('tenant_agent_dashboard_contract_invalid', scope);
    }
    return unavailable('tenant_agent_dashboard_authority_unavailable', scope);
  }
}

function unavailable(
  reasonCode: string,
  scope: DesktopCapabilityScope,
  serviceVersion: string | null = null,
): DesktopCapabilityAvailability {
  return {
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: serviceVersion,
    contract_version: serviceVersion ? '3.0.0' : null,
    allowed_actions: [],
    scope,
    authority_revision: null,
  };
}

function tenantCapabilityScope(tenantId: string | null): DesktopCapabilityScope {
  return {
    tenant_id: tenantId,
    project_id: null,
    workspace_id: null,
    instance_id: null,
  };
}

function scopeIdentifier(value: string): string | null {
  return value.length > 0 && value === value.trim() ? value : null;
}

function isOrderedActionSubset(
  actions: readonly TenantAgentDashboardAction[],
): boolean {
  let lastIndex = -1;
  for (const action of actions) {
    const index = ACTION_ORDER.indexOf(action);
    if (index <= lastIndex) return false;
    lastIndex = index;
  }
  return true;
}
