import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from './capabilitySnapshot';
import type { CapabilityContractNegotiation } from './capabilityVersion';

type CapabilityAuthorityMetadata = {
  allowedActions?: readonly string[];
  authorityRevision?: number | null;
};

export function available(
  negotiation: CapabilityContractNegotiation,
  metadata: CapabilityAuthorityMetadata = {},
): DesktopCapabilityAvailability {
  return {
    availability: 'available',
    reason_code: null,
    service_version: negotiation.service_version,
    contract_version: negotiation.contract_version,
    allowed_actions: [...(metadata.allowedActions ?? [])],
    scope: emptyCapabilityScope(),
    authority_revision: metadata.authorityRevision ?? null,
  };
}

export function degraded(
  reasonCode: string,
  negotiation: CapabilityContractNegotiation,
  metadata: CapabilityAuthorityMetadata = {},
): DesktopCapabilityAvailability {
  return {
    availability: 'degraded',
    reason_code: reasonCode,
    service_version: negotiation.service_version,
    contract_version: negotiation.contract_version,
    allowed_actions: [...(metadata.allowedActions ?? [])],
    scope: emptyCapabilityScope(),
    authority_revision: metadata.authorityRevision ?? null,
  };
}

export function unavailable(
  reasonCode: string,
  negotiation?: CapabilityContractNegotiation,
): DesktopCapabilityAvailability {
  return {
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: negotiation?.service_version ?? null,
    contract_version: negotiation?.contract_version ?? null,
    allowed_actions: [],
    scope: emptyCapabilityScope(),
    authority_revision: null,
  };
}

export function emptyCapabilityScope(): DesktopCapabilityScope {
  return {
    tenant_id: null,
    project_id: null,
    workspace_id: null,
    instance_id: null,
  };
}
