/**
 * AgentWorkspace - Tenant-level AI Agent Workspace
 *
 * Allows users to access Agent Chat from tenant main menu,
 * with project selector for choosing which project's context to use.
 */

import { Suspense, lazy, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { Empty as AntEmpty } from 'antd';
import { AlertCircle, RefreshCw } from 'lucide-react';

import { LazyEmpty, LazySpin, LazyButton } from '@/components/ui/lazyAntd';

import { useBlackboardSSE } from '../../hooks/useBlackboardSSE';
import { useConversationListAutoRefresh } from '../../hooks/useConversationListAutoRefresh';
import { useLocalStorage } from '../../hooks/useLocalStorage';
import { useAuthStore } from '../../stores/auth';
import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';
import { getErrorMessage } from '../../types/common';
import {
  getDefaultProject,
  lastProjectSelectionSourceStorageKey,
  MANUAL_PROJECT_SELECTION_SOURCE,
} from '../../utils/projectSelectionPersistence';

import type { Project } from '../../types/memory';

const AgentChatContent = lazy(() =>
  import('../../components/agent/AgentChatContent').then((module) => ({
    default: module.AgentChatContent,
  }))
);

const ContextDetailPanel = lazy(() =>
  import('../../components/agent/context/ContextDetailPanel').then((module) => ({
    default: module.ContextDetailPanel,
  }))
);

const AGENT_WORKSPACE_PROJECT_WINDOW_SIZE = 25;

function WorkspacePanelFallback() {
  const { t } = useTranslation();

  return (
    <div className="max-w-full mx-auto w-full h-full flex items-center justify-center">
      <div className="text-center">
        <LazySpin size="large" />
        <div className="mt-2 text-slate-500 dark:text-slate-400">
          {t('agent.workspace.loading')}
        </div>
      </div>
    </div>
  );
}

/**
 * AgentWorkspace - Main component for tenant-level agent access
 */
export const AgentWorkspace: FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { tenantId: urlTenantId, conversation: routeConversationId } = useParams<{
    tenantId?: string | undefined;
    conversation?: string | undefined;
  }>();
  const [searchParams] = useSearchParams();

  // Store subscriptions - select only what we need
  const user = useAuthStore((state) => state.user);
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const projects = useProjectStore((state) => state.projects);
  const currentProject = useProjectStore((state) => state.currentProject);
  const setCurrentProject = useProjectStore((state) => state.setCurrentProject);
  const listProjects = useProjectStore((state) => state.listProjects);
  const getProject = useProjectStore((state) => state.getProject);

  // Resolve the effective tenant id early so localStorage keys can be scoped
  // by tenant. Without scoping, switching tenants would leak the previous
  // tenant's project id and produce a 404 on first load.
  const tenantId = useMemo(
    () => urlTenantId || currentTenant?.id || user?.tenant_id,
    [urlTenantId, currentTenant?.id, user?.tenant_id]
  );
  const tenantCurrentProject =
    tenantId && currentProject?.tenant_id === tenantId ? currentProject : null;
  const tenantProjects = useMemo(
    () => (tenantId ? projects.filter((project) => project.tenant_id === tenantId) : []),
    [projects, tenantId]
  );

  // Tenant-scoped storage keys. Falls back to "global" when the tenant id
  // is not yet known so the hook receives a stable key.
  const tenantScope = tenantId ?? 'global';
  const lastProjectIdKey = `agent:${tenantScope}:lastProjectId`;
  const lastProjectSelectionSourceKey =
    lastProjectSelectionSourceStorageKey(tenantId) ??
    `agent:${tenantScope}:lastProjectSelectionSource`;
  const lastWorkspaceIdKey = `agent:${tenantScope}:lastWorkspaceId`;

  // Track selected project for this session - using useLocalStorage for better performance
  const { value: lastProjectId, setValue: setLastProjectId } = useLocalStorage<string | null>(
    lastProjectIdKey,
    null
  );
  const { value: lastProjectSelectionSource, setValue: setLastProjectSelectionSource } =
    useLocalStorage<string | null>(lastProjectSelectionSourceKey, null);
  const { value: lastWorkspaceId, setValue: setLastWorkspaceId } = useLocalStorage<string | null>(
    lastWorkspaceIdKey,
    null
  );
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [resolvedStoredProject, setResolvedStoredProject] = useState<Project | null>(null);
  const [invalidQueryProjectId, setInvalidQueryProjectId] = useState<string | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [projectLoadError, setProjectLoadError] = useState<string | null>(null);
  const previousTenantIdRef = useRef<string | undefined>(tenantId);
  const queryProjectId = searchParams.get('projectId');
  const queryWorkspaceId = searchParams.get('workspaceId');
  const tenantCurrentProjectId = tenantCurrentProject?.id ?? null;
  const tenantProjectsWithResolvedStoredProject = useMemo(() => {
    if (!tenantId) {
      return tenantProjects;
    }

    let resolvedProjects = tenantProjects;
    if (
      tenantCurrentProject?.tenant_id === tenantId &&
      !resolvedProjects.some((project) => project.id === tenantCurrentProject.id)
    ) {
      resolvedProjects = [...resolvedProjects, tenantCurrentProject];
    }
    if (
      resolvedStoredProject?.tenant_id === tenantId &&
      !resolvedProjects.some((project) => project.id === resolvedStoredProject.id)
    ) {
      resolvedProjects = [...resolvedProjects, resolvedStoredProject];
    }
    return resolvedProjects;
  }, [resolvedStoredProject, tenantCurrentProject, tenantId, tenantProjects]);
  const isQueryProjectInvalid = !!queryProjectId && invalidQueryProjectId === queryProjectId;
  const queryProjectInTenant =
    queryProjectId && !isQueryProjectInvalid
      ? tenantProjectsWithResolvedStoredProject.some((project) => project.id === queryProjectId)
      : false;
  const shouldResolveQueryProject =
    !!queryProjectId && !isQueryProjectInvalid && !queryProjectInTenant && !!tenantId;
  const storedManualProjectId =
    lastProjectSelectionSource === MANUAL_PROJECT_SELECTION_SOURCE && lastProjectId
      ? lastProjectId
      : null;
  const storedProjectIdInTenant =
    storedManualProjectId &&
    tenantProjectsWithResolvedStoredProject.some((project) => project.id === storedManualProjectId)
      ? storedManualProjectId
      : null;
  const storedProjectIdNeedsFetch =
    storedManualProjectId && !storedProjectIdInTenant ? storedManualProjectId : null;
  const shouldResolveStoredProject =
    !queryProjectId &&
    !!storedProjectIdNeedsFetch &&
    resolvedStoredProject?.id !== storedProjectIdNeedsFetch;
  const defaultTenantProjectId =
    getDefaultProject(tenantProjectsWithResolvedStoredProject)?.id ?? null;
  const firstTenantProjectId =
    defaultTenantProjectId ?? tenantProjectsWithResolvedStoredProject[0]?.id ?? null;
  const tenantProjectCount = tenantProjectsWithResolvedStoredProject.length;
  const activeSelectedProjectId =
    selectedProjectId &&
    tenantProjectsWithResolvedStoredProject.some((project) => project.id === selectedProjectId)
      ? selectedProjectId
      : null;
  const effectiveWorkspaceId =
    queryProjectId && !queryProjectInTenant
      ? null
      : queryWorkspaceId
        ? queryWorkspaceId
        : routeConversationId
          ? null
          : lastWorkspaceId;
  useEffect(() => {
    if (queryWorkspaceId && queryProjectInTenant) {
      setLastWorkspaceId(queryWorkspaceId);
    }
  }, [queryProjectInTenant, queryWorkspaceId, setLastWorkspaceId]);
  const navigationQuery = useMemo(() => {
    const params = new URLSearchParams();
    if (queryProjectId && queryProjectInTenant) params.set('projectId', queryProjectId);
    if (effectiveWorkspaceId) params.set('workspaceId', effectiveWorkspaceId);
    const serialized = params.toString();
    return serialized.length > 0 ? serialized : undefined;
  }, [effectiveWorkspaceId, queryProjectId, queryProjectInTenant]);

  // Subscribe to workspace SSE events for real-time group chat updates
  useBlackboardSSE(effectiveWorkspaceId);
  useConversationListAutoRefresh(activeSelectedProjectId);

  useEffect(() => {
    const previousTenantId = previousTenantIdRef.current;
    previousTenantIdRef.current = tenantId;
    if (previousTenantId === tenantId) {
      return;
    }

    setSelectedProjectId(null);
    setResolvedStoredProject(null);
    setInvalidQueryProjectId(null);
    setProjectLoadError(null);
    setInitializing(true);
  }, [tenantId]);

  useEffect(() => {
    setResolvedStoredProject((project) => (project?.tenant_id === tenantId ? project : null));
  }, [tenantId]);

  useEffect(() => {
    setInvalidQueryProjectId((projectId) => (projectId === queryProjectId ? projectId : null));
  }, [queryProjectId]);

  // Calculate base path for conversation navigation - memoized
  const basePath = useMemo(
    () => (tenantId ? `/tenant/${tenantId}/agent-workspace` : '/tenant/agent-workspace'),
    [tenantId]
  );

  // Navigate to create project - memoized callback
  const handleCreateProject = useCallback(() => {
    void navigate(tenantId ? `/tenant/${tenantId}/projects/new` : '/tenant/projects/new');
  }, [navigate, tenantId]);

  const loadProjectsForTenant = useCallback(async () => {
    if (!tenantId) return;

    setProjectLoadError(null);
    try {
      await listProjects(tenantId, { page: 1, page_size: AGENT_WORKSPACE_PROJECT_WINDOW_SIZE });
    } catch (error) {
      const message = getErrorMessage(error);
      setProjectLoadError(
        message === 'An unknown error occurred'
          ? t('agent.workspace.projectsLoadFailed', 'Failed to load projects')
          : message
      );
    } finally {
      setInitializing(false);
    }
  }, [tenantId, listProjects, t]);

  const handleRetryProjectLoad = useCallback(() => {
    setInitializing(true);
    void loadProjectsForTenant();
  }, [loadProjectsForTenant]);

  const clearRouteProjectSelection = useCallback(() => {
    const params = new URLSearchParams(searchParams);
    params.delete('projectId');
    params.delete('workspaceId');
    const serialized = params.toString();
    void navigate(
      {
        pathname: basePath,
        search: serialized ? `?${serialized}` : '',
      },
      { replace: true }
    );
  }, [basePath, navigate, searchParams]);

  // Load projects on mount - optimized with removed function dependency
  useEffect(() => {
    if (tenantId && tenantProjects.length === 0) {
      void loadProjectsForTenant();
    }
  }, [tenantId, loadProjectsForTenant, tenantProjects.length]);

  // Initialize selected project after projects are loaded
  useEffect(() => {
    const cancellation = { current: false };
    const isCancelled = () => cancellation.current;

    const init = async () => {
      if (queryProjectId) {
        if (isQueryProjectInvalid) {
          if (selectedProjectId === queryProjectId) {
            setSelectedProjectId(null);
          }
          if (initializing) {
            setInitializing(false);
          }
          return;
        }

        if (isCancelled()) return;
        if (queryProjectInTenant) {
          if (selectedProjectId !== queryProjectId) {
            setSelectedProjectId(queryProjectId);
          }
          if (initializing) {
            setInitializing(false);
          }
        } else if (tenantId) {
          try {
            const project = await getProject(tenantId, queryProjectId);
            if (isCancelled()) return;
            if (project.tenant_id !== tenantId) {
              throw new Error('URL project belongs to another tenant');
            }
            setResolvedStoredProject(project);
            if (selectedProjectId !== project.id) {
              setSelectedProjectId(project.id);
            }
            if (project.id !== tenantCurrentProjectId) {
              setCurrentProject(project);
            }
          } catch (error) {
            if (isCancelled()) return;
            console.warn('AgentWorkspace: failed to load project from URL', error);
            setInvalidQueryProjectId(queryProjectId);
            if (selectedProjectId === queryProjectId) {
              setSelectedProjectId(null);
            }
            if (lastProjectId === queryProjectId) {
              setLastProjectId(null);
              setLastProjectSelectionSource(null);
            }
            if (queryWorkspaceId) {
              setLastWorkspaceId(null);
            }
            clearRouteProjectSelection();
          } finally {
            if (!isCancelled() && initializing) {
              setInitializing(false);
            }
          }
        } else if (initializing) {
          setInitializing(false);
        }
      } else if (storedProjectIdInTenant) {
        // Try to restore last selected project from localStorage (now using cached hook)
        if (isCancelled()) return;
        if (selectedProjectId !== storedProjectIdInTenant) {
          setSelectedProjectId(storedProjectIdInTenant);
        }
      } else if (storedProjectIdNeedsFetch && tenantId) {
        try {
          const project = await getProject(tenantId, storedProjectIdNeedsFetch);
          if (isCancelled()) return;
          if (project.tenant_id !== tenantId) {
            throw new Error('Stored project belongs to another tenant');
          }
          setResolvedStoredProject(project);
          if (selectedProjectId !== project.id) {
            setSelectedProjectId(project.id);
          }
          if (tenantCurrentProjectId !== project.id) {
            setCurrentProject(project);
          }
        } catch (error) {
          if (isCancelled()) return;
          console.warn('AgentWorkspace: failed to restore stored project', error);
          if (selectedProjectId === storedProjectIdNeedsFetch) {
            setSelectedProjectId(null);
          }
          setLastProjectId(null);
          setLastProjectSelectionSource(null);
        }
      } else if (tenantCurrentProjectId) {
        if (isCancelled()) return;
        if (selectedProjectId !== tenantCurrentProjectId) {
          setSelectedProjectId(tenantCurrentProjectId);
        }
      } else if (firstTenantProjectId) {
        if (isCancelled()) return;
        if (selectedProjectId !== firstTenantProjectId) {
          setSelectedProjectId(firstTenantProjectId);
        }
      }

      if (!isCancelled() && initializing && (tenantProjectCount > 0 || queryProjectId)) {
        setInitializing(false);
      }
    };
    void init();
    return () => {
      cancellation.current = true;
    };
  }, [
    clearRouteProjectSelection,
    firstTenantProjectId,
    getProject,
    initializing,
    isQueryProjectInvalid,
    lastProjectId,
    queryProjectInTenant,
    queryProjectId,
    queryWorkspaceId,
    setCurrentProject,
    setLastProjectId,
    setLastProjectSelectionSource,
    setLastWorkspaceId,
    selectedProjectId,
    storedProjectIdNeedsFetch,
    storedProjectIdInTenant,
    tenantId,
    tenantCurrentProjectId,
    tenantProjectCount,
  ]);

  // Persist explicit route project selection and keep the global project scope aligned.
  // Conversation list loading is owned by the sidebar/chat surfaces and
  // deduplicated in the agent store so tenant switches do not fan out requests.
  useEffect(() => {
    if (!activeSelectedProjectId) {
      return;
    }
    if (queryProjectId && lastProjectId !== activeSelectedProjectId) {
      setLastProjectId(activeSelectedProjectId);
      setLastProjectSelectionSource(MANUAL_PROJECT_SELECTION_SOURCE);
    }
    // Update global current project for consistency
    const project = tenantProjectsWithResolvedStoredProject.find(
      (p: Project) => p.id === activeSelectedProjectId
    );
    if (project && tenantCurrentProjectId !== project.id) {
      setCurrentProject(project);
    }
  }, [
    activeSelectedProjectId,
    lastProjectId,
    queryProjectId,
    tenantCurrentProjectId,
    tenantProjectsWithResolvedStoredProject,
    setCurrentProject,
    setLastProjectId,
    setLastProjectSelectionSource,
  ]);

  const effectiveProjectId =
    activeSelectedProjectId ||
    tenantCurrentProject?.id ||
    (tenantProjectsWithResolvedStoredProject.length > 0
      ? (tenantProjectsWithResolvedStoredProject[0]?.id ?? null)
      : null);

  // Show loading while initializing projects
  if (initializing || shouldResolveStoredProject || shouldResolveQueryProject) {
    return (
      <div className="max-w-full mx-auto w-full h-full flex items-center justify-center">
        <div className="text-center">
          <LazySpin size="large" />
          <div className="mt-2 text-slate-500 dark:text-slate-400">
            {t('agent.workspace.loading')}
          </div>
        </div>
      </div>
    );
  }

  if (
    projectLoadError &&
    tenantProjectsWithResolvedStoredProject.length === 0 &&
    !effectiveProjectId
  ) {
    return (
      <div className="max-w-full mx-auto w-full h-full flex items-center justify-center">
        <div
          role="alert"
          className="bg-white dark:bg-surface-dark rounded-xl border border-red-200 dark:border-red-900/60 shadow-sm p-8 max-w-lg text-center"
        >
          <AlertCircle size={32} className="mx-auto text-red-500 dark:text-red-400" />
          <p className="mt-4 text-base font-semibold text-slate-900 dark:text-white">
            {t('agent.workspace.projectsLoadFailed', 'Failed to load projects')}
          </p>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300 break-words">
            {projectLoadError}
          </p>
          <LazyButton
            type="primary"
            icon={<RefreshCw size={14} />}
            className="mt-5"
            onClick={handleRetryProjectLoad}
          >
            {t('common.retry', 'Retry')}
          </LazyButton>
        </div>
      </div>
    );
  }

  if (tenantProjectsWithResolvedStoredProject.length === 0 && !effectiveProjectId) {
    return (
      <div className="max-w-full mx-auto w-full h-full flex items-center justify-center">
        <div className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm p-12 max-w-lg">
          <LazyEmpty
            description={t('agent.workspace.noProjects')}
            image={AntEmpty.PRESENTED_IMAGE_SIMPLE}
          >
            <LazyButton type="primary" onClick={handleCreateProject}>
              {t('agent.workspace.createProject')}
            </LazyButton>
          </LazyEmpty>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full relative">
      {effectiveProjectId ? (
        <Suspense fallback={<WorkspacePanelFallback />}>
          <AgentChatContent
            externalProjectId={effectiveProjectId}
            basePath={basePath}
            navigationQuery={navigationQuery}
            routeTenantId={tenantId}
            loadConversationList={false}
          />
          <ContextDetailPanel />
        </Suspense>
      ) : (
        <div className="h-full flex items-center justify-center">
          <LazyEmpty
            description={t('agent.workspace.selectProjectToStart')}
            image={AntEmpty.PRESENTED_IMAGE_SIMPLE}
          />
        </div>
      )}
    </div>
  );
};

export default AgentWorkspace;
