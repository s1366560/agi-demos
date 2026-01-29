/**
 * ProjectLayout - Layout for project-level pages
 *
 * Design Reference: design-prototype/project_workbench_-_overview/
 *
 * Layout Structure:
 * - Left sidebar: Brand, project navigation with groups (256px / 80px collapsed)
 * - Main area: Header with breadcrumbs/search, scrollable content
 *
 * Features:
 * - Collapsible sidebar with navigation groups
 * - Quick action button (New Memory)
 * - Workspace switcher
 * - Theme/language toggle
 */

import React, { useEffect, useState } from "react"
import { Outlet, useParams, useNavigate, useLocation } from "react-router-dom"
import { Plus } from "lucide-react"
import { ProjectSidebar } from "@/components/layout/ProjectSidebar"
import { AppHeader } from "@/components/layout/AppHeader"
import { RouteErrorBoundary } from "@/components/common/RouteErrorBoundary"
import { useProjectStore } from "@/stores/project"
import { useTenantStore } from "@/stores/tenant"
import { useAuthStore } from "@/stores/auth"

/**
 * ProjectLayout component
 */
export const ProjectLayout: React.FC = () => {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const { currentProject, setCurrentProject, getProject } = useProjectStore()
  const { currentTenant, setCurrentTenant } = useTenantStore()
  const { user, logout } = useAuthStore()

  // Sync project and tenant data
  useEffect(() => {
    if (projectId && (!currentProject || currentProject.id !== projectId)) {
      if (currentTenant) {
        getProject(currentTenant.id, projectId)
          .then((project) => {
            setCurrentProject(project)
          })
          .catch(console.error)
      } else {
        const { tenants, listTenants } = useTenantStore.getState()
        if (tenants.length === 0) {
          listTenants().then(() => {
            const tenants = useTenantStore.getState().tenants
            if (tenants.length > 0) {
              const firstTenant = tenants[0]
              setCurrentTenant(firstTenant)
              getProject(firstTenant.id, projectId!)
                .then((p) => setCurrentProject(p))
                .catch(console.error)
            }
          })
        } else {
          const firstTenant = tenants[0]
          setCurrentTenant(firstTenant)
          getProject(firstTenant.id, projectId!)
            .then((p) => setCurrentProject(p))
            .catch(console.error)
        }
      }
    }
  }, [
    projectId,
    currentProject,
    currentTenant,
    getProject,
    setCurrentProject,
    setCurrentTenant,
  ])

  const basePath = projectId ? `/project/${projectId}` : '/project'

  const handleLogout = () => {
    logout()
    navigate("/login")
  }

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background-light dark:bg-background-dark">
      {/* Sidebar Navigation - using new component */}
      <ProjectSidebar projectId={projectId} />

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 bg-background-light dark:bg-background-dark">
        {/* Header Bar - using new component */}
        <AppHeader
          context="project"
          basePath={basePath}
          showMobileMenu={false}
          showSearch={true}
          showNotifications={true}
          showThemeToggle={true}
          showLanguageSwitcher={true}
          showWorkspaceSwitcher={true}
          workspaceMode="project"
          primaryAction={{
            label: "nav.newMemory",
            to: `${basePath}/memories/new`,
            icon: <Plus className="w-4 h-4" />,
          }}
        />

        {/* Scrollable Page Content */}
        <div
          className={`flex-1 relative ${
            location.pathname.includes("/schema") ||
            location.pathname.includes("/graph") ||
            location.pathname.includes("/advanced-search") ||
            location.pathname.includes("/agent")
              ? "overflow-hidden"
              : "overflow-y-auto p-6 lg:p-8"
          }`}
        >
          <div className="max-w-7xl mx-auto">
            <RouteErrorBoundary context="Project" fallbackPath={`/project/${projectId}`}>
              <Outlet />
            </RouteErrorBoundary>
          </div>
        </div>
      </main>
    </div>
  )
}
