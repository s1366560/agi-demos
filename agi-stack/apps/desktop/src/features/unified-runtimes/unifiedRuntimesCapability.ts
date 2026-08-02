import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

const CLOUD_ACTIONS = Object.freeze([
  'view',
  'refresh',
  'inspect-pool',
  'inspect-sandbox',
]);
const LOCAL_ACTIONS = Object.freeze([
  'view',
  'refresh',
  'inspect-sidecar',
  'inspect-sandbox-capabilities',
]);

export function unifiedRuntimesCapability(
  config: DesktopRuntimeConfig,
): DesktopCapabilityAvailability {
  const tenantId = scopeIdentifier(config.tenantId);
  const projectId = scopeIdentifier(config.projectId);
  const scope = capabilityScope(tenantId, config.mode === 'local' ? projectId : null);
  if (!tenantId) {
    return unavailable('unified_runtimes_tenant_scope_unavailable', scope);
  }
  if (config.mode === 'local' && !projectId) {
    return unavailable('unified_runtimes_project_scope_unavailable', scope);
  }
  if (config.mode === 'local') {
    return Object.freeze({
      availability: 'degraded',
      reason_code: 'local_pool_not_applicable_sidecar_projection',
      service_version: '0.1.0',
      contract_version: '3.0.0',
      allowed_actions: LOCAL_ACTIONS,
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

function unavailable(
  reasonCode: string,
  scope: DesktopCapabilityScope,
): DesktopCapabilityAvailability {
  return Object.freeze({
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    scope,
    authority_revision: null,
  });
}

function capabilityScope(
  tenantId: string | null,
  projectId: string | null,
): DesktopCapabilityScope {
  return Object.freeze({
    tenant_id: tenantId,
    project_id: projectId,
    workspace_id: null,
    instance_id: null,
  });
}

function scopeIdentifier(input: string): string | null {
  return input.length > 0 && input === input.trim() ? input : null;
}
