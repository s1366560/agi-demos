import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

export const RUNTIME_CLUSTERS_CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'refresh',
  'search-current-page',
  'filter-status-current-page',
  'paginate',
  'inspect-health',
]);

export function runtimeClustersCapability(
  config: DesktopRuntimeConfig,
): DesktopCapabilityAvailability {
  const tenantId = scopeIdentifier(config.tenantId);
  const scope = capabilityScope(tenantId);
  if (!tenantId) {
    return Object.freeze({
      availability: 'unavailable',
      reason_code: 'runtime_clusters_tenant_scope_unavailable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope,
      authority_revision: null,
    });
  }
  if (config.mode === 'local') {
    return Object.freeze({
      availability: 'not_applicable',
      reason_code: 'cloud_cluster_control_not_applicable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope,
      authority_revision: null,
    });
  }
  return Object.freeze({
    availability: 'degraded',
    reason_code: 'runtime_clusters_detail_and_mutations_partial',
    service_version: '0.1.0',
    contract_version: '3.0.0',
    allowed_actions: RUNTIME_CLUSTERS_CLOUD_ACTIONS,
    scope,
    authority_revision: null,
  });
}

function capabilityScope(tenantId: string | null): DesktopCapabilityScope {
  return Object.freeze({
    tenant_id: tenantId,
    project_id: null,
    workspace_id: null,
    instance_id: null,
  });
}

function scopeIdentifier(value: string): string | null {
  return value && value === value.trim() ? value : null;
}
