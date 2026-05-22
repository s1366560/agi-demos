/**
 * AgentWorkspace - Tenant-level AI Agent Workspace
 *
 * Allows users to access Agent Chat from tenant main menu,
 * with project selector for choosing which project's context to use.
 */

import { Suspense, lazy, useState, useEffect, useCallback, useMemo } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { Empty as AntEmpty } from 'antd';

import { LazyEmpty, LazySpin, LazyButton } from '@/components/ui/lazyAntd';

import { useBlackboardSSE } from '../../hooks/useBlackboardSSE';
import { useConversationListAutoRefresh } from '../../hooks/useConversationListAutoRefresh';
import { useLocalStorage } from '../../hooks/useLocalStorage';
import { useAgentV3Store } from '../../stores/agentV3';
import { useAuthStore } from '../../stores/auth';
import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';

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
  const loadConversations = useAgentV3Store((state) => state.loadConversations);

  // Resolve the effective tenant id early so localStorage keys can be scoped
  // by tenant. Without scoping, switching tenants would leak the previous
  // tenant's project id and produce a 404 on first load.
  const tenantId = useMemo(
    () => urlTenantId || currentTenant?.id || user?.tenant_id,
    [urlTenantId, currentTenant?.id, user?.tenant_id]
  );

  // Tenant-scoped storage keys. Falls back to "global" when the tenant id
  // is not yet known so the hook receives a stable key.
  const tenantScope = tenantId ?? 'global';
  const lastProjectIdKey = `agent:${tenantScope}:lastProjectId`;
  const lastWorkspaceIdKey = `agent:${tenantScope}:lastWorkspaceId`;

  // Track selected project for this session - using useLocalStorage for better performance
  const { value: lastProjectId, setValue: setLastProjectId } = useLocalStorage<string | null>(
    lastProjectIdKey,
    null
  );
  const { value: lastWorkspaceId, setValue: setLastWorkspaceId } = useLocalStorage<string | null>(
    lastWorkspaceIdKey,
    null
  );
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [initializing, setInitializing] = useState(true);
  const queryProjectId = searchParams.get('projectId');
  const queryWorkspaceId = searchParams.get('workspaceId');
  const effectiveWorkspaceId = queryWorkspaceId || (routeConversationId ? null : lastWorkspaceId);
  useEffect(() => {
    if (queryWorkspaceId) {
      setLastWorkspaceId(queryWorkspaceId);
    }
  }, [queryWorkspaceId, setLastWorkspaceId]);
  const navigationQuery = useMemo(() => {
    const params = new URLSearchParams();
    if (queryProjectId) params.set('projectId', queryProjectId);
    if (effectiveWorkspaceId) params.set('workspaceId', effectiveWorkspaceId);
    const serialized = params.toString();
    return serialized.length > 0 ? serialized : undefined;
  }, [queryProjectId, effectiveWorkspaceId]);

  // Subscribe to workspace SSE events for real-time group chat updates
  useBlackboardSSE(effectiveWorkspaceId);
  useConversationListAutoRefresh(selectedProjectId);

  // Calculate base path for conversation navigation - memoized
  const basePath = useMemo(
    () => (tenantId ? `/tenant/${tenantId}/agent-workspace` : '/tenant/agent-workspace'),
    [tenantId]
  );

  // Navigate to create project - memoized callback
  const handleCreateProject = useCallback(() => {
    void navigate('/tenant/projects/new');
  }, [navigate]);

  // Load projects on mount - optimized with removed function dependency
  useEffect(() => {
    const loadProjects = async () => {
      if (tenantId && projects.length === 0) {
        await listProjects(tenantId);
      }
    };
    void loadProjects();
    // Only depend on tenantId - listProjects is stable from store
  }, [tenantId, listProjects, projects.length]);

  // Initialize selected project after projects are loaded
  useEffect(() => {
    const cancellation = { current: false };
    const isCancelled = () => cancellation.current;

    const init = async () => {
      if (queryProjectId) {
        if (isCancelled()) return;
        setSelectedProjectId(queryProjectId);
        setInitializing(false);

        if (
          tenantId &&
          currentProject?.id !== queryProjectId &&
          !projects.find((p: Project) => p.id === queryProjectId)
        ) {
          try {
            const project = await getProject(tenantId, queryProjectId);
            if (isCancelled()) return;
            setCurrentProject(project);
          } catch (error) {
            console.warn('AgentWorkspace: failed to load project from URL', error);
          }
        }
      } else if (lastProjectId && projects.find((p: Project) => p.id === lastProjectId)) {
        // Try to restore last selected project from localStorage (now using cached hook)
        if (isCancelled()) return;
        setSelectedProjectId(lastProjectId);
      } else if (currentProject) {
        if (isCancelled()) return;
        setSelectedProjectId(currentProject.id);
      } else if (projects.length > 0) {
        if (isCancelled()) return;
        setSelectedProjectId(projects[0]?.id ?? null);
      }

      if (!isCancelled() && (projects.length > 0 || queryProjectId)) {
        setInitializing(false);
      }
    };
    void init();
    return () => {
      cancellation.current = true;
    };
  }, [
    projects,
    currentProject,
    lastProjectId,
    queryProjectId,
    tenantId,
    getProject,
    setCurrentProject,
  ]);

  // Load conversations when project changes
  useEffect(() => {
    if (!selectedProjectId) {
      return;
    }
    // Defect #15: cancel any in-flight conversation list request when the
    // user switches projects so a slow response can't overwrite the newer
    // project's list.
    const controller = new AbortController();
    void loadConversations(selectedProjectId, controller.signal);
    // Persist selection using cached hook
    setLastProjectId(selectedProjectId);
    // Update global current project for consistency
    const project = projects.find((p: Project) => p.id === selectedProjectId);
    if (project) {
      setCurrentProject(project);
    }
    return () => {
      controller.abort();
    };
  }, [selectedProjectId, loadConversations, projects, setCurrentProject, setLastProjectId]);

  const effectiveProjectId =
    queryProjectId ||
    selectedProjectId ||
    currentProject?.id ||
    (projects.length > 0 ? (projects[0]?.id ?? null) : null);

  // Show loading while initializing projects
  if (initializing) {
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

  if (projects.length === 0 && !effectiveProjectId) {
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
