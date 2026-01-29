/**
 * TenantLayout - Main layout for tenant-level pages
 *
 * Design Reference: design-prototype/tenant_console_-_overview_1/
 *
 * Layout Structure:
 * - Left sidebar: Brand, navigation, user profile (256px / 80px collapsed)
 * - Main area: Header with breadcrumbs/search, scrollable content
 *
 * Features:
 * - Collapsible sidebar
 * - Responsive design
 * - Theme toggle
 * - Language switcher
 * - Workspace switcher
 */

import React, { useEffect, useState } from "react"
import { Outlet, useLocation, useNavigate, useParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { TenantSidebar } from "@/components/layout/TenantSidebar"
import { AppHeader } from "@/components/layout/AppHeader"
import { TenantCreateModal } from "@/pages/tenant/TenantCreate"
import { RouteErrorBoundary } from "@/components/common/RouteErrorBoundary"
import { useTenantStore } from "@/stores/tenant"
import { useAuthStore } from "@/stores/auth"
import { useProjectStore } from "@/stores/project"

// HTTP status codes for error handling
const HTTP_STATUS = {
  FORBIDDEN: 403,
  NOT_FOUND: 404,
} as const

/**
 * TenantLayout component
 */
export const TenantLayout: React.FC = () => {
  const { t } = useTranslation()
  const location = useLocation()
  const navigate = useNavigate()
  const { tenantId, projectId } = useParams()
  const { currentTenant, setCurrentTenant, getTenant, listTenants } = useTenantStore()
  const { currentProject } = useProjectStore()
  const { logout, user } = useAuthStore()
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const [noTenants, setNoTenants] = useState(false)

  const handleLogout = () => {
    logout()
    navigate("/login")
  }

  const handleCreateTenant = async () => {
    await listTenants()
    const tenants = useTenantStore.getState().tenants
    if (tenants.length > 0) {
      setCurrentTenant(tenants[tenants.length - 1])
      setNoTenants(false)
    }
  }

  /**
   * Handle 403/404 errors when accessing unauthorized tenant
   * Falls back to first accessible tenant
   */
  const handleTenantAccessError = async (error: unknown, requestedTenantId: string) => {
    const status = (error as any)?.response?.status

    if (status === HTTP_STATUS.FORBIDDEN || status === HTTP_STATUS.NOT_FOUND) {
      console.warn(`Access denied to tenant ${requestedTenantId}, falling back to accessible tenant`)

      try {
        await listTenants()
        const tenants = useTenantStore.getState().tenants

        if (tenants.length > 0) {
          const firstAccessibleTenant = tenants[0]
          setCurrentTenant(firstAccessibleTenant)
          navigate(`/tenant/${firstAccessibleTenant.id}`, { replace: true })
        } else {
          setNoTenants(true)
        }
      } catch (listError) {
        console.error("Failed to list accessible tenants:", listError)
        setNoTenants(true)
      }
    }
  }

  // Sync tenant ID from URL with store
  useEffect(() => {
    if (tenantId && (!currentTenant || currentTenant.id !== tenantId)) {
      getTenant(tenantId).catch((error) => {
        handleTenantAccessError(error, tenantId)
      })
    } else if (!tenantId && !currentTenant) {
      const tenants = useTenantStore.getState().tenants
      if (tenants.length > 0) {
        setCurrentTenant(tenants[0])
      } else {
        useTenantStore
          .getState()
          .listTenants()
          .then(() => {
            const tenants = useTenantStore.getState().tenants
            if (tenants.length > 0) {
              setCurrentTenant(tenants[0])
            } else {
              const defaultName = user?.name
                ? `${user.name}'s Workspace`
                : "My Workspace"
              useTenantStore
                .getState()
                .createTenant({
                  name: defaultName,
                  description: "Automatically created default workspace",
                })
                .then(() => {
                  const newTenants = useTenantStore.getState().tenants
                  if (newTenants.length > 0) {
                    setCurrentTenant(newTenants[newTenants.length - 1])
                  } else {
                    setNoTenants(true)
                  }
                })
                .catch((err) => {
                  console.error("Failed to auto-create tenant:", err)
                  setNoTenants(true)
                })
            }
          })
          .catch(() => {})
      }
    }
  }, [tenantId, currentTenant, getTenant, setCurrentTenant, user, navigate])

  // Sync project ID from URL with store
  useEffect(() => {
    if (
      projectId &&
      currentTenant &&
      (!currentProject || currentProject.id !== projectId)
    ) {
      const { projects, setCurrentProject, getProject } =
        useProjectStore.getState()
      const project = projects.find((p) => p.id === projectId)
      if (project) {
        setCurrentProject(project)
      } else {
        getProject(currentTenant.id, projectId)
          .then((p) => {
            setCurrentProject(p)
          })
          .catch(console.error)
      }
    } else if (!projectId && currentProject) {
      useProjectStore.getState().setCurrentProject(null)
    }
  }, [projectId, currentTenant, currentProject])

  // No tenants state - welcome screen
  if (noTenants) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-background-light dark:bg-background-dark">
        <div className="mx-auto flex w-full max-w-md flex-col items-center space-y-6 p-6 text-center">
          <div className="flex items-center gap-3">
            <div className="bg-primary/10 p-3 rounded-xl">
              <span className="material-symbols-outlined text-primary text-4xl">
                memory
              </span>
            </div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
              MemStack<span className="text-primary">.ai</span>
            </h1>
          </div>

          <div className="space-y-2">
            <h2 className="text-xl font-semibold text-slate-900 dark:text-white">
              {t("tenant.welcome")}
            </h2>
            <p className="text-slate-500 dark:text-slate-400">
              {t("tenant.noTenantDescription")}
            </p>
          </div>

          <div className="flex flex-col gap-4 w-full">
            <button
              onClick={() => setIsCreateModalOpen(true)}
              className="btn-primary w-full py-3"
            >
              {t("tenant.create")}
            </button>
            <button
              onClick={handleLogout}
              className="btn-secondary w-full py-3"
            >
              {t("common.logout")}
            </button>
          </div>
        </div>

        <TenantCreateModal
          isOpen={isCreateModalOpen}
          onClose={() => setIsCreateModalOpen(false)}
          onSuccess={handleCreateTenant}
        />
      </div>
    )
  }

  const basePath = tenantId ? `/tenant/${tenantId}` : '/tenant'

  return (
    <>
      <div className="flex h-screen w-full overflow-hidden bg-background-light dark:bg-background-dark">
        {/* Sidebar - using new component */}
        <TenantSidebar tenantId={tenantId} />

        {/* Main Content */}
        <main className="flex flex-col flex-1 h-full overflow-hidden relative">
          {/* Header - using new component */}
          <AppHeader
            context="tenant"
            basePath={basePath}
            showMobileMenu={false}
            showSearch={true}
            showNotifications={true}
            showThemeToggle={true}
            showLanguageSwitcher={true}
            showWorkspaceSwitcher={true}
            workspaceMode="tenant"
          />

          {/* Page Content */}
          <div className="flex-1 overflow-y-auto p-6 lg:p-8">
            <div className="max-w-7xl mx-auto">
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
    </>
  )
}
