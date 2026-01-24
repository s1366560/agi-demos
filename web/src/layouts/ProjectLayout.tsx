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

import React, { useEffect, useState } from "react";
import {
  Link,
  Outlet,
  useLocation,
  useParams,
  useNavigate,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Tooltip } from "antd";
import { WorkspaceSwitcher } from "../components/WorkspaceSwitcher";
import { ThemeToggle } from "../components/ThemeToggle";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { useProjectStore } from "../stores/project";
import { useTenantStore } from "../stores/tenant";
import { useAuthStore } from "../stores/auth";
import {
  LogOut,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Bell,
  Search,
  Menu,
  Plus,
} from "lucide-react";

// Navigation item interface
interface NavItem {
  id: string;
  icon: string;
  label: string;
  path: string;
  exact?: boolean;
}

// Navigation groups
const NAV_GROUPS = {
  main: [
    {
      id: "overview",
      icon: "dashboard",
      label: "nav.overview",
      path: "",
      exact: true,
    },
    { id: "agent", icon: "smart_toy", label: "Agent V3", path: "/agent" },
    { id: "agent-v2", icon: "psychology", label: "Agent V2", path: "/agent-v2" },
  ],
  knowledge: [
    {
      id: "memories",
      icon: "database",
      label: "nav.memories",
      path: "/memories",
    },
    {
      id: "entities",
      icon: "category",
      label: "nav.entities",
      path: "/entities",
    },
    {
      id: "communities",
      icon: "groups",
      label: "nav.communities",
      path: "/communities",
    },
    { id: "graph", icon: "hub", label: "nav.knowledgeGraph", path: "/graph" },
  ],
  discovery: [
    {
      id: "search",
      icon: "travel_explore",
      label: "nav.deepSearch",
      path: "/advanced-search",
    },
  ],
  config: [
    { id: "schema", icon: "code", label: "nav.schema", path: "/schema" },
    {
      id: "maintenance",
      icon: "build",
      label: "nav.maintenance",
      path: "/maintenance",
    },
    { id: "team", icon: "manage_accounts", label: "nav.team", path: "/team" },
    {
      id: "settings",
      icon: "settings",
      label: "nav.settings",
      path: "/settings",
    },
  ],
};

const BOTTOM_NAV: NavItem[] = [
  { id: "support", icon: "help", label: "nav.support", path: "/support" },
];

export const ProjectLayout: React.FC = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const { projectId } = useParams();
  const { currentProject, setCurrentProject, getProject } = useProjectStore();
  const { currentTenant, setCurrentTenant } = useTenantStore();
  const { user, logout } = useAuthStore();
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({
    knowledge: true,
    discovery: true,
    config: true,
  });

  const toggleGroup = (group: string) => {
    setOpenGroups((prev) => ({ ...prev, [group]: !prev[group] }));
  };

  // Sync project and tenant data
  useEffect(() => {
    if (projectId && (!currentProject || currentProject.id !== projectId)) {
      if (currentTenant) {
        getProject(currentTenant.id, projectId)
          .then((project) => {
            setCurrentProject(project);
          })
          .catch(console.error);
      } else {
        const { tenants, listTenants } = useTenantStore.getState();
        if (tenants.length === 0) {
          listTenants().then(() => {
            const tenants = useTenantStore.getState().tenants;
            if (tenants.length > 0) {
              const firstTenant = tenants[0];
              setCurrentTenant(firstTenant);
              getProject(firstTenant.id, projectId!)
                .then((p) => setCurrentProject(p))
                .catch(console.error);
            }
          });
        } else {
          const firstTenant = tenants[0];
          setCurrentTenant(firstTenant);
          getProject(firstTenant.id, projectId!)
            .then((p) => setCurrentProject(p))
            .catch(console.error);
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
  ]);

  const getBreadcrumbs = () => {
    const paths = location.pathname.split("/").filter(Boolean);
    const breadcrumbs = [
      { label: "Home", path: "/tenant" },
      { label: "Projects", path: "/tenant/projects" },
    ];

    if (currentProject) {
      breadcrumbs.push({
        label: currentProject.name,
        path: `/project/${currentProject.id}`,
      });
    } else {
      breadcrumbs.push({ label: "Project", path: `/project/${projectId}` });
    }

    if (paths.length > 2) {
      const section = paths[2];
      breadcrumbs.push({
        label: section.charAt(0).toUpperCase() + section.slice(1),
        path: location.pathname,
      });
    }

    return breadcrumbs;
  };

  const isActive = (path: string, exact?: boolean) => {
    const currentPath = location.pathname;

    if (exact || path === "") {
      return (
        currentPath === `/project/${projectId}` ||
        currentPath === `/project/${projectId}/`
      );
    }

    return currentPath.includes(`/project/${projectId}${path}`);
  };

  const getLink = (path: string) => `/project/${projectId}${path}`;

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  // Navigation item component
  const NavItem = ({ item }: { item: NavItem }) => {
    const active = isActive(item.path, item.exact);
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
        {active && !isSidebarCollapsed && (
          <div className="absolute right-3 w-1.5 h-1.5 rounded-full bg-primary"></div>
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

  // Navigation group component
  const NavGroup = ({
    title,
    items,
    groupKey,
  }: {
    title: string;
    items: NavItem[];
    groupKey: string;
  }) => (
    <div className="space-y-1">
      {!isSidebarCollapsed && (
        <button
          onClick={() => toggleGroup(groupKey)}
          className="flex items-center justify-between w-full px-3 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
        >
          <span>{title}</span>
          <ChevronDown
            className={`w-3 h-3 transition-transform ${
              openGroups[groupKey] ? "" : "-rotate-90"
            }`}
          />
        </button>
      )}
      {(isSidebarCollapsed || openGroups[groupKey]) && (
        <div className="space-y-1">
          {items.map((item) => (
            <NavItem key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background-light dark:bg-background-dark">
      {/* Sidebar Navigation */}
      <aside
        className={`flex flex-col bg-surface-light dark:bg-surface-dark border-r border-slate-200 dark:border-border-dark transition-all duration-300 relative ${
          isSidebarCollapsed ? "w-20" : "w-64"
        }`}
      >
        {/* Brand Header */}
        <div className="h-16 flex items-center px-4 border-b border-slate-100 dark:border-slate-800/50">
          {!isSidebarCollapsed ? (
            <div className="flex items-center gap-3 px-2">
              <div className="bg-primary/10 p-2 rounded-lg border border-primary/20">
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
              <div className="bg-primary/10 p-2 rounded-lg border border-primary/20">
                <span className="material-symbols-outlined text-primary">
                  memory
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Navigation Menu */}
        <nav className="flex-1 overflow-y-auto custom-scrollbar py-4 px-3 space-y-4">
          {/* Main Navigation */}
          <div className="space-y-1">
            {NAV_GROUPS.main.map((item) => (
              <NavItem key={item.id} item={item} />
            ))}
          </div>

          {!isSidebarCollapsed && (
            <div className="h-px bg-slate-100 dark:bg-slate-800 mx-2"></div>
          )}
          {isSidebarCollapsed && (
            <div className="h-px bg-slate-100 dark:bg-slate-800 mx-1"></div>
          )}

          {/* Knowledge Base */}
          <NavGroup
            title={t("nav.knowledgeBase")}
            items={NAV_GROUPS.knowledge}
            groupKey="knowledge"
          />

          {/* Discovery */}
          <NavGroup
            title={t("nav.discovery")}
            items={NAV_GROUPS.discovery}
            groupKey="discovery"
          />

          {/* Configuration */}
          <NavGroup
            title={t("nav.configuration")}
            items={NAV_GROUPS.config}
            groupKey="config"
          />
        </nav>

        {/* Bottom Section */}
        <div className="p-3 border-t border-slate-100 dark:border-slate-800">
          {/* Bottom Nav Items */}
          {BOTTOM_NAV.map((item) => (
            <NavItem key={item.id} item={item} />
          ))}

          {/* User Profile */}
          <div
            className={`flex items-center gap-3 p-2 mt-2 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700/50 ${
              isSidebarCollapsed ? "justify-center" : ""
            } group`}
          >
            <div className="size-8 rounded-full bg-gradient-to-br from-primary to-primary-light flex items-center justify-center text-xs font-bold text-white shrink-0 shadow-sm">
              {user?.name?.[0]?.toUpperCase() || "U"}
            </div>
            {!isSidebarCollapsed && (
              <>
                <div className="flex flex-col overflow-hidden min-w-0 flex-1">
                  <span className="text-sm font-medium text-slate-700 dark:text-white truncate">
                    {user?.name || "User"}
                  </span>
                  <span className="text-xs text-slate-500 truncate">
                    {user?.email || "user@example.com"}
                  </span>
                </div>
                <button
                  onClick={handleLogout}
                  className="p-1.5 text-slate-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-md transition-colors opacity-0 group-hover:opacity-100"
                  title="Sign out"
                >
                  <LogOut className="w-4 h-4" />
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

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 bg-background-light dark:bg-background-dark">
        {/* Header Bar */}
        <header className="h-16 flex items-center justify-between px-6 border-b border-slate-200 dark:border-border-dark bg-surface-light dark:bg-surface-dark">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
              className="lg:hidden p-2 rounded-lg text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              <Menu className="w-5 h-5" />
            </button>

            {/* Breadcrumbs */}
            <nav className="flex items-center text-sm font-medium">
              {getBreadcrumbs().map((crumb, index, array) => (
                <React.Fragment key={crumb.path}>
                  {index > 0 && (
                    <ChevronRight className="w-4 h-4 mx-1 text-slate-300 dark:text-slate-600" />
                  )}
                  {index === array.length - 1 ? (
                    <span className="text-slate-900 dark:text-white font-semibold">
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

          {/* Actions */}
          <div className="flex items-center gap-4">
            {/* Search */}
            <div className="relative hidden md:block group">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-primary w-4 h-4 transition-colors" />
              <input
                type="text"
                className="w-64 h-9 pl-9 pr-4 text-sm bg-slate-100 dark:bg-slate-800 border border-transparent focus:border-primary/30 rounded-lg text-slate-900 dark:text-white placeholder-slate-500 focus:ring-2 focus:ring-primary/20 transition-all outline-none"
                placeholder={t("common.search") + "..."}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    navigate(getLink("/advanced-search"));
                  }
                }}
              />
            </div>

            <ThemeToggle />
            <LanguageSwitcher />

            {/* Notification Bell */}
            <button className="relative p-2 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-full transition-colors">
              <Bell className="w-5 h-5" />
              <span className="absolute top-2 right-2 h-2 w-2 rounded-full bg-red-500 ring-2 ring-white dark:ring-surface-dark"></span>
            </button>

            <div className="h-6 w-px bg-slate-200 dark:bg-slate-700"></div>

            {/* Primary Action */}
            <Link to={getLink("/memories/new")}>
              <button className="btn-primary">
                <Plus className="w-4 h-4" />
                <span>{t("nav.newMemory")}</span>
              </button>
            </Link>

            <div className="w-48">
              <WorkspaceSwitcher mode="project" />
            </div>
          </div>
        </header>

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
            <Outlet />
          </div>
        </div>
      </main>
    </div>
  );
};
