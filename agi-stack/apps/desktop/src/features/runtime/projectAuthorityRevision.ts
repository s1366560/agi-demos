import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from './capabilitySnapshot';

export function canReuseProjectAuthorityRevision(
  revisionSource: DesktopCapabilityAvailability | undefined,
  expectedScope: DesktopCapabilityScope,
): revisionSource is DesktopCapabilityAvailability {
  if (!revisionSource?.scope) return false;
  if (
    revisionSource.availability !== 'available' &&
    revisionSource.availability !== 'degraded'
  ) {
    return false;
  }
  const revision = revisionSource.authority_revision;
  if (revision === null || !Number.isSafeInteger(revision) || revision < 0) return false;
  const { tenant_id: tenantId, project_id: projectId } = revisionSource.scope;
  if (tenantId === null || projectId === null) return false;
  return tenantId === expectedScope.tenant_id && projectId === expectedScope.project_id;
}

export function withProjectAuthorityRevision(
  capability: DesktopCapabilityAvailability,
  revisionSource: DesktopCapabilityAvailability | undefined,
  expectedScope: DesktopCapabilityScope,
): DesktopCapabilityAvailability {
  if (capability.authority_revision !== null) return capability;
  if (capability.availability !== 'available' && capability.availability !== 'degraded') {
    return capability;
  }
  if (!canReuseProjectAuthorityRevision(revisionSource, expectedScope)) return capability;
  return { ...capability, authority_revision: revisionSource.authority_revision };
}
