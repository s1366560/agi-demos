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

import React, { useEffect, useState } from "react";
import {
  Link,
  Outlet,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Tooltip } from "antd";
import { WorkspaceSwitcher } from "../components/WorkspaceSwitcher";
import { ThemeToggle } from "../components/ThemeToggle";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { TenantCreateModal } from "../pages/tenant/TenantCreate";
import { useTenantStore } from "../stores/tenant";
import { useAuthStore } from "../stores/auth";
import { useProjectStore } from "../stores/project";
import {
  LogOut,
  ChevronLeft,
  ChevronRight,
  Bell,
  Search,
  Menu,
} from "lucide-react";

// Navigation item interface
interface NavItem {
  id: string;
  icon: string;
  label: string;
  path: string;
  badge?: number;
}

// Platform navigation items
const PLATFORM_NAV: NavItem[] = [
  { id: "overview", icon: "dashboard", label: "nav.overview", path: "" },
  { id: "projects", icon: "folder", label: "nav.projects", path: "/projects" },
  { id: "users", icon: "group", label: "nav.users", path: "/users" },
  {
    id: "analytics",
    icon: "monitoring",
    label: "nav.analytics",
    path: "/analytics",
  },
  { id: "tasks", icon: "task", label: "nav.tasks", path: "/tasks" },
  { id: "agents", icon: "support_agent", label: "nav.agents", path: "/agents" },
  {
    id: "subagents",
    icon: "smart_toy",
    label: "nav.subagents",
    path: "/subagents",
  },
  { id: "skills", icon: "psychology", label: "nav.skills", path: "/skills" },
  {
    id: "mcp-servers",
    icon: "cable",
    label: "nav.mcpServers",
    path: "/mcp-servers",
  },
  {
    id: "patterns",
    icon: "account_tree",
    label: "Workflow Patterns",
    path: "/patterns",
  },
  {
    id: "providers",
    icon: "model_training",
    label: "nav.providers",
    path: "/providers",
  },
];

// Administration navigation items
const ADMIN_NAV: NavItem[] = [
  {
    id: "billing",
    icon: "credit_card",
    label: "nav.billing",
    path: "/billing",
  },
  {
    id: "settings",
    icon: "settings",
    label: "nav.settings",
    path: "/settings",
  },
];

export const TenantLayout: React.FC = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const { tenantId, projectId } = useParams();
  const { currentTenant, setCurrentTenant, getTenant, listTenants } =
    useTenantStore();
  const { currentProject } = useProjectStore();
  const { logout, user } = useAuthStore();
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [noTenants, setNoTenants] = useState(false);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const handleCreateTenant = async () => {
    await listTenants();
    const tenants = useTenantStore.getState().tenants;
    if (tenants.length > 0) {
      setCurrentTenant(tenants[tenants.length - 1]);
      setNoTenants(false);
    }
  };

  // Sync tenant ID from URL with store
  useEffect(() => {
    if (tenantId && (!currentTenant || currentTenant.id !== tenantId)) {
      getTenant(tenantId);
    } else if (!tenantId && !currentTenant) {
      const tenants = useTenantStore.getState().tenants;
      if (tenants.length > 0) {
        setCurrentTenant(tenants[0]);
      } else {
        useTenantStore
          .getState()
          .listTenants()
          .then(() => {
            const tenants = useTenantStore.getState().tenants;
            if (tenants.length > 0) {
              setCurrentTenant(tenants[0]);
            } else {
              const defaultName = user?.name
                ? `${user.name}'s Workspace`
                : "My Workspace";
              useTenantStore
                .getState()
                .createTenant({
                  name: defaultName,
                  description: "Automatically created default workspace",
                })
                .then(() => {
                  const newTenants = useTenantStore.getState().tenants;
                  if (newTenants.length > 0) {
                    setCurrentTenant(newTenants[newTenants.length - 1]);
                  } else {
                    setNoTenants(true);
                  }
                })
                .catch((err) => {
                  console.error("Failed to auto-create tenant:", err);
                  setNoTenants(true);
                });
            }
          })
          .catch(() => {});
      }
    }
  }, [tenantId, currentTenant, getTenant, setCurrentTenant, user]);

  // Sync project ID from URL with store
  useEffect(() => {
    if (
      projectId &&
      currentTenant &&
      (!currentProject || currentProject.id !== projectId)
    ) {
      const { projects, setCurrentProject, getProject } =
        useProjectStore.getState();
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
    );
  }

  const getBreadcrumbs = () => {
    const paths = location.pathname.split("/").filter(Boolean);
    const breadcrumbs = [{ label: "Home", path: getLink("") }];

    if (paths.length > 2) {
      const section = paths[2];

      if (section === "project" && projectId && currentProject) {
        breadcrumbs.push({ label: "Projects", path: getLink("/projects") });
        breadcrumbs.push({
          label: currentProject.name,
          path: getLink(`/project/${projectId}`),
        });
        if (paths.length > 4) {
          const subSection = paths[4];
          breadcrumbs.push({
            label: subSection.charAt(0).toUpperCase() + subSection.slice(1),
            path: getLink(`/project/${projectId}/${subSection}`),
          });
        }
      } else {
        breadcrumbs.push({
          label: section.charAt(0).toUpperCase() + section.slice(1),
          path: getLink(`/${section}`),
        });
      }
    } else if (paths.length === 2) {
      breadcrumbs[0].label = "Overview";
    }

    return breadcrumbs;
  };

  const isActive = (path: string) => {
    const currentPath = location.pathname;
    const targetPath = tenantId
      ? `/tenant/${tenantId}${path}`
      : `/tenant${path}`;

    if (path === "") {
      return currentPath === (tenantId ? `/tenant/${tenantId}` : "/tenant");
    }

    return (
      currentPath === targetPath || currentPath.startsWith(`${targetPath}/`)
    );
  };

  const getLink = (path: string) => {
    return tenantId ? `/tenant/${tenantId}${path}` : `/tenant${path}`;
  };

  // Navigation item component
  const NavItem = ({ item }: { item: NavItem }) => {
    const active = isActive(item.path);
    const label = item.label.startsWith("nav.") ? t(item.label) : item.label;

    const content = (
      <Link
        to={getLink(item.path)}
        className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 group ${
          active
            ? "bg-primary/10 text-primary font-medium"
            : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white"
        } ${isSidebarCollapsed ? "justify-center" : ""}`}
      >
        <span
          className={`material-symbols-outlined text-[20px] ${
            active ? "icon-filled" : ""
          }`}
        >
          {item.icon}
        </span>
        {!isSidebarCollapsed && (
          <span className="text-sm whitespace-nowrap">{label}</span>
        )}
        {!isSidebarCollapsed && item.badge && (
          <span className="ml-auto bg-primary text-white text-xs px-1.5 py-0.5 rounded-full">
            {item.badge}
          </span>
        )}
      </Link>
    );

    if (isSidebarCollapsed) {
      return (
        <Tooltip title={label} placement="right">
          {content}
        </Tooltip>
      );
    }
    return content;
  };

  return (
    <>
      <div className="flex h-screen w-full overflow-hidden bg-background-light dark:bg-background-dark">
        {/* Side Navigation */}
        <aside
          className={`flex flex-col bg-surface-light dark:bg-surface-dark border-r border-slate-200 dark:border-border-dark flex-none z-20 transition-all duration-300 ease-in-out relative ${
            isSidebarCollapsed ? "w-20" : "w-64"
          }`}
        >
          {/* Brand Header */}
          <div className="h-16 flex items-center px-4 border-b border-slate-100 dark:border-slate-800/50">
            {!isSidebarCollapsed ? (
              <div className="flex items-center gap-3 px-2">
                <div className="bg-primary/10 p-2 rounded-lg">
                  <span className="material-symbols-outlined text-primary">
                    memory
                  </span>
                </div>
                <h1 className="text-slate-900 dark:text-white text-lg font-bold leading-none tracking-tight">
                  MemStack<span className="text-primary">.ai</span>
                </h1>
              </div>
            ) : (
              <div className="w-full flex justify-center">
                <div className="bg-primary/10 p-2 rounded-lg">
                  <span className="material-symbols-outlined text-primary">
                    memory
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Navigation */}
          <nav className="flex-1 overflow-y-auto custom-scrollbar px-3 py-4">
            {/* Platform Section */}
            {!isSidebarCollapsed && (
              <p className="px-3 text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
                {t("nav.platform")}
              </p>
            )}
            <div className="space-y-1">
              {PLATFORM_NAV.map((item) => (
                <NavItem key={item.id} item={item} />
              ))}
            </div>

            {/* Divider */}
            {!isSidebarCollapsed ? (
              <p className="px-3 text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2 mt-6">
                {t("nav.administration")}
              </p>
            ) : (
              <div className="my-4 mx-3 border-t border-slate-100 dark:border-slate-800"></div>
            )}

            {/* Admin Section */}
            <div className="space-y-1">
              {ADMIN_NAV.map((item) => (
                <NavItem key={item.id} item={item} />
              ))}
            </div>
          </nav>

          {/* User Profile */}
          <div className="p-3 border-t border-slate-100 dark:border-slate-800">
            <div
              className={`flex items-center gap-3 p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700/50 ${
                isSidebarCollapsed ? "justify-center" : ""
              } group`}
            >
              <div className="size-8 rounded-full bg-gradient-to-br from-primary to-primary-light flex items-center justify-center text-xs font-bold text-white shrink-0 shadow-sm">
                {user?.name?.[0]?.toUpperCase() || "U"}
              </div>
              {!isSidebarCollapsed && (
                <>
                  <div className="flex flex-col overflow-hidden min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-900 dark:text-white truncate">
                      {user?.name || "User"}
                    </p>
                    <p className="text-xs text-slate-500 truncate">
                      {user?.email || "user@example.com"}
                    </p>
                  </div>
                  <button
                    onClick={handleLogout}
                    className="p-1.5 text-slate-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md transition-colors opacity-0 group-hover:opacity-100"
                    title="Sign out"
                  >
                    <LogOut className="size-4" />
                  </button>
                </>
              )}
            </div>
          </div>

          {/* Collapse Toggle */}
          <button
            onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
            className="absolute top-20 -right-3 w-6 h-6 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-full flex items-center justify-center shadow-sm hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors z-30"
          >
            {isSidebarCollapsed ? (
              <ChevronRight className="w-4 h-4 text-slate-500" />
            ) : (
              <ChevronLeft className="w-4 h-4 text-slate-500" />
            )}
          </button>
        </aside>

        {/* Main Content */}
        <main className="flex flex-col flex-1 h-full overflow-hidden relative">
          {/* Top Header */}
          <header className="h-16 flex items-center justify-between px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex-none">
            {/* Left: Mobile menu + Breadcrumbs */}
            <div className="flex items-center gap-4">
              <button
                onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
                className="lg:hidden p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg"
              >
                <Menu className="w-5 h-5" />
              </button>

              <nav className="flex items-center text-sm">
                {getBreadcrumbs().map((crumb, index, array) => (
                  <React.Fragment key={crumb.path}>
                    {index > 0 && (
                      <span className="mx-2 text-slate-300 dark:text-slate-600">
                        /
                      </span>
                    )}
                    {index === array.length - 1 ? (
                      <span className="font-medium text-slate-900 dark:text-white">
                        {crumb.label}
                      </span>
                    ) : (
                      <Link
                        to={crumb.path}
                        className="text-slate-500 hover:text-primary transition-colors"
                      >
                        {crumb.label}
                      </Link>
                    )}
                  </React.Fragment>
                ))}
              </nav>
            </div>

            {/* Right: Actions */}
            <div className="flex items-center gap-4">
              {/* Search */}
              <div className="relative hidden md:block group">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-primary w-4 h-4 transition-colors" />
                <input
                  type="text"
                  placeholder={t("common.search") + "..."}
                  className="input-search w-64"
                />
              </div>

              <ThemeToggle />
              <LanguageSwitcher />

              {/* Notifications */}
              <button className="relative p-2 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors">
                <Bell className="w-5 h-5" />
                <span className="absolute top-2 right-2 size-2 bg-red-500 rounded-full border-2 border-white dark:border-surface-dark"></span>
              </button>

              <div className="h-6 w-px bg-slate-200 dark:bg-slate-700"></div>

              {/* Workspace Switcher */}
              <div className="w-56">
                <WorkspaceSwitcher mode="tenant" />
              </div>
            </div>
          </header>

          {/* Page Content */}
          <div className="flex-1 overflow-y-auto p-6 lg:p-8">
            <div className="max-w-7xl mx-auto">
              <Outlet />
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
  );
};
