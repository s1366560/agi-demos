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

import React, { useEffect, useState, useCallback, memo } from 'react';

import { useTranslation } from 'react-i18next';
import { Outlet, useNavigate, useParams, useLocation } from 'react-router-dom';

import { useAuthStore } from '@/stores/auth';
import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { TenantCreateModal } from '@/pages/tenant/TenantCreate';

// eslint-disable-next-line no-restricted-imports
import { BackgroundSubAgentPanel } from '@/components/agent/BackgroundSubAgentPanel';
// eslint-disable-next-line no-restricted-imports
import { MobileSidebarDrawer } from '@/components/agent/chat/MobileSidebarDrawer';
import { RouteErrorBoundary } from '@/components/common/RouteErrorBoundary';
import { TenantChatSidebar } from '@/components/layout/TenantChatSidebar';
import TenantHeader from '@/components/layout/TenantHeader';

// HTTP status codes for error handling
const HTTP_STATUS = {
  FORBIDDEN: 403,
  NOT_FOUND: 404,
} as const;

/**
 * TenantLayout component
 */
export const TenantLayout: React.FC = memo(() => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { tenantId, projectId } = useParams();

  // Optimized: Select only the state we need with typing
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const setCurrentTenant = useTenantStore((state) => state.setCurrentTenant);
  const getTenant = useTenantStore((state) => state.getTenant);
  const listTenants = useTenantStore((state) => state.listTenants);

  const currentProject = useProjectStore((state) => state.currentProject);

  // Auth store
  const logout = useAuthStore((state) => state.logout);
  const user = useAuthStore((state) => state.user);

  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [noTenants, setNoTenants] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  const handleLogout = useCallback(() => {
    logout();
    navigate('/login');
  }, [logout, navigate]);

  const handleCreateTenant = useCallback(async () => {
    await listTenants();
    const tenants = useTenantStore.getState().tenants;
    if (tenants.length > 0) {
      setCurrentTenant(tenants[tenants.length - 1]);
      setNoTenants(false);
    }
  }, [listTenants, setCurrentTenant]);

  /**
   * Handle 403/404 errors when accessing unauthorized tenant
   * Falls back to first accessible tenant
   */
  const handleTenantAccessError = useCallback(
    async (error: unknown, requestedTenantId: string) => {
      const status = (error as any)?.response?.status;

      if (status === HTTP_STATUS.FORBIDDEN || status === HTTP_STATUS.NOT_FOUND) {
        console.warn(
          `Access denied to tenant ${requestedTenantId}, falling back to accessible tenant`
        );

        try {
          await listTenants();
          const tenants = useTenantStore.getState().tenants;

          if (tenants.length > 0) {
            const firstAccessibleTenant = tenants[0];
            setCurrentTenant(firstAccessibleTenant);
            navigate(`/tenant/${firstAccessibleTenant.id}`, { replace: true });
          } else {
            setNoTenants(true);
          }
        } catch (listError) {
          console.error('Failed to list accessible tenants:', listError);
          setNoTenants(true);
        }
      }
    },
    [listTenants, setCurrentTenant, navigate]
  );

  /**
   * Initialize tenant and project setup
   * Extracted to reduce nested Promise chains in useEffect
   */
  const initializeTenantAndProject = useCallback(async () => {
    if (tenantId && (!currentTenant || currentTenant.id !== tenantId)) {
      try {
        await getTenant(tenantId);
      } catch (error) {
        await handleTenantAccessError(error, tenantId);
      }
    } else if (!tenantId && !currentTenant) {
      const tenants = useTenantStore.getState().tenants;
      if (tenants.length > 0) {
        setCurrentTenant(tenants[0]);
      } else {
        try {
          await listTenants();
          const updatedTenants = useTenantStore.getState().tenants;
          if (updatedTenants.length > 0) {
            setCurrentTenant(updatedTenants[0]);
          } else {
            // Auto-create default tenant
            const defaultName = user?.name ? `${user.name}'s Workspace` : 'My Workspace';
            try {
              await useTenantStore.getState().createTenant({
                name: defaultName,
                description: 'Automatically created default workspace',
              });
              const newTenants = useTenantStore.getState().tenants;
              if (newTenants.length > 0) {
                setCurrentTenant(newTenants[newTenants.length - 1]);
              } else {
                setNoTenants(true);
              }
            } catch (err) {
              console.error('Failed to auto-create tenant:', err);
              setNoTenants(true);
            }
          }
        } catch {
          // Silently handle listTenants failure
        }
      }
    }
  }, [
    tenantId,
    currentTenant,
    getTenant,
    handleTenantAccessError,
    listTenants,
    setCurrentTenant,
    user,
  ]);

  // Sync tenant ID from URL with store - flattened for better performance
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    initializeTenantAndProject();
  }, [initializeTenantAndProject]);

  // Sync project ID from URL with store
  useEffect(() => {
    if (projectId && currentTenant && (!currentProject || currentProject.id !== projectId)) {
      const { projects, setCurrentProject, getProject } = useProjectStore.getState();
      const project = projects.find((p) => p.id === projectId);
      if (project) {
        setCurrentProject(project);
      } else {
        getProject(currentTenant.id, projectId)
          .then((p) => {
            setCurrentProject(p);
          })
          .catch(console.error);
      }
    } else if (!projectId && currentProject) {
      useProjectStore.getState().setCurrentProject(null);
    }
  }, [projectId, currentTenant, currentProject]);

  // No tenants state - welcome screen
  if (noTenants) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-background-light dark:bg-background-dark">
        <div className="mx-auto flex w-full max-w-md flex-col items-center space-y-6 p-6 text-center">
          <div className="flex items-center gap-3">
            <div className="bg-primary/10 p-3 rounded-xl">
              <span className="material-symbols-outlined text-primary text-4xl">memory</span>
            </div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
              MemStack<span className="text-primary">.ai</span>
            </h1>
          </div>

          <div className="space-y-2">
            <h2 className="text-xl font-semibold text-slate-900 dark:text-white">
              {t('tenant.welcome')}
            </h2>
            <p className="text-slate-500 dark:text-slate-400">{t('tenant.noTenantDescription')}</p>
          </div>

          <div className="flex flex-col gap-4 w-full">
            <button onClick={() => setIsCreateModalOpen(true)} className="btn-primary w-full py-3">
              {t('tenant.create')}
            </button>
            <button onClick={handleLogout} className="btn-secondary w-full py-3">
              {t('common.logout')}
            </button>
          </div>
        </div>

        <TenantCreateModal
          isOpen={isCreateModalOpen}
          onClose={() => setIsCreateModalOpen(false)}
          onSuccess={handleCreateTenant}
        />
      </div>
    );
  }

  const basePath = tenantId ? `/tenant/${tenantId}` : '/tenant';

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
    'profile',
    'mcp-servers',
  ];
  const pathSegments = location.pathname.replace(basePath, '').split('/').filter(Boolean);
  const isAgentWorkspacePath =
    pathSegments.length === 0 ||
    pathSegments[0] === 'agent-workspace' ||
    !NON_AGENT_SUBPATHS.includes(pathSegments[0]);

  return (
    <>
      <div className="flex h-screen w-full overflow-hidden bg-background-light dark:bg-background-dark">
        {/* Sidebar - Agent Conversation History (Primary Navigation) */}
        <TenantChatSidebar
          tenantId={tenantId}
          collapsed={sidebarCollapsed}
          onCollapsedChange={setSidebarCollapsed}
        />

        {/* Mobile sidebar drawer */}
        <MobileSidebarDrawer open={mobileSidebarOpen} onClose={() => setMobileSidebarOpen(false)}>
          <TenantChatSidebar tenantId={tenantId} mobile />
        </MobileSidebarDrawer>

        {/* Main Content */}
        <main className="flex flex-col flex-1 h-full overflow-hidden relative">
          {/* Header */}
          <TenantHeader
            tenantId={tenantId || ''}
            sidebarCollapsed={sidebarCollapsed}
            onSidebarToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
            onMobileMenuOpen={() => setMobileSidebarOpen(true)}
          />

          {/* Page Content */}
          <div
            className={`flex-1 relative ${
              isAgentWorkspacePath ? 'overflow-hidden h-full' : 'overflow-y-auto p-4'
            }`}
          >
            <div className={`${isAgentWorkspacePath ? 'h-full' : 'max-w-full'}`}>
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
        onClose={() => setIsCreateModalOpen(false)}
        onSuccess={handleCreateTenant}
      />

      {/* Background SubAgent Panel */}
      <BackgroundSubAgentPanel />
    </>
  );
});

TenantLayout.displayName = 'TenantLayout';
