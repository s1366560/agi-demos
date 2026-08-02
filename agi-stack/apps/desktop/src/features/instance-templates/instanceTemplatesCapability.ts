import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

export const INSTANCE_TEMPLATES_CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'list-items',
  'create',
  'delete',
  'publish',
  'clone',
  'refresh',
  'paginate',
  'search-current-page',
  'filter-status',
]);

export function instanceTemplatesCapability(
  config: DesktopRuntimeConfig,
): DesktopCapabilityAvailability {
  const tenantId = scopeIdentifier(config.tenantId);
  const scope = capabilityScope(tenantId);
  if (!tenantId) {
    return Object.freeze({
      availability: 'unavailable',
      reason_code: 'instance_templates_tenant_scope_unavailable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope,
      authority_revision: null,
    });
  }
  if (config.mode === 'local') {
    return Object.freeze({
      availability: 'unavailable',
      reason_code: 'local_instance_template_authority_unavailable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope,
      authority_revision: null,
    });
  }
  return Object.freeze({
    availability: 'degraded',
    reason_code: 'instance_templates_nested_deep_link_and_deploy_partial',
    service_version: '0.1.0',
    contract_version: '3.0.0',
    allowed_actions: INSTANCE_TEMPLATES_CLOUD_ACTIONS,
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
