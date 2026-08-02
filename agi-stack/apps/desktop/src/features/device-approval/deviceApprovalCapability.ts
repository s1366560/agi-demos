import type { RuntimeMode } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

export const DEVICE_APPROVAL_CLOUD_ACTIONS = Object.freeze([
  'enter-code',
  'approve',
  'navigate-back',
  'retry',
]);

export function deviceApprovalCapability(
  config: Readonly<{ mode: RuntimeMode }>,
): DesktopCapabilityAvailability {
  const scope = globalScope();
  if (config.mode === 'local') {
    return Object.freeze({
      availability: 'not_applicable',
      reason_code: 'local_cloud_device_approval_not_applicable',
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
    allowed_actions: DEVICE_APPROVAL_CLOUD_ACTIONS,
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
