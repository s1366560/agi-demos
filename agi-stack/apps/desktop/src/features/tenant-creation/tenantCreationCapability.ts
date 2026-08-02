import type { RuntimeMode } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

export const TENANT_CREATION_CLOUD_ACTIONS = Object.freeze([
  'create',
  'cancel',
  'return-to-tenant-list',
  'retry',
]);

export function tenantCreationCapability(
  config: Readonly<{ mode: RuntimeMode }>,
): DesktopCapabilityAvailability {
  const scope = globalScope();
  if (config.mode === 'local') {
    return Object.freeze({
      availability: 'not_applicable',
      reason_code: 'local_tenant_creation_not_applicable',
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
    allowed_actions: TENANT_CREATION_CLOUD_ACTIONS,
    scope,
    authority_revision: null,
  });
}

function globalScope(): DesktopCapabilityScope {
  return Object.freeze({
    tenant_id: null,
    project_id: null,
    workspace_id: null,
    instance_id: null,
  });
}
