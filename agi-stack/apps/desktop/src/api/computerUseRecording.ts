import type { ComputerUseRecording } from './computerUseContractV2';
import { computerUseTimestamp } from './computerUseTime';

export function computerUseRecordingDuration(
  recording: ComputerUseRecording,
  now = Date.now(),
): string {
  const started = computerUseTimestamp(recording.started_at);
  const ended = computerUseTimestamp(recording.ended_at);
  const elapsed =
    recording.status === 'recording' && started
      ? Math.max(recording.elapsed_ms ?? 0, now - Date.parse(started), 0)
      : (recording.elapsed_ms ??
        (started && ended ? Math.max(0, Date.parse(ended) - Date.parse(started)) : 0));
  const seconds = Math.floor(elapsed / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export function computerUseRecordingIsPending(recording: ComputerUseRecording): boolean {
  return ['recording', 'stopping', 'pending_export'].includes(recording.status);
}

/** Native protocol reasons, never a classification of free-form error text. */
export function computerUseRecordingEndReasonKey(reason: string): string {
  return [
    'user_stopped',
    'user_paused',
    'model_stopped',
    'session_ended',
    'session_reset',
    'revoked',
    'disabled',
    'lease_expired',
    'cancelled',
    'duration_limit',
    'byte_limit',
    'start_failed',
    'capture_error',
    'device_lost',
    'capture_ended',
    'process_ended',
  ].includes(reason)
    ? `cua.recording.ended.${reason}`
    : 'cua.recording.ended.unknown';
}
