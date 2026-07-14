import type {
  ArtifactDeliveryRequest,
  ArtifactReviewRequest,
  DesktopArtifactDelivery,
  DesktopArtifactVersion,
  DesktopRun,
} from '../../types';

export type ArtifactVersionAction = 'approve' | 'request_changes' | 'deliver';

export function currentArtifactVersions(
  versions: DesktopArtifactVersion[],
): DesktopArtifactVersion[] {
  const current = new Map<string, DesktopArtifactVersion>();
  for (const version of versions) {
    const existing = current.get(version.artifact_id);
    if (
      !existing ||
      version.version > existing.version ||
      (version.version === existing.version && version.revision > existing.revision)
    ) {
      current.set(version.artifact_id, version);
    }
  }
  return [...current.values()].sort((left, right) =>
    right.updated_at.localeCompare(left.updated_at),
  );
}

export function artifactVersionActions(
  version: DesktopArtifactVersion,
  run: DesktopRun | null,
): ArtifactVersionAction[] {
  if (version.status === 'delivered' || version.status === 'superseded') return [];
  const canRequestChanges = Boolean(
    run &&
      version.run_id === run.id &&
      run.status === 'ready_review' &&
      Number.isFinite(run.revision),
  );
  if (version.status === 'approved') {
    return canRequestChanges ? ['request_changes', 'deliver'] : ['deliver'];
  }
  if (version.status === 'draft' || version.status === 'ready') {
    return canRequestChanges ? ['request_changes', 'approve'] : ['approve'];
  }
  return [];
}

export function artifactReviewRequest(
  version: DesktopArtifactVersion,
  action: Extract<ArtifactVersionAction, 'approve' | 'request_changes'>,
  run: DesktopRun | null,
  feedback?: string,
): ArtifactReviewRequest {
  const trimmedFeedback = feedback?.trim();
  if (action === 'request_changes') {
    if (!trimmedFeedback) throw new Error('artifact review feedback is required');
    if (!run || version.run_id !== run.id || run.status !== 'ready_review') {
      throw new Error('artifact run is not ready for review');
    }
  }
  return {
    action,
    expectedRevision: version.revision,
    ...(action === 'request_changes' && run
      ? { runExpectedRevision: run.revision, feedback: trimmedFeedback }
      : {}),
  };
}

export function artifactDeliveryRequest(
  version: DesktopArtifactVersion,
): ArtifactDeliveryRequest {
  return {
    expectedRevision: version.revision,
    idempotencyKey: `${version.id}:${version.revision}:deliver`,
    destination: 'local_workspace',
  };
}

export function deliveryForArtifactVersion(
  deliveries: DesktopArtifactDelivery[],
  artifactVersionId: string,
): DesktopArtifactDelivery | null {
  return (
    deliveries
      .filter((delivery) => delivery.artifact_version_id === artifactVersionId)
      .sort((left, right) => right.created_at.localeCompare(left.created_at))[0] ?? null
  );
}
