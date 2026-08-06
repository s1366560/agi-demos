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
      authority_source: 'renderer',
      provenance: 'declared',
    });
  }
  return Object.freeze({
    availability: 'unavailable',
    reason_code: 'renderer_capability_authority_unobserved',
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    scope,
    authority_revision: null,
    authority_source: 'renderer',
    provenance: 'declared',
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
