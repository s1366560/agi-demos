import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

const CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'create',
  'close',
  'retry',
]);

export function projectSupportCapability(
  config: DesktopRuntimeConfig,
): DesktopCapabilityAvailability {
  const tenantId = identifier(config.tenantId);
  const projectId = identifier(config.projectId);
  const scope = capabilityScope(tenantId, projectId);
  if (!tenantId || !projectId) {
    return Object.freeze({
      availability: 'unavailable',
      reason_code: 'project_support_scope_unavailable',
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
      reason_code: 'local_support_service_not_applicable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope,
      authority_revision: null,
    });
  }
  return Object.freeze({
    availability: 'available',
    reason_code: null,
    service_version: '0.1.0',
    contract_version: '3.0.0',
    allowed_actions: CLOUD_ACTIONS,
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

function identifier(input: string): string | null {
  return input.length > 0 && input === input.trim() ? input : null;
}
