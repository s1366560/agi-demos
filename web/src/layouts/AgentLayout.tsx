/**
 * AgentLayout - Full-screen layout for Unified Agent Workspace
 *
 * Design Reference: design-prototype/agent_chat_interface/
 *                   design-prototype/unified_agent_workspace_-_idle_state_1/
 *
 * Layout Structure:
 * - Left sidebar: Navigation to project pages (256px / 80px collapsed)
 * - Main content area:
 *   - Top header: Breadcrumbs, agent status, view tabs, search
 *   - Content: Agent chat interface
 *
 * Features:
 * - Collapsible sidebar
 * - Agent online status indicator
 * - View tabs (Dashboard, Logs, Patterns)
 * - Responsive design
 */

import React, { useState, useEffect, useMemo, useRef } from 'react';

import { useTranslation } from 'react-i18next';
import { Outlet, useParams, useNavigate, Link, useLocation } from 'react-router-dom';

import { Search, History, GitBranch, Home, ChevronRight } from 'lucide-react';

import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { useProjectBasePath } from '@/hooks/useProjectBasePath';

import { getAgentConfig } from '@/config/navigation';

import { RouteErrorBoundary } from '@/components/common/RouteErrorBoundary';
import { AgentSidebar } from '@/components/layout/AppSidebar';
import { AppLauncher } from '@/components/mcp-app/AppLauncher';
import { LazyTooltip } from '@/components/ui/lazyAntd';

import { requestOpenAgentChatSearch } from '../components/agent/chat/searchEvents';

export const AgentLayout: React.FC = () => {
  const { t } = useTranslation();
  const { projectId, conversationId } = useParams<{
    projectId: string;
    conversationId?: string | undefined;
  }>();
  const currentProject = useProjectStore((state) => state.currentProject);
  const setCurrentProject = useProjectStore((state) => state.setCurrentProject);
  const projects = useProjectStore((state) => state.projects);
  const getProject = useProjectStore((state) => state.getProject);
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const navigate = useNavigate();
  const location = useLocation();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const { projectBasePath } = useProjectBasePath();
  const topTabs = useMemo(() => getAgentConfig().tabs, []);
  const projectSyncRequestRef = useRef(0);

  // Sync project data
  useEffect(() => {
    if (projectId && (!currentProject || currentProject.id !== projectId)) {
      const requestId = projectSyncRequestRef.current + 1;
      projectSyncRequestRef.current = requestId;
      const applyProject = (project: (typeof projects)[number]) => {
        if (projectSyncRequestRef.current === requestId) {
          setCurrentProject(project);
        }
      };
      const reportError = (error: unknown) => {
        if (projectSyncRequestRef.current === requestId) {
          console.error(error);
        }
      };
      const project = projects.find((p) => p.id === projectId);
      if (project) {
        applyProject(project);
      } else if (currentTenant) {
        getProject(currentTenant.id, projectId).then(applyProject).catch(reportError);
      }
      return () => {
        projectSyncRequestRef.current += 1;
      };
    }
    return undefined;
  }, [projectId, currentProject, projects, currentTenant, setCurrentProject, getProject]);

  // Determine active top tab based on current path
  const getActiveTab = () => {
    const pathSegments = location.pathname.split('/');
    const lastSegment = pathSegments[pathSegments.length - 1];
    if (lastSegment === 'logs') return 'logs';
    if (lastSegment === 'patterns') return 'patterns';
    return 'dashboard';
  };

  const activeTab = getActiveTab();

  const handleTabClick = (tab: { id: string; path: string }) => {
    if (projectId) {
      const agentBasePath = `${projectBasePath}/agent`;
      void navigate(tab.path ? `${agentBasePath}/${tab.path}` : agentBasePath);
    }
  };

  return (
    <div className="flex h-screen overflow-hidden bg-background-light dark:bg-background-dark">
      {/* Left Sidebar Navigation - using new component */}
      <AgentSidebar
        projectId={projectId}
        conversationId={conversationId}
        collapsed={sidebarCollapsed}
        onCollapseToggle={() => {
          setSidebarCollapsed(!sidebarCollapsed);
        }}
      />

      {/* Main Workspace Area */}
      <main className="flex-1 flex flex-col relative overflow-hidden">
        {/* Top Navigation Bar */}
        <header className="h-16 flex items-center justify-between px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark shrink-0">
          <div className="flex items-center gap-4">
            {/* Breadcrumbs */}
            <nav className="flex items-center gap-2 text-sm">
              <Link
                to={projectBasePath}
                className="text-slate-400 hover:text-primary transition-colors"
              >
                <Home size={18} />
              </Link>
              <ChevronRight size={16} className="text-slate-300 dark:text-slate-600" />
              <Link
                to={projectBasePath}
                className="text-slate-500 hover:text-primary transition-colors font-medium"
              >
                {currentProject?.name ||
                  t('nav.project', {
                    defaultValue: 'Project',
                  })}
              </Link>
              <ChevronRight size={16} className="text-slate-300 dark:text-slate-600" />
              <span className="text-slate-900 dark:text-white font-bold">
                {t('nav.agent', {
                  defaultValue: 'Agent',
                })}
              </span>
            </nav>

            {/* Agent Status Badge */}
            <div className="flex items-center gap-1.5 px-2.5 py-1 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-800 rounded-full">
              <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse motion-reduce:animate-none"></div>
              <span className="text-2xs font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-tight">
                {t('agent.layout.online', {
                  defaultValue: 'Agent Online',
                })}
              </span>
            </div>

            {/* View Tabs */}
            <nav className="flex items-center gap-1 ml-4 bg-slate-100 dark:bg-slate-800/50 rounded-lg p-1">
              {topTabs.map((tab) => (
                <button
                  type="button"
                  key={tab.id}
                  onClick={() => {
                    handleTabClick(tab);
                  }}
                  className={`px-3 py-1.5 text-sm font-medium rounded-md transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 ${
                    activeTab === tab.id
                      ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-3">
            {/* Search */}
            <div className="relative hidden md:block group">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-primary w-4 h-4 transition-colors" />
              <button
                id="conversation-search"
                type="button"
                disabled={!conversationId}
                onClick={requestOpenAgentChatSearch}
                aria-label={t('agent.layout.searchCurrentConversation', {
                  defaultValue: 'Search current conversation',
                })}
                className="w-56 bg-slate-100 dark:bg-surface-dark border border-transparent focus:border-primary/30 rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary/20 transition-[color,background-color,border-color,box-shadow,opacity,transform] text-left text-text-muted disabled:cursor-not-allowed disabled:opacity-60"
              >
                <span className="block truncate">
                  {t('agent.layout.searchCurrentConversationPlaceholder', {
                    defaultValue: 'Search current conversation...',
                  })}
                </span>
              </button>
            </div>

            {/* Quick Actions */}
            <div className="flex items-center gap-1">
              <AppLauncher />
              <LazyTooltip
                title={t('agent.layout.viewExecutionHistory', {
                  defaultValue: 'View execution history',
                })}
              >
                <button
                  type="button"
                  aria-label={t('agent.layout.viewExecutionHistory', {
                    defaultValue: 'View execution history',
                  })}
                  className="p-2 bg-slate-100 dark:bg-slate-800 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors text-slate-600 dark:text-slate-400"
                  onClick={() => {
                    const tab = topTabs[1];
                    if (tab) handleTabClick(tab);
                  }}
                >
                  <History className="w-5 h-5" />
                </button>
              </LazyTooltip>
              <LazyTooltip
                title={t('agent.layout.viewWorkflowPatterns', {
                  defaultValue: 'View workflow patterns',
                })}
              >
                <button
                  type="button"
                  aria-label={t('agent.layout.viewWorkflowPatterns', {
                    defaultValue: 'View workflow patterns',
                  })}
                  className="p-2 bg-slate-100 dark:bg-slate-800 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors text-slate-600 dark:text-slate-400"
                  onClick={() => {
                    const tab = topTabs[2];
                    if (tab) handleTabClick(tab);
                  }}
                >
                  <GitBranch className="w-5 h-5" />
                </button>
              </LazyTooltip>
            </div>
          </div>
        </header>

        {/* Page Content */}
        <div className="flex-1 overflow-hidden">
          <RouteErrorBoundary context="Agent" fallbackPath={`${projectBasePath}/agent`}>
            <Outlet />
          </RouteErrorBoundary>
        </div>
      </main>
    </div>
  );
};

export default AgentLayout;
