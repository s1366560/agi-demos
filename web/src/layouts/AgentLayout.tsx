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

import React, { useState, useEffect } from 'react'
import { Outlet, useParams, useNavigate, Link, useLocation } from 'react-router-dom'
import { Tooltip } from 'antd'
import { RouteErrorBoundary } from '@/components/common/RouteErrorBoundary'
import { AgentSidebar } from '@/components/layout/AgentSidebar'
import { useProjectStore } from '@/stores/project'
import { useTenantStore } from '@/stores/tenant'
import { useAuthStore } from '@/stores/auth'
import { Search, History, GitBranch } from 'lucide-react'

// Top navigation tabs for agent views
const TOP_TABS = [
    { id: 'dashboard', label: 'Dashboard', path: '' },
    { id: 'logs', label: 'Activity Logs', path: 'logs' },
    { id: 'patterns', label: 'Patterns', path: 'patterns' },
]

export const AgentLayout: React.FC = () => {
    const { projectId, conversationId } = useParams<{ projectId: string; conversationId?: string }>()
    const { currentProject, setCurrentProject, projects, getProject } = useProjectStore()
    const { currentTenant } = useTenantStore()
    const { user, logout } = useAuthStore()
    const navigate = useNavigate()
    const location = useLocation()
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

    // Sync project data
    useEffect(() => {
        if (projectId && (!currentProject || currentProject.id !== projectId)) {
            const project = projects.find((p) => p.id === projectId)
            if (project) {
                setCurrentProject(project)
            } else if (currentTenant) {
                getProject(currentTenant.id, projectId).then(p => {
                    setCurrentProject(p)
                }).catch(console.error)
            }
        }
    }, [projectId, currentProject, projects, currentTenant, setCurrentProject, getProject])

    // Determine active top tab based on current path
    const getActiveTab = () => {
        const pathSegments = location.pathname.split('/')
        const lastSegment = pathSegments[pathSegments.length - 1]
        if (lastSegment === 'logs') return 'logs'
        if (lastSegment === 'patterns') return 'patterns'
        return 'dashboard'
    }

    const activeTab = getActiveTab()

    const handleTabClick = (tab: { id: string; path: string }) => {
        if (projectId) {
            const basePath = `/project/${projectId}/agent`
            navigate(tab.path ? `${basePath}/${tab.path}` : basePath)
        }
    }

    const handleLogout = () => {
        logout()
        navigate('/login')
    }

    const basePath = projectId ? `/project/${projectId}` : '/project'

    return (
        <div className="flex h-screen overflow-hidden bg-background-light dark:bg-background-dark">
            {/* Left Sidebar Navigation - using new component */}
            <AgentSidebar
                projectId={projectId}
                conversationId={conversationId}
                collapsed={sidebarCollapsed}
                onCollapseToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
            />

            {/* Main Workspace Area */}
            <main className="flex-1 flex flex-col relative overflow-hidden">
                {/* Top Navigation Bar */}
                <header className="h-16 flex items-center justify-between px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark shrink-0">
                    <div className="flex items-center gap-4">
                        {/* Breadcrumbs */}
                        <nav className="flex items-center gap-2 text-sm">
                            <Link
                                to={`/project/${projectId}`}
                                className="text-slate-400 hover:text-primary transition-colors"
                            >
                                <span className="material-symbols-outlined text-[18px]">home</span>
                            </Link>
                            <span className="material-symbols-outlined text-slate-300 dark:text-slate-600 text-[16px]">
                                chevron_right
                            </span>
                            <Link
                                to={`/project/${projectId}`}
                                className="text-slate-500 hover:text-primary transition-colors font-medium"
                            >
                                {currentProject?.name || 'Project'}
                            </Link>
                            <span className="material-symbols-outlined text-slate-300 dark:text-slate-600 text-[16px]">
                                chevron_right
                            </span>
                            <span className="text-slate-900 dark:text-white font-bold">Agent</span>
                        </nav>

                        {/* Agent Status Badge */}
                        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-800 rounded-full">
                            <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse"></div>
                            <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-tight">
                                Agent Online
                            </span>
                        </div>

                        {/* View Tabs */}
                        <nav className="flex items-center gap-1 ml-4 bg-slate-100 dark:bg-slate-800/50 rounded-lg p-1">
                            {TOP_TABS.map((tab) => (
                                <button
                                    key={tab.id}
                                    onClick={() => handleTabClick(tab)}
                                    className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all duration-200 ${
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
                            <input
                                id="conversation-search"
                                name="conversation-search"
                                className="w-56 bg-slate-100 dark:bg-surface-dark border border-transparent focus:border-primary/30 rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary/20 transition-all placeholder:text-text-muted text-slate-900 dark:text-white"
                                placeholder="Search conversations..."
                                type="text"
                            />
                        </div>

                        {/* Quick Actions */}
                        <div className="flex items-center gap-1">
                            <Tooltip title="View execution history">
                                <button
                                    className="p-2 bg-slate-100 dark:bg-slate-800 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors text-slate-600 dark:text-slate-400"
                                    onClick={() => handleTabClick(TOP_TABS[1])}
                                >
                                    <History className="w-5 h-5" />
                                </button>
                            </Tooltip>
                            <Tooltip title="View workflow patterns">
                                <button
                                    className="p-2 bg-slate-100 dark:bg-slate-800 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors text-slate-600 dark:text-slate-400"
                                    onClick={() => handleTabClick(TOP_TABS[2])}
                                >
                                    <GitBranch className="w-5 h-5" />
                                </button>
                            </Tooltip>
                        </div>
                    </div>
                </header>

                {/* Page Content */}
                <div className="flex-1 overflow-hidden">
                    <RouteErrorBoundary context="Agent" fallbackPath={`/project/${projectId}/agent`}>
                        <Outlet />
                    </RouteErrorBoundary>
                </div>
            </main>
        </div>
    )
}

export default AgentLayout
