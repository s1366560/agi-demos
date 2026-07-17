import type { DesktopRuntimeConfig } from '../../types';
import { isSameDesktopRequestScope } from '../auth/authContextModel';

export type SessionTimelineRequestStamp = {
  requestId: number;
  scopeEpoch: number;
};

/**
 * A conversation change inside the current request scope only changes the
 * WebSocket subscription. Reload workspace authority only when the selected
 * runtime, tenant, project, or workspace boundary actually changes.
 */
export function sessionSelectionRequiresRuntimeRefresh(
  current: DesktopRuntimeConfig,
  next: DesktopRuntimeConfig,
): boolean {
  return !isSameDesktopRequestScope(current, next);
}

export function sessionTimelineRequestIsCurrent(
  expected: SessionTimelineRequestStamp,
  current: SessionTimelineRequestStamp,
): boolean {
  return expected.requestId === current.requestId && expected.scopeEpoch === current.scopeEpoch;
}
