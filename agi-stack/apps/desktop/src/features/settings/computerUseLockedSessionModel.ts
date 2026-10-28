import type { ComputerUseSnapshot } from '../../api/computerUseContractV2';

export type ComputerUseLockedSessionPhase =
  | 'idle'
  | 'armed'
  | 'covering'
  | 'unlocking'
  | 'guarded'
  | 'relocking'
  | 'failed'
  | 'unknown';

/** Display only the host's session projection, never the device-wide component status. */
export function computerUseLockedSessionView(session: ComputerUseSnapshot['sessions'][number]) {
  const status = session.locked_use;
  if (!status) return null;
  const revoked = status.revoked_binding;
  if (Object.prototype.hasOwnProperty.call(status, 'revoked_binding') &&
    (!revoked || typeof revoked !== 'object' || Array.isArray(revoked))) return null;
  const binding = revoked ?? status;
  if (
    binding.session_id !== session.session_id ||
    binding.run_id !== session.run_id ||
    ![binding.session_id, binding.run_id, binding.generation].every(
      (value) => typeof value === 'string' && value.length > 0,
    )
  ) return null;

  const failed = status.state === 'failed' || status.state === 'suppressed';
  if (revoked) {
    // Revoked identity can explain a terminal state, never an active phase.
    if (
      status.enabled !== false ||
      [status.session_id, status.run_id, status.generation].some((value) => value !== undefined) ||
      !['available', 'suppressed', 'failed'].includes(status.state ?? '') ||
      status.requires_manual_unlock !== failed ||
      !(status.phase === 'relocking' || (status.phase === 'idle' && failed))
    ) return null;
  } else if (failed || status.phase === 'relocking' || status.requires_manual_unlock === true) {
    return null;
  }
  let phase: ComputerUseLockedSessionPhase;
  if (failed && status.phase !== 'relocking') phase = 'failed';
  else if (
    ['armed', 'covering', 'unlocking', 'guarded'].includes(status.phase ?? '') &&
    (status.enabled !== true || status.state !== 'active')
  ) phase = 'unknown';
  else {
    switch (status.phase) {
      case 'idle':
      case 'armed':
      case 'covering':
      case 'unlocking':
      case 'guarded':
      case 'relocking':
      case 'failed':
        phase = status.phase;
        break;
      default:
        phase = 'unknown';
    }
  }
  return {
    phase,
    requiresManualUnlock: status.requires_manual_unlock === true,
    reason: typeof status.reason === 'string' ? status.reason : null,
  };
}
