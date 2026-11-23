import { BLACKBOARD_TABS, type BlackboardTab } from '@/components/blackboard/BlackboardTabBar';

export const DEFAULT_BLACKBOARD_TAB: BlackboardTab = 'goals';

export function syncBlackboardWorkspaceSearchParams(
  searchParams: URLSearchParams,
  options: {
    selectedWorkspaceId: string | null;
    workspacesLoading: boolean;
  }
): URLSearchParams | null {
  const currentQueryWorkspaceId = searchParams.get('workspaceId');
  const hasLegacyOpenFlag = searchParams.has('open');

  if (!options.selectedWorkspaceId) {
    if (!currentQueryWorkspaceId && !hasLegacyOpenFlag) {
      return null;
    }
    if (options.workspacesLoading) {
      return null;
    }

    const nextSearchParams = new URLSearchParams(searchParams);
    nextSearchParams.delete('workspaceId');
    nextSearchParams.delete('open');
    return nextSearchParams;
  }

  if (currentQueryWorkspaceId === options.selectedWorkspaceId && !hasLegacyOpenFlag) {
    return null;
  }

  const nextSearchParams = new URLSearchParams(searchParams);
  nextSearchParams.set('workspaceId', options.selectedWorkspaceId);
  nextSearchParams.delete('open');
  return nextSearchParams;
}

/**
 * Read the active tab from the URL. Returns the default when the `tab`
 * parameter is missing or holds an unknown value.
 */
export function resolveBlackboardTab(searchParams: URLSearchParams): BlackboardTab {
  const raw = searchParams.get('tab');
  if (!raw) {
    return DEFAULT_BLACKBOARD_TAB;
  }
  return (BLACKBOARD_TABS as readonly string[]).includes(raw)
    ? (raw as BlackboardTab)
    : DEFAULT_BLACKBOARD_TAB;
}

/**
 * Build the next searchParams when the active tab changes. Returns null
 * when the URL already matches (no-op).
 */
export function syncBlackboardTabSearchParam(
  searchParams: URLSearchParams,
  nextTab: BlackboardTab
): URLSearchParams | null {
  const current = searchParams.get('tab');
  if (nextTab === DEFAULT_BLACKBOARD_TAB) {
    if (!current) {
      return null;
    }
    const next = new URLSearchParams(searchParams);
    next.delete('tab');
    return next;
  }
  if (current === nextTab) {
    return null;
  }
  const next = new URLSearchParams(searchParams);
  next.set('tab', nextTab);
  return next;
}

export function clearBlackboardAutoOpenSearchParam(
  searchParams: URLSearchParams
): URLSearchParams | null {
  if (!searchParams.has('open')) {
    return null;
  }

  const nextSearchParams = new URLSearchParams(searchParams);
  nextSearchParams.delete('open');
  return nextSearchParams;
}

export function resolveRequestedWorkspaceSelection(
  requestedWorkspaceId: string | null,
  appliedRequestedWorkspaceId: string | null,
  workspaces: Array<{ id: string }>
): string | null {
  if (!requestedWorkspaceId || requestedWorkspaceId === appliedRequestedWorkspaceId) {
    return null;
  }

  return workspaces.some((workspace) => workspace.id === requestedWorkspaceId)
    ? requestedWorkspaceId
    : null;
}

export function buildWorkspaceBlackboardRedirectQuery(workspaceId?: string): string {
  const params = new URLSearchParams();

  if (workspaceId) {
    params.set('workspaceId', workspaceId);
  }

  return params.toString();
}
