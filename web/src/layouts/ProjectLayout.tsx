/**
 * ProjectLayout - Layout for project-level pages
 *
 * Design Reference: design-prototype/project_workbench_-_overview/
 *
 * Layout Structure:
 * - Left sidebar: Project navigation
 * - Main area: Header with breadcrumbs/search, scrollable content
 *
 * Features:
 * - Project navigation sidebar
 * - Quick action button (New Memory)
 * - Workspace switcher
 * - Theme/language toggle
 */

import React, { useEffect } from "react"

import { Outlet, useParams } from "react-router-dom"

import { Plus } from "lucide-react"

import { useProjectStore } from "@/stores/project"
import { useTenantStore } from "@/stores/tenant"

import { RouteErrorBoundary } from "@/components/common/RouteErrorBoundary"
import { AppHeader } from "@/components/layout/AppHeader"
import { ProjectSidebar } from "@/components/layout/AppSidebar"

/**
 * ProjectLayout component
 */
export const ProjectLayout: React.FC = () => {
  const { projectId } = useParams()
  const currentProject = useProjectStore((state) => state.currentProject)
  const setCurrentProject = useProjectStore((state) => state.setCurrentProject)
  const getProject = useProjectStore((state) => state.getProject)
  const currentTenant = useTenantStore((state) => state.currentTenant)
  const setCurrentTenant = useTenantStore((state) => state.setCurrentTenant)

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

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background-light dark:bg-background-dark">
      {/* Left Sidebar - Project Navigation */}
      <ProjectSidebar projectId={projectId} />

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 bg-background-light dark:bg-background-dark">
        {/* Header Bar */}
        <AppHeader context="project" basePath={basePath}>
          <AppHeader.Search />
          <AppHeader.Tools>
            <AppHeader.ThemeToggle />
            <AppHeader.LanguageSwitcher />
          </AppHeader.Tools>
          <AppHeader.Notifications />
          <AppHeader.WorkspaceSwitcher mode="project" />
          <AppHeader.PrimaryAction
            label="nav.newMemory"
            to={`${basePath}/memories/new`}
            icon={<Plus className="w-4 h-4" />}
          />
          <AppHeader.UserMenu />
        </AppHeader>

        {/* Scrollable Page Content */}
        <div className="flex-1 overflow-y-auto p-6 lg:p-8">
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

export default ProjectLayout
