import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopCapabilityAvailability } from '../runtime/capabilitySnapshot';

const ALLOWED_ACTIONS = Object.freeze(['view', 'list', 'create']);

export function tenantWorkspacesCapability(
  config: DesktopRuntimeConfig,
): DesktopCapabilityAvailability {
  return Object.freeze({
    availability: 'degraded',
    reason_code:
      config.mode === 'cloud'
        ? 'desktop_tenant_workspaces_advanced_management_partial'
        : 'local_workspace_lifecycle_partial',
    service_version: '0.1.0',
    contract_version: '3.0.0',
    allowed_actions: ALLOWED_ACTIONS,
    scope: Object.freeze({
      tenant_id: config.tenantId,
      project_id: config.projectId,
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: null,
  });
}
