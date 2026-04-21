import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useWorkspaceActions } from '@/stores/workspace';

import { workspaceService } from '@/services/workspaceService';

import {
  resolveRequestedWorkspaceSelection,
  syncBlackboardWorkspaceSearchParams,
} from '@/pages/project/blackboardRouteUtils';

import type { Workspace } from '@/types/workspace';

interface BlackboardLifecycleParams {
  tenantId: string | undefined;
  projectId: string | undefined;
  requestedWorkspaceId: string | null;
  searchParams: URLSearchParams;
  setSearchParams: (params: URLSearchParams, options?: { replace?: boolean }) => void;
  currentWorkspaceId: string | undefined;
}

interface BlackboardLifecycleResult {
  workspaces: Workspace[];
  selectedWorkspaceId: string | null;
  setSelectedWorkspaceId: React.Dispatch<React.SetStateAction<string | null>>;
  workspacesLoading: boolean;
  workspacesError: string | null;
  surfaceLoading: boolean;
  handleRetrySurface: () => Promise<void>;
}

export function useBlackboardLifecycle({
  tenantId,
  projectId,
  requestedWorkspaceId,
  searchParams,
  setSearchParams,
  currentWorkspaceId: _currentWorkspaceId,
}: BlackboardLifecycleParams): BlackboardLifecycleResult {
  const { loadWorkspaceSurface, clearSelectedHex } = useWorkspaceActions();

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null);
  const [workspacesLoading, setWorkspacesLoading] = useState(true);
  const [workspacesError, setWorkspacesError] = useState<string | null>(null);
  const [surfaceLoading, setSurfaceLoading] = useState(false);
  const workspaceListRequestIdRef = useRef(0);
  const requestedWorkspaceIdRef = useRef(requestedWorkspaceId);
  const appliedRequestedWorkspaceIdRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      clearSelectedHex();
    };
  }, [clearSelectedHex]);

  useEffect(() => {
    requestedWorkspaceIdRef.current = requestedWorkspaceId;
  }, [requestedWorkspaceId]);

  const loadWorkspaces = useCallback(async () => {
    if (!tenantId || !projectId) {
      return;
    }

    const requestId = ++workspaceListRequestIdRef.current;
    setWorkspacesLoading(true);
    setWorkspacesError(null);

    try {
      const result = await workspaceService.listByProject(tenantId, projectId);
      if (requestId !== workspaceListRequestIdRef.current) {
        return;
      }
      setWorkspaces(result);
      setSelectedWorkspaceId((current) =>
        requestedWorkspaceIdRef.current &&
          result.some((workspace) => workspace.id === requestedWorkspaceIdRef.current)
          ? requestedWorkspaceIdRef.current
          : result.some((workspace) => workspace.id === current)
            ? current
            : (result[0]?.id ?? null)
      );
    } catch (loadError: unknown) {
      if (requestId !== workspaceListRequestIdRef.current) {
        return;
      }
      setWorkspacesError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      if (requestId === workspaceListRequestIdRef.current) {
        setWorkspacesLoading(false);
      }
    }
  }, [projectId, tenantId]);

  useEffect(() => {
    void loadWorkspaces();
  }, [loadWorkspaces]);

  const hydrateSurface = useCallback(async () => {
    if (!tenantId || !projectId || !selectedWorkspaceId) {
      return;
    }

    await loadWorkspaceSurface(tenantId, projectId, selectedWorkspaceId);
  }, [loadWorkspaceSurface, projectId, selectedWorkspaceId, tenantId]);

  useEffect(() => {
    let cancelled = false;

    const loadSurface = async () => {
      setSurfaceLoading(true);
      try {
        await hydrateSurface();
      } catch {
        // The workspace store exposes the load failure via state.error for this page.
      } finally {
        if (!cancelled) {
          setSurfaceLoading(false);
        }
      }
    };

    void loadSurface();

    return () => {
      cancelled = true;
    };
  }, [hydrateSurface]);

  useEffect(() => {
    if (!requestedWorkspaceId) {
      appliedRequestedWorkspaceIdRef.current = null;
      return;
    }

    const nextRequestedWorkspaceId = resolveRequestedWorkspaceSelection(
      requestedWorkspaceId,
      appliedRequestedWorkspaceIdRef.current,
      workspaces
    );
    if (!nextRequestedWorkspaceId) {
      return;
    }

    appliedRequestedWorkspaceIdRef.current = nextRequestedWorkspaceId;
    setSelectedWorkspaceId(nextRequestedWorkspaceId);
  }, [requestedWorkspaceId, workspaces]);

  useEffect(() => {
    if (workspacesLoading || workspaces.length > 0) {
      return;
    }
    if (!searchParams.has('open') && !searchParams.has('workspaceId')) {
      return;
    }

    const nextSearchParams = new URLSearchParams(searchParams);
    nextSearchParams.delete('open');
    nextSearchParams.delete('workspaceId');
    setSearchParams(nextSearchParams, { replace: true });
  }, [searchParams, setSearchParams, workspaces, workspacesLoading]);

  useEffect(() => {
    const nextSearchParams = syncBlackboardWorkspaceSearchParams(searchParams, {
      selectedWorkspaceId,
      workspacesLoading,
    });

    if (!nextSearchParams) {
      return;
    }

    setSearchParams(nextSearchParams, { replace: true });
  }, [searchParams, selectedWorkspaceId, setSearchParams, workspacesLoading]);

  const handleRetrySurface = useCallback(async () => {
    setSurfaceLoading(true);
    try {
      await hydrateSurface();
    } catch {
      // The workspace store exposes the load failure via state.error for this page.
    } finally {
      setSurfaceLoading(false);
    }
  }, [hydrateSurface]);

  return useMemo(
    () => ({
      workspaces,
      selectedWorkspaceId,
      setSelectedWorkspaceId,
      workspacesLoading,
      workspacesError,
      surfaceLoading,
      handleRetrySurface,
    }),
    [
      workspaces,
      selectedWorkspaceId,
      workspacesLoading,
      workspacesError,
      surfaceLoading,
      handleRetrySurface,
    ]
  );
}
