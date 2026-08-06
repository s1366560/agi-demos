import type { RuntimeMode } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

export const INVITATION_ACCEPTANCE_CLOUD_ACTIONS = Object.freeze([
  'verify',
  'sign-in',
  'accept',
  'open-tenant',
  'retry',
]);

export function invitationAcceptanceCapability(
  config: Readonly<{ mode: RuntimeMode }>,
): DesktopCapabilityAvailability {
  const scope = globalScope();
  if (config.mode === 'local') {
    return Object.freeze({
      availability: 'not_applicable',
      reason_code: 'local_tenant_invitation_not_applicable',
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
