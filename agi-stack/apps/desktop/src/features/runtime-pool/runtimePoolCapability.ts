import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

const CLOUD_ACTIONS = Object.freeze([
  'view',
  'refresh',
  'toggle-auto-refresh',
  'list-instances',
  'search-current-page',
  'filter-by-tier',
  'paginate-instances',
  'pause-instance',
  'resume-instance',
  'terminate-instance',
  'retry-list-instances',
  'inspect-pool-status',
]);

export function runtimePoolCapability(
  config: DesktopRuntimeConfig,
): DesktopCapabilityAvailability {
  const tenantId = scopeIdentifier(config.tenantId);
  const scope = capabilityScope(tenantId);
  if (!tenantId) {
    return Object.freeze({
      availability: 'unavailable',
      reason_code: 'runtime_pool_scope_unavailable',
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
      reason_code: 'cloud_runtime_pool_not_applicable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope,
      authority_revision: null,
    });
  }
  return Object.freeze({
    availability: 'degraded',
    reason_code: 'global_pool_capacity_not_available_in_tenant_scope',
    service_version: '0.1.0',
    contract_version: '3.0.0',
    allowed_actions: CLOUD_ACTIONS,
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

function scopeIdentifier(input: string): string | null {
  return input.length > 0 && input === input.trim() ? input : null;
}
