import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

export const RUNTIME_INSTANCES_CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'refresh',
  'search',
  'filter-status',
  'paginate',
  'restart',
  'delete',
]);
export const RUNTIME_INSTANCES_LOCAL_ACTIONS = Object.freeze([
  'view',
  'list',
  'refresh',
  'search',
  'filter-status',
]);

export function runtimeInstancesCapability(
  config: DesktopRuntimeConfig,
): DesktopCapabilityAvailability {
  const tenantId = scopeIdentifier(config.tenantId);
  const scope = capabilityScope(tenantId);
  if (!tenantId) {
    return Object.freeze({
      availability: 'unavailable',
      reason_code: 'runtime_instances_tenant_scope_unavailable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope,
      authority_revision: null,
    });
  }
  const local = config.mode === 'local';
  return Object.freeze({
    availability: 'degraded',
    reason_code: local
      ? 'local_instance_sidecar_projection_partial'
      : 'runtime_instances_nested_routes_partial',
    service_version: '0.1.0',
    contract_version: '3.0.0',
    allowed_actions: local
      ? RUNTIME_INSTANCES_LOCAL_ACTIONS
      : RUNTIME_INSTANCES_CLOUD_ACTIONS,
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
