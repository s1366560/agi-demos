import type { ChangeSnapshot, DesktopArtifactVersion } from '../../types';
import { currentArtifactVersions } from './sessionArtifactModel';
import { sessionCanvasTabs, type SessionCanvasTabId } from './sessionCanvasModel';
import { artifactEvidenceForCurrentVersions } from './sessionEvidenceModel';
import { runDurationMs, type SessionUsageSummary } from './sessionUsageModel';
import { sessionRunStatusIsTerminal, type SessionCapabilityMode } from './sessionViewModel';

export type RunCompletionOutcome = 'completed' | 'failed' | 'cancelled';

export type RunCompletionSummaryLink = {
  tab: SessionCanvasTabId;
  labelKey: string;
};

export type RunCompletionChangesSummary = {
  filesChanged: number;
  additions: number;
  deletions: number;
  truncated: boolean;
  link: RunCompletionSummaryLink | null;
};

export type RunCompletionArtifactEntry = {
  artifactId: string;
  versionId: string;
  title: string;
  mimeType: string;
  status: string;
};

export type RunCompletionArtifactsSummary = {
  totalCount: number;
  entries: RunCompletionArtifactEntry[];
  link: RunCompletionSummaryLink | null;
};

export type RunCompletionVerificationSummary = {
  total: number;
  passedCount: number;
  failedCount: number;
  pendingCount: number;
  // The verification claim is never rendered without a navigable evidence
  // link: when neither the Checks nor the Verification canvas exists for the
  // current capability mode, the section is omitted entirely.
  link: RunCompletionSummaryLink;
};

export type RunCompletionSummary = {
  outcome: RunCompletionOutcome;
  outcomeLabelKey: string;
  failureReason: string | null;
  /** Wall-clock run duration from authoritative run timestamps; null when unavailable. */
  durationMs: number | null;
  /** Latest context-window occupancy reported during the run; null when never reported. */
  usage: SessionUsageSummary | null;
  changes: RunCompletionChangesSummary | null;
  artifacts: RunCompletionArtifactsSummary | null;
  verification: RunCompletionVerificationSummary | null;
};

export type RunCompletionSummaryInput = {
  status: string | null | undefined;
  capabilityMode: SessionCapabilityMode;
  error?: string | null;
  /** ISO-8601 run timestamps from the authoritative projection run record. */
  runStartedAt?: string | null;
  runCompletedAt?: string | null;
  usage?: SessionUsageSummary | null;
  changeSnapshot?: ChangeSnapshot | null;
  artifactVersions?: readonly DesktopArtifactVersion[];
};

const MAX_ARTIFACT_ENTRIES = 3;

const OUTCOME_LABEL_KEYS: Record<RunCompletionOutcome, string> = {
  completed: 'session.statusCompleted',
  failed: 'session.statusFailed',
  cancelled: 'session.statusCancelled',
};

const PASSED_CHECK_STATUSES: ReadonlySet<string> = new Set([
  'passed',
  'pass',
  'ok',
  'success',
  'succeeded',
]);
const FAILED_CHECK_STATUSES: ReadonlySet<string> = new Set(['failed', 'fail', 'error']);

export function runCompletionOutcome(
  status: string | null | undefined,
): RunCompletionOutcome | null {
  const normalized = status?.trim().toLowerCase() ?? '';
  if (!sessionRunStatusIsTerminal(normalized)) return null;
  if (normalized === 'completed') return 'completed';
  if (normalized === 'failed') return 'failed';
  return 'cancelled';
}

/**
 * Durable run-completion summary derived from canonical session data
 * (authoritative run status, change snapshot, artifact versions and their
 * declared checks) rather than transient stream events, so the card reappears
 * identically after reload/refetch. Returns null unless the run reached a
 * terminal status.
 */
export function buildRunCompletionSummary(
  input: RunCompletionSummaryInput,
): RunCompletionSummary | null {
  const outcome = runCompletionOutcome(input.status);
  if (!outcome) return null;

  const configuredTabs = sessionCanvasTabs(input.capabilityMode);
  const tabById = new Map<SessionCanvasTabId, string>(
    [...configuredTabs.primary, ...configuredTabs.secondary].map((tab) => [
      tab.id,
      tab.labelKey,
    ]),
  );
  const linkFor = (tab: SessionCanvasTabId): RunCompletionSummaryLink | null => {
    const labelKey = tabById.get(tab);
    return labelKey ? { tab, labelKey } : null;
  };

  return {
    outcome,
    outcomeLabelKey: OUTCOME_LABEL_KEYS[outcome],
    failureReason:
      outcome === 'completed' ? null : (input.error?.trim() ? input.error.trim() : null),
    durationMs: runDurationMs(input.runStartedAt, input.runCompletedAt),
    usage: input.usage ?? null,
    changes: changesSummary(input.changeSnapshot ?? null, linkFor('changes')),
    artifacts: artifactsSummary(input.artifactVersions ?? [], linkFor('artifacts')),
    verification: verificationSummary(
      input.artifactVersions ?? [],
      linkFor('checks') ?? linkFor('verification'),
    ),
  };
}

function changesSummary(
  snapshot: ChangeSnapshot | null,
  link: RunCompletionSummaryLink | null,
): RunCompletionChangesSummary | null {
  if (!snapshot || snapshot.status !== 'ready' || snapshot.files_changed < 1) return null;
  return {
    filesChanged: snapshot.files_changed,
    additions: snapshot.additions,
    deletions: snapshot.deletions,
    truncated: snapshot.truncated,
    link,
  };
}

function artifactsSummary(
  versions: readonly DesktopArtifactVersion[],
  link: RunCompletionSummaryLink | null,
): RunCompletionArtifactsSummary | null {
  const current = currentArtifactVersions([...versions]);
  if (!current.length) return null;
  return {
    totalCount: current.length,
    entries: current.slice(0, MAX_ARTIFACT_ENTRIES).map((version) => ({
      artifactId: version.artifact_id,
      versionId: version.id,
      title: version.filename,
      mimeType: version.mime_type,
      status: version.status,
    })),
    link,
  };
}

function verificationSummary(
  versions: readonly DesktopArtifactVersion[],
  link: RunCompletionSummaryLink | null,
): RunCompletionVerificationSummary | null {
  if (!link) return null;
  const evidence = artifactEvidenceForCurrentVersions(versions, 'checks');
  if (!evidence.rows.length) return null;
  let passedCount = 0;
  let failedCount = 0;
  let pendingCount = 0;
  for (const row of evidence.rows) {
    const status = row.status?.trim().toLowerCase() ?? '';
    if (PASSED_CHECK_STATUSES.has(status)) passedCount += 1;
    else if (FAILED_CHECK_STATUSES.has(status)) failedCount += 1;
    else pendingCount += 1;
  }
  return {
    total: evidence.rows.length,
    passedCount,
    failedCount,
    pendingCount,
    link,
  };
}
