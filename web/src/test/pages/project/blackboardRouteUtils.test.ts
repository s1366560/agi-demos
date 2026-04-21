import { describe, expect, it } from 'vitest';

import {
  buildWorkspaceBlackboardRedirectQuery,
  clearBlackboardAutoOpenSearchParam,
  resolveRequestedWorkspaceSelection,
  syncBlackboardWorkspaceSearchParams,
} from '@/pages/project/blackboardRouteUtils';

describe('blackboardRouteUtils', () => {
  it('keeps the requested workspace query while the workspace list is still loading', () => {
    const result = syncBlackboardWorkspaceSearchParams(
      new URLSearchParams('workspaceId=ws-2&open=1'),
      {
        selectedWorkspaceId: null,
        workspacesLoading: true,
      }
    );

    expect(result).toBeNull();
  });

  it('syncs a manually selected workspace into the URL', () => {
    const result = syncBlackboardWorkspaceSearchParams(new URLSearchParams('workspaceId=ws-1'), {
      selectedWorkspaceId: 'ws-2',
      workspacesLoading: false,
    });

    expect(result?.toString()).toBe('workspaceId=ws-2');
  });

  it('drops stale auto-open state when reassigning workspaceId to a fallback workspace', () => {
    const result = syncBlackboardWorkspaceSearchParams(
      new URLSearchParams('workspaceId=missing&open=1'),
      {
        selectedWorkspaceId: 'ws-2',
        workspacesLoading: false,
      }
    );

    expect(result?.toString()).toBe('workspaceId=ws-2');
  });

  it('clears both workspaceId and open when no workspace remains selected', () => {
    const result = syncBlackboardWorkspaceSearchParams(
      new URLSearchParams('workspaceId=ws-2&open=1'),
      {
        selectedWorkspaceId: null,
        workspacesLoading: false,
      }
    );

    expect(result?.toString()).toBe('');
  });

  it('removes only the auto-open flag when the user changes workspaces', () => {
    const result = clearBlackboardAutoOpenSearchParam(
      new URLSearchParams('workspaceId=ws-2&open=1')
    );

    expect(result?.toString()).toBe('workspaceId=ws-2');
  });

  it('only applies URL-driven workspace changes once per requested id', () => {
    expect(
      resolveRequestedWorkspaceSelection('ws-2', null, [{ id: 'ws-1' }, { id: 'ws-2' }])
    ).toBe('ws-2');
    expect(
      resolveRequestedWorkspaceSelection('ws-2', 'ws-2', [{ id: 'ws-1' }, { id: 'ws-2' }])
    ).toBeNull();
  });

  it('only adds the workspace id to redirect URLs when one exists', () => {
    expect(buildWorkspaceBlackboardRedirectQuery('ws-2')).toBe('workspaceId=ws-2');
    expect(buildWorkspaceBlackboardRedirectQuery()).toBe('');
  });
});
