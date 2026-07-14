import type { RuntimeMode } from '../../types';

export type WorkspaceSsoAction =
  | { kind: 'local_session'; trustedDevice: boolean }
  | { kind: 'unavailable' };

export function resolveWorkspaceSsoAction(
  mode: RuntimeMode,
  localReady: boolean,
  trustedDevice: boolean,
): WorkspaceSsoAction {
  if (mode !== 'local' || !localReady) return { kind: 'unavailable' };
  return { kind: 'local_session', trustedDevice };
}
