/**
 * TenantLayout - Main layout for tenant-level pages
 *
 * Design Reference: design-prototype/tenant_console_-_overview_1/
 *
 * Layout Structure:
 * - Left sidebar: Agent conversation history (primary navigation)
 * - Main area: Header with breadcrumbs/search/tenant navigation, scrollable content
 *
 * Features:
 * - Agent-centric primary navigation (conversation history)
 * - Tenant pages moved to secondary navigation (header dropdown)
 * - Sidebar collapse toggle in header
 * - Responsive design
 * - Theme toggle
 * - Language switcher
 * - Workspace switcher
 */

import React, { useEffect, useLayoutEffect, useState, useCallback, memo, useRef } from 'react';

import { useTranslation } from 'react-i18next';
import { Outlet, useNavigate, useParams, useLocation } from 'react-router-dom';

import { AlertCircle, Brain, Loader2, RefreshCw } from 'lucide-react';

import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { useExecutionStore } from '@/stores/agent/executionStore';
import { useAgentHITLStore } from '@/stores/agent/hitlStore';
import { useStreamingStore } from '@/stores/agent/streamingStore';
import { useTimelineStore } from '@/stores/agent/timelineStore';
import { useAgentV3Store } from '@/stores/agentV3';
import { useAuthStore } from '@/stores/auth';
import { useProjectStore } from '@/stores/project';
import { useSandboxStore } from '@/stores/sandbox';
import { useTenantStore } from '@/stores/tenant';

import { agentService } from '@/services/agentService';
import { unifiedEventService } from '@/services/unifiedEventService';

import { TenantCreateModal } from '@/pages/tenant/TenantCreate';

// eslint-disable-next-line no-restricted-imports
import { BackgroundSubAgentPanel } from '@/components/agent/BackgroundSubAgentPanel';
// eslint-disable-next-line no-restricted-imports
import { MobileSidebarDrawer } from '@/components/agent/chat/MobileSidebarDrawer';
import { RouteErrorBoundary } from '@/components/common/RouteErrorBoundary';
import { TenantChatSidebar } from '@/components/layout/TenantChatSidebar';
import TenantHeader from '@/components/layout/TenantHeader';

import type { Tenant } from '@/types/memory';

// HTTP status codes for error handling
const HTTP_STATUS = {
  FORBIDDEN: 403,
  NOT_FOUND: 404,
} as const;

type TenantEntryStatus = 'idle' | 'loading' | 'empty' | 'error';

function getResponseStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object' || !('response' in error)) return undefined;
  const response = (error as { response?: unknown }).response;
  if (!response || typeof response !== 'object' || !('status' in response)) return undefined;
  const status = (response as { status?: unknown }).status;
  return typeof status === 'number' ? status : undefined;
}

function isBareTenantEntryPath(pathname: string): boolean {
  return pathname === '/tenant' || pathname === '/tenant/';
}

function resetTenantScopedRuntimeState(): void {
  useAgentV3Store.setState((state) => ({
    conversations: [],
    activeConversationId: null,
    isCreatingConversation: false,
    hasMoreConversations: false,
    conversationsTotal: 0,
    conversationStates: new Map(),
    conversationScopeGeneration: state.conversationScopeGeneration + 1,
  }));
  useConversationsStore.getState().reset();
  useTimelineStore.getState().reset();
  useStreamingStore.getState().reset();
  useExecutionStore.getState().reset();
  useAgentHITLStore.getState().syncFromConversation({
    pendingClarification: null,
    pendingDecision: null,
    pendingEnvVarRequest: null,
    pendingPermission: null,
    doomLoopDetected: null,
    costTracking: null,
    suggestions: [],
    pinnedEventIds: new Set(),
  });

  const sandboxStore = useSandboxStore.getState();
  sandboxStore.unsubscribeSSE();
  sandboxStore.reset();
  agentService.disconnect();
  unifiedEventService.disconnect();
}

/**
 * TenantLayout component
 */
export const TenantLayout: React.FC = memo(() => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { tenantId, projectId } = useParams();
  const queryProjectId = new URLSearchParams(location.search).get('projectId')?.trim() || undefined;
  const effectiveProjectId = projectId ?? queryProjectId;
  const tenantBasePath = tenantId ? `/tenant/${tenantId}` : '/tenant';
  const isAgentWorkspaceRoute =
    location.pathname === `${tenantBasePath}/agent-workspace` ||
    location.pathname.startsWith(`${tenantBasePath}/agent-workspace/`);

  // Optimized: Select only the state we need with typing
  const tenants = useTenantStore((state) => state.tenants);
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const setCurrentTenant = useTenantStore((state) => state.setCurrentTenant);
  const getTenant = useTenantStore((state) => state.getTenant);
  const listTenants = useTenantStore((state) => state.listTenants);

  const currentProject = useProjectStore((state) => state.currentProject);
  const clearProjects = useProjectStore((state) => state.clearProjects);

  // Auth store
  const logout = useAuthStore((state) => state.logout);

  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [tenantEntryStatus, setTenantEntryStatus] = useState<TenantEntryStatus>('idle');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const projectSyncRequestRef = useRef(0);
  const tenantProjectScopeRef = useRef<string | null | undefined>(undefined);
  const tenantProjectScope = tenantId ?? currentTenant?.id ?? null;
  const projectSyncTenantId = tenantId ?? currentTenant?.id ?? null;
  const shouldResolveBareTenantEntry =
    !tenantId && isBareTenantEntryPath(location.pathname) && !currentTenant && tenants.length === 0;
  const effectiveTenantEntryStatus =
    tenantEntryStatus === 'idle' && shouldResolveBareTenantEntry ? 'loading' : tenantEntryStatus;

  const handleLogout = useCallback(() => {
    logout();
    void navigate('/login');
  }, [logout, navigate]);

  const activateTenant = useCallback(
    (tenant: Tenant | null | undefined) => {
      if (!tenant) return false;

      setCurrentTenant(tenant);
      setTenantEntryStatus('idle');

      if (!tenantId && isBareTenantEntryPath(location.pathname)) {
        void navigate(`/tenant/${tenant.id}/overview`, { replace: true });
      }

      return true;
    },
    [location.pathname, navigate, setCurrentTenant, tenantId]
  );

  const handleCreateTenant = useCallback(async () => {
    await listTenants();
    const tenants = useTenantStore.getState().tenants;
    if (tenants.length > 0) {
      activateTenant(tenants[tenants.length - 1] ?? null);
    }
  }, [activateTenant, listTenants]);

  const activateAccessibleTenant = useCallback(
    async (requestedTenantId?: string) => {
      try {
        setTenantEntryStatus('loading');
        await listTenants();
        const tenantState = useTenantStore.getState();
        const requestedTenant = requestedTenantId
          ? (tenantState.tenants.find((tenant) => tenant.id === requestedTenantId) ?? null)
          : null;
        const currentTenantFromList = tenantState.currentTenant
          ? (tenantState.tenants.find((tenant) => tenant.id === tenantState.currentTenant?.id) ??
            null)
          : null;
        const fallbackTenant = requestedTenant ?? currentTenantFromList ?? tenantState.tenants[0];

        if (fallbackTenant) {
          activateTenant(fallbackTenant);
          if (
            !tenantId ||
            fallbackTenant.id !== tenantId ||
            isBareTenantEntryPath(location.pathname)
          ) {
            void navigate(`/tenant/${fallbackTenant.id}/overview`, { replace: true });
          }
          return true;
        }

        setTenantEntryStatus('empty');
        return false;
      } catch (listError) {
        console.error('Failed to list accessible tenants:', listError);
        setTenantEntryStatus('error');
        return false;
      }
    },
    [activateTenant, listTenants, location.pathname, navigate, tenantId]
  );

  /**
   * Handle 403/404 errors when accessing unauthorized tenant
   * Falls back to first accessible tenant
   */
  const handleTenantAccessError = useCallback(
    async (error: unknown, requestedTenantId: string) => {
      const status = getResponseStatus(error);

      if (status === HTTP_STATUS.FORBIDDEN || status === HTTP_STATUS.NOT_FOUND) {
        console.warn(
          `Access denied to tenant ${requestedTenantId}, falling back to accessible tenant`
        );

        await activateAccessibleTenant(requestedTenantId);
      }
    },
    [activateAccessibleTenant]
  );

  /**
   * Initialize tenant and project setup
   * Extracted to reduce nested Promise chains in useEffect
   */
  const initializeTenantAndProject = useCallback(async () => {
    if (currentTenant && (!tenantId || currentTenant.id === tenantId)) {
      setTenantEntryStatus('idle');
      if (!tenantId && isBareTenantEntryPath(location.pathname)) {
        void navigate(`/tenant/${currentTenant.id}/overview`, { replace: true });
      }
      return;
    }

    if (tenantId && (!currentTenant || currentTenant.id !== tenantId)) {
      const routeTenant = tenants.find((tenant) => tenant.id === tenantId);
      if (routeTenant) {
        activateTenant(routeTenant);
        return;
      }

      try {
        await getTenant(tenantId);
        if (useTenantStore.getState().currentTenant?.id === tenantId) {
          setTenantEntryStatus('idle');
        } else {
          await activateAccessibleTenant(tenantId);
        }
      } catch (error) {
        await handleTenantAccessError(error, tenantId);
      }
    } else if (!tenantId && !currentTenant) {
      if (tenants.length > 0) {
        activateTenant(tenants[0] ?? null);
      } else {
        await activateAccessibleTenant();
      }
    }
  }, [
    tenantId,
    tenants,
    currentTenant,
    location.pathname,
    navigate,
    getTenant,
    handleTenantAccessError,
    activateTenant,
    activateAccessibleTenant,
  ]);

  const handleRetryTenantLoad = useCallback(async () => {
    await activateAccessibleTenant();
  }, [activateAccessibleTenant]);

  // Sync tenant ID from URL with store - flattened for better performance
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void initializeTenantAndProject();
  }, [initializeTenantAndProject]);

  useLayoutEffect(() => {
    const previousTenantProjectScope = tenantProjectScopeRef.current;
    tenantProjectScopeRef.current = tenantProjectScope;

    if (
      previousTenantProjectScope !== undefined &&
      previousTenantProjectScope !== tenantProjectScope
    ) {
      projectSyncRequestRef.current += 1;
      clearProjects();
      resetTenantScopedRuntimeState();
    }
  }, [tenantProjectScope, clearProjects]);

  // Sync project ID from URL with store
  useEffect(() => {
    const requestId = projectSyncRequestRef.current + 1;
    projectSyncRequestRef.current = requestId;
    const requestProjectId = effectiveProjectId ?? null;
    const isCurrentProjectRequest = () => projectSyncRequestRef.current === requestId;
    const currentProjectMatchesRequest =
      !!requestProjectId &&
      currentProject?.id === requestProjectId &&
      (!projectSyncTenantId || currentProject.tenant_id === projectSyncTenantId);

    if (requestProjectId && projectSyncTenantId && !currentProjectMatchesRequest) {
      const { projects, setCurrentProject, getProject } = useProjectStore.getState();
      const project = projects.find(
        (p) => p.id === requestProjectId && p.tenant_id === projectSyncTenantId
      );
      if (project) {
        if (isCurrentProjectRequest()) {
          setCurrentProject(project);
        }
      } else if (!isAgentWorkspaceRoute) {
        getProject(projectSyncTenantId, requestProjectId)
          .then((p) => {
            if (isCurrentProjectRequest()) {
              setCurrentProject(p);
            }
          })
          .catch((error: unknown) => {
            if (isCurrentProjectRequest()) {
              console.error(error);
            }
          });
      }
    } else if (!requestProjectId && currentProject && !isAgentWorkspaceRoute) {
      useProjectStore.getState().setCurrentProject(null);
    }

    return () => {
      if (projectSyncRequestRef.current === requestId) {
        projectSyncRequestRef.current += 1;
      }
    };
  }, [effectiveProjectId, projectSyncTenantId, currentProject, isAgentWorkspaceRoute]);

  // Tenant entry status screen
  if (effectiveTenantEntryStatus !== 'idle') {
    const isLoadingTenantEntry = effectiveTenantEntryStatus === 'loading';
    const isTenantEntryError = effectiveTenantEntryStatus === 'error';
    const entryTitle = isLoadingTenantEntry
      ? t('tenant.entry.loadingTitle')
      : isTenantEntryError
        ? t('tenant.entry.errorTitle')
        : t('tenant.welcome');
    const entryDescription = isLoadingTenantEntry
      ? t('tenant.entry.loadingDescription')
      : isTenantEntryError
        ? t('tenant.entry.errorDescription')
        : t('tenant.noTenantDescription');

    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-background-light dark:bg-background-dark">
        <div className="mx-auto flex w-full max-w-md flex-col items-center space-y-6 p-6 text-center">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-3">
              {isLoadingTenantEntry ? (
                <Loader2
                  size={36}
                  className="animate-spin text-primary motion-reduce:animate-none"
                  aria-hidden="true"
                />
              ) : isTenantEntryError ? (
                <AlertCircle size={36} className="text-error" aria-hidden="true" />
              ) : (
                <Brain size={36} className="text-primary" aria-hidden="true" />
              )}
            </div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
              MemStack<span className="text-primary">.ai</span>
            </h1>
          </div>

          <div className="space-y-2">
            <h2 className="text-xl font-semibold text-slate-900 dark:text-white">{entryTitle}</h2>
            <p className="text-slate-600 dark:text-slate-300">{entryDescription}</p>
          </div>

          <div className="flex flex-col gap-4 w-full">
            {isTenantEntryError ? (
              <button
                type="button"
                onClick={() => {
                  void handleRetryTenantLoad();
                }}
                className="btn-primary flex w-full items-center justify-center gap-2 py-3"
              >
                <RefreshCw size={16} aria-hidden="true" />
                {t('common.retry')}
              </button>
            ) : null}
            {!isLoadingTenantEntry && !isTenantEntryError ? (
              <button
                type="button"
                onClick={() => {
                  setIsCreateModalOpen(true);
                }}
                className="btn-primary w-full py-3"
              >
                {t('tenant.create.action')}
              </button>
            ) : null}
            <button type="button" onClick={handleLogout} className="btn-secondary w-full py-3">
              {t('common.logout')}
            </button>
          </div>
        </div>

        <TenantCreateModal
          isOpen={isCreateModalOpen}
          onClose={() => {
            setIsCreateModalOpen(false);
          }}
          onSuccess={() => {
            void handleCreateTenant();
          }}
        />
      </div>
    );
  }

  const basePath = tenantBasePath;

  // Determine if the current page is an agent workspace (needs full-height, no scroll)
  // Non-agent pages: overview, projects, users, providers, analytics, etc.
  const NON_AGENT_SUBPATHS = [
    'overview',
    'tasks',
    'agents',
    'projects',
    'users',
    'providers',
    'analytics',
    'billing',
    'settings',
    'patterns',
    'subagents',
    'skills',
    'evolution',
    'profile',
    'mcp-servers',
    'agent-definitions',
    'agent-bindings',
    'plugins',
    'templates',
    'project',
    'instances',
    'instance-templates',
    'clusters',
    'genes',
    'audit-logs',
    'dead-letter-queue',
    'trust-policies',
    'decision-records',
    'deploy',
    'org-settings',
  ];
  const pathSegments = location.pathname.replace(basePath, '').split('/').filter(Boolean);
  const isFullHeightPath =
    pathSegments.length === 0 ||
    pathSegments[0] === 'agent-workspace' ||
    !NON_AGENT_SUBPATHS.includes(pathSegments[0] ?? '') ||
    (pathSegments[0] === 'project' && pathSegments.length >= 3 && pathSegments[2] === 'blackboard');

  return (
    <>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-[100] focus:p-4 focus:bg-white focus:text-primary dark:focus:bg-surface-dark dark:focus:text-primary-light"
      >
        Skip to main content
      </a>
      <div className="flex h-screen w-full overflow-hidden bg-background-light dark:bg-background-dark">
        {/* Sidebar - Agent Conversation History (Primary Navigation) */}
        <TenantChatSidebar
          tenantId={tenantId}
          collapsed={sidebarCollapsed}
          onCollapsedChange={setSidebarCollapsed}
        />

        {/* Mobile sidebar drawer */}
        <MobileSidebarDrawer
          open={mobileSidebarOpen}
          onClose={() => {
            setMobileSidebarOpen(false);
          }}
        >
          <TenantChatSidebar tenantId={tenantId} mobile />
        </MobileSidebarDrawer>

        {/* Main Content */}
        <main id="main-content" className="flex flex-col flex-1 h-full overflow-hidden relative">
          {/* Header */}
          <TenantHeader
            tenantId={tenantId || ''}
            sidebarCollapsed={sidebarCollapsed}
            onSidebarToggle={() => {
              setSidebarCollapsed(!sidebarCollapsed);
            }}
            onMobileMenuOpen={() => {
              setMobileSidebarOpen(true);
            }}
            projectId={projectId}
          />

          {/* Page Content */}
          <div
            className={`flex-1 relative ${
              isFullHeightPath ? 'overflow-hidden h-full' : 'overflow-y-auto p-4'
            }`}
          >
            <div className={isFullHeightPath ? 'h-full' : 'max-w-full'}>
              <RouteErrorBoundary context="Tenant" fallbackPath="/tenant">
                <Outlet />
              </RouteErrorBoundary>
            </div>
          </div>
        </main>
      </div>

      {/* Tenant Create Modal */}
      <TenantCreateModal
        isOpen={isCreateModalOpen}
        onClose={() => {
          setIsCreateModalOpen(false);
        }}
        onSuccess={() => {
          void handleCreateTenant();
        }}
      />

      {/* Background SubAgent Panel */}
      <BackgroundSubAgentPanel />
    </>
  );
});

TenantLayout.displayName = 'TenantLayout';
