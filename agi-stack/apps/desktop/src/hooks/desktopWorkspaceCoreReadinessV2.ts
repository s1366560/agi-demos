export interface DesktopWorkspaceCoreReadinessOptionsV2 {
  readonly readStatus: () => Promise<unknown>;
  readonly isCurrent: () => boolean;
  readonly pollIntervalMs?: number;
}

/** Wait for the authenticated helper handshake and recovery, not just sidecar startup. */
export async function waitForDesktopWorkspaceCoreReadyV2({
  readStatus,
  isCurrent,
  pollIntervalMs = 250,
}: DesktopWorkspaceCoreReadinessOptionsV2): Promise<boolean> {
  while (isCurrent()) {
    let status: unknown;
    try {
      status = await readStatus();
    } catch (error) {
      if (!isCurrent()) return false;
      throw error;
    }
    if (!isCurrent()) return false;
    if (typeof status !== 'object' || status === null || Array.isArray(status)) {
      throw new Error('workspace_core_status_invalid');
    }
    const { state, cutoverState } = status as Record<string, unknown>;
    switch (state) {
      case 'running':
        if (cutoverState !== 'core-authoritative') {
          throw new Error('workspace_core_status_invalid');
        }
        return true;
      case 'starting':
      case 'restartScheduled':
        await new Promise<void>((resolve) => setTimeout(resolve, pollIntervalMs));
        break;
      case 'failed':
        throw new Error('workspace_core_failed');
      case 'stopped':
        throw new Error('workspace_core_stopped');
      default:
        throw new Error('workspace_core_status_invalid');
    }
  }
  return false;
}
