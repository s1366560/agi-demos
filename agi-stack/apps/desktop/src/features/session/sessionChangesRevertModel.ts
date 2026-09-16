import { DesktopApiError, desktopApiCredential, desktopLaunchCapability } from '../../api/client';
import { desktopApiAuthenticationAvailable, desktopApiFetch } from '../../api/cloudRequestBroker';
import type { ChangeSnapshot, DesktopRuntimeConfig } from '../../types';

/**
 * Per-file / per-hunk revert for the Changes review panel (Cloud mode only).
 *
 * The backend endpoint is the sole authority: the client sends only selectors
 * (path + optional hunk indices) pinned to the snapshot digest it reviewed,
 * plus the run revision and an idempotency key. Local mode stays fail-closed —
 * the sidecar diff pipeline is read-only by design.
 */

export type ChangeRevertSelector = Readonly<{
  path: string;
  hunkIndices?: readonly number[];
}>;

export type ChangeRevertNoticeKind = 'stale' | 'unavailable' | 'failed';

export type ChangeRevertNotice = Readonly<{
  kind: ChangeRevertNoticeKind;
  reasonCode: string;
}>;

export type ChangeRevertResult = Readonly<{
  accepted: true;
  snapshot_digest: string;
  reverted: readonly unknown[];
  head_commit: string | null;
}>;

export function changeRevertAvailable(
  config: DesktopRuntimeConfig,
  snapshot: ChangeSnapshot | null,
): boolean {
  return Boolean(
    config.mode === 'cloud' &&
      snapshot &&
      snapshot.status === 'ready' &&
      snapshot.environment_id &&
      typeof snapshot.snapshot_revision === 'string' &&
      snapshot.snapshot_revision.length > 0 &&
      snapshot.files.length > 0,
  );
}

export function buildChangeRevertPayload(
  snapshot: ChangeSnapshot,
  selector: ChangeRevertSelector,
  idempotencyKey: string,
): Readonly<Record<string, unknown>> | null {
  if (
    typeof snapshot.snapshot_revision !== 'string' ||
    !snapshot.snapshot_revision ||
    !idempotencyKey.trim() ||
    !selector.path.trim()
  )
    return null;
  if (
    selector.hunkIndices !== undefined &&
    (!selector.hunkIndices.length ||
      selector.hunkIndices.some(
        (index) => !Number.isSafeInteger(index) || index < 0,
      ))
  )
    return null;
  const scope = snapshot.scope ?? 'run';
  return Object.freeze({
    expected_run_revision: snapshot.run_revision,
    scope,
    ...(scope === 'turn' && snapshot.turn_id ? { turn_id: snapshot.turn_id } : {}),
    snapshot_digest: snapshot.snapshot_revision,
    idempotency_key: idempotencyKey,
    selectors: [
      {
        path: selector.path,
        ...(selector.hunkIndices === undefined
          ? {}
          : { hunk_indices: [...selector.hunkIndices] }),
      },
    ],
  });
}

function reasonCodeFromError(error: unknown): string | null {
  if (error instanceof DesktopApiError) {
    const raw = error.payload;
    if (raw !== null && typeof raw === 'object' && !Array.isArray(raw)) {
      const code = (raw as Record<string, unknown>).reason_code;
      if (typeof code === 'string' && code) return code;
    }
    if (typeof error.message === 'string' && error.message) return error.message;
  }
  return null;
}

export function changeRevertNoticeFromError(error: unknown): ChangeRevertNotice {
  const reasonCode = reasonCodeFromError(error) ?? 'unknown';
  if (reasonCode === 'snapshot_digest_mismatch' || reasonCode === 'run_revision_conflict')
    return Object.freeze({ kind: 'stale', reasonCode });
  if (
    reasonCode === 'sandbox_write_unavailable' ||
    reasonCode === 'revert_execution_failed' ||
    reasonCode === 'local_run_changes_revert_unavailable'
  )
    return Object.freeze({ kind: 'unavailable', reasonCode });
  return Object.freeze({ kind: 'failed', reasonCode });
}

export function revertTargetLabel(selector: ChangeRevertSelector): string {
  if (selector.hunkIndices === undefined) return selector.path;
  const hunks = selector.hunkIndices.map((index) => `#${index + 1}`).join(', ');
  return `${selector.path} hunk ${hunks}`;
}

export async function revertRunChanges(
  config: DesktopRuntimeConfig,
  runId: string,
  payload: Readonly<Record<string, unknown>>,
  signal: AbortSignal,
): Promise<ChangeRevertResult> {
  if (config.mode !== 'cloud')
    throw new DesktopApiError('local_run_changes_revert_unavailable', 501, {
      reason_code: 'local_run_changes_revert_unavailable',
    });
  if (!desktopApiAuthenticationAvailable(config))
    throw new DesktopApiError('desktop_trusted_session_required', 401, {
      reason_code: 'desktop_trusted_session_required',
    });
  const headers = new Headers({
    Accept: 'application/json',
    'Content-Type': 'application/json',
  });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launch = desktopLaunchCapability(config);
  if (launch) headers.set('X-Agistack-Launch', launch);
  const response = await desktopApiFetch(
    config,
    `/api/v1/agent/runs/${encodeURIComponent(runId)}/changes/revert`,
    { method: 'POST', headers, body: JSON.stringify(payload), signal },
  );
  const raw: unknown = response.headers
    .get('content-type')
    ?.toLowerCase()
    .includes('application/json')
    ? await response.json().catch(() => null)
    : null;
  if (!response.ok) {
    const record =
      raw !== null && typeof raw === 'object' && !Array.isArray(raw)
        ? (raw as Record<string, unknown>)
        : {};
    const detail = typeof record.detail === 'string' ? record.detail : undefined;
    throw new DesktopApiError(detail ?? `HTTP ${response.status}`, response.status, record);
  }
  if (
    raw === null ||
    typeof raw !== 'object' ||
    Array.isArray(raw) ||
    (raw as Record<string, unknown>).accepted !== true ||
    typeof (raw as Record<string, unknown>).snapshot_digest !== 'string' ||
    !Array.isArray((raw as Record<string, unknown>).reverted)
  )
    throw new DesktopApiError('desktop_run_change_revert_response_invalid', 502, {
      reason_code: 'desktop_run_change_revert_response_invalid',
    });
  const record = raw as Record<string, unknown>;
  return Object.freeze({
    accepted: true,
    snapshot_digest: record.snapshot_digest as string,
    reverted: Object.freeze(record.reverted as unknown[]),
    head_commit: typeof record.head_commit === 'string' ? record.head_commit : null,
  });
}
