/**
 * TenantHeader - Clean single-row navigation header for tenant pages
 *
 * 3-zone layout:
 *   Left:   Sidebar toggle + brand
 *   Center: Primary navigation tabs + overflow "More" menu
 *   Right:  Search + Notifications + User menu
 */

/* eslint-disable react-refresh/only-export-components */

import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';

import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { NavLink, Link, useNavigate, useLocation } from 'react-router-dom';

import {
  PanelLeft,
  PanelRight,
  Menu,
  Search,
  Check,
  ChevronDown,
  MoreHorizontal,
  User,
  Settings,
  CreditCard,
  LogOut,
  Sun,
  Moon,
  Monitor,
  Languages,
  Activity,
} from 'lucide-react';

import { useAuthActions, useUser } from '@/stores/auth';
import { useBackgroundStore, useRunningCount } from '@/stores/backgroundStore';
import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';
import { useThemeStore } from '@/stores/theme';
import { useCurrentWorkspace, useWorkspaces } from '@/stores/workspace';

import { authAPI } from '@/services/api';

import { deriveTopNavigationItems } from '@/config/navigation';

import { NotificationDropdown } from './AppHeader/NotificationDropdown';

import type { Tenant } from '@/types/memory';

interface TenantHeaderProps {
  tenantId: string;
  sidebarCollapsed: boolean;
  onSidebarToggle: () => void;
  onMobileMenuOpen: () => void;
  projectId?: string | undefined;
}

interface NavItem {
  id: string;
  label: string;
  path: string;
  exact?: boolean | undefined;
}

const MAX_VISIBLE_NAV_ITEMS = 8;

const TENANT_NAV_FALLBACK_LABELS: Record<string, string> = {
  'agent-workspace': 'Agent Workspace',
  'agent-configuration': 'Agent Configuration',
  'audit-logs': 'Audit Logs',
  'dead-letter-queue': 'Dead Letter Queue',
  evolution: 'Evolution',
  overview: 'Overview',
  plugins: 'Plugins',
  projects: 'Projects',
  providers: 'Model Services',
  skills: 'Skills',
  subagents: 'Agents',
  tasks: 'Tasks',
  users: 'Users',
  workspaces: 'Workspaces',
};

const PROJECT_NAV_FALLBACK_LABELS: Record<string, string> = {
  blackboard: 'Blackboard',
  channels: 'Channels',
  communities: 'Communities',
  'cron-jobs': 'Cron Jobs',
  entities: 'Entities',
  graph: 'Knowledge Graph',
  maintenance: 'Maintenance',
  memories: 'Memories',
  overview: 'Overview',
  schema: 'Schema',
  search: 'Deep Search',
  settings: 'Settings',
  team: 'Team',
  workspaces: 'Workspaces',
};

interface ContextualNavOptions {
  basePath: string;
  projectBasePath: string | null;
  preferredWorkspaceId: string | null;
  t: (key: string, fallback?: string) => string;
  tenantId?: string | undefined;
  projectId?: string | undefined;
}

function stripSearch(path: string): string {
  return path.split('?')[0] || path;
}

function getThemePresentation(
  theme: 'light' | 'dark' | 'system',
  t: (key: string, fallback: string) => string
): { icon: React.ReactNode; label: string } {
  switch (theme) {
    case 'dark':
      return {
        icon: <Moon size={16} />,
        label: t('theme.dark', 'Dark'),
      };
    case 'light':
      return {
        icon: <Sun size={16} />,
        label: t('theme.light', 'Light'),
      };
    default:
      return {
        icon: <Monitor size={16} />,
        label: t('theme.system', 'System'),
      };
  }
}

export function getContextualTopNavItems({
  basePath,
  projectBasePath,
  preferredWorkspaceId,
  t,
  tenantId,
  projectId,
}: ContextualNavOptions): NavItem[] {
  const currentContext = projectBasePath ? 'project' : 'tenant';
  const fallbackLabels =
    currentContext === 'project' ? PROJECT_NAV_FALLBACK_LABELS : TENANT_NAV_FALLBACK_LABELS;

  return deriveTopNavigationItems(currentContext, {
    tenantId,
    projectId,
    preferredWorkspaceId,
  }).map((item) => ({
    id: item.id,
    label: t(item.label, fallbackLabels[item.id] ?? item.label),
    path: item.path || (projectBasePath ?? basePath),
    exact: item.exact,
  }));
}

export function isContextualTopNavItemActive(pathname: string, item: NavItem): boolean {
  const matchPath = stripSearch(item.path);

  if (item.exact) {
    return pathname === matchPath || pathname === `${matchPath}/`;
  }

  return pathname === matchPath || pathname.startsWith(`${matchPath}/`);
}

const TenantHeader: React.FC<TenantHeaderProps> = ({
  tenantId,
  sidebarCollapsed,
  onSidebarToggle,
  onMobileMenuOpen,
  projectId,
}) => {
  const { t } = useTranslation();
  const location = useLocation();
  const normalizedTenantId = tenantId.trim();
  const basePath = normalizedTenantId ? `/tenant/${normalizedTenantId}` : '/tenant';

  const currentProject = useProjectStore((state) => state.currentProject);
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const currentWorkspace = useCurrentWorkspace();
  const workspaces = useWorkspaces();
  const isProjectScopedPath = location.pathname.includes('/project/');
  const tenantCurrentProject =
    currentProject?.tenant_id === normalizedTenantId ? currentProject : null;
  const effectiveProjectId =
    projectId ?? (isProjectScopedPath ? tenantCurrentProject?.id : undefined);
  const projectBasePath = effectiveProjectId ? `${basePath}/project/${effectiveProjectId}` : null;
  const tenantProjectWorkspaces = useMemo(
    () =>
      workspaces.filter(
        (workspace) =>
          workspace.tenant_id === normalizedTenantId &&
          (!effectiveProjectId || workspace.project_id === effectiveProjectId)
      ),
    [effectiveProjectId, normalizedTenantId, workspaces]
  );
  const tenantCurrentWorkspace =
    currentWorkspace?.tenant_id === normalizedTenantId &&
    (!effectiveProjectId || currentWorkspace.project_id === effectiveProjectId)
      ? currentWorkspace
      : null;
  const preferredWorkspaceId = tenantCurrentWorkspace?.id ?? tenantProjectWorkspaces[0]?.id ?? null;
  const contextualNavItems = useMemo(
    () =>
      getContextualTopNavItems({
        basePath,
        projectBasePath,
        preferredWorkspaceId,
        t: (key, fallback) => (fallback ? t(key, fallback) : t(key)),
        tenantId: normalizedTenantId || undefined,
        projectId: effectiveProjectId,
      }),
    [basePath, effectiveProjectId, normalizedTenantId, preferredWorkspaceId, projectBasePath, t]
  );
  const visibleNav = contextualNavItems.slice(0, MAX_VISIBLE_NAV_ITEMS);
  const overflowNav = contextualNavItems.slice(MAX_VISIBLE_NAV_ITEMS);
  const searchPath = projectBasePath
    ? `${projectBasePath}/advanced-search`
    : `${basePath}/projects`;

  return (
    <>
      <header className="h-14 px-3 sm:px-4 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex items-center flex-none shrink-0">
        <div className="h-full w-full flex items-center gap-1 sm:gap-3">
          {/* Left: Mobile menu + Sidebar toggle + Brand */}
          <div className="flex items-center gap-1 flex-shrink-0">
            <button
              type="button"
              onClick={onMobileMenuOpen}
              className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 md:hidden"
              aria-label={t('components.layout.header.mobileMenu', 'Menu')}
            >
              <Menu size={18} className="text-slate-500" />
            </button>
            <button
              type="button"
              onClick={onSidebarToggle}
              className="hidden md:flex p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 text-slate-500"
              aria-label={
                sidebarCollapsed
                  ? t('components.layout.header.expandSidebar', 'Expand sidebar')
                  : t('components.layout.header.collapseSidebar', 'Collapse sidebar')
              }
            >
              {sidebarCollapsed ? <PanelRight size={18} /> : <PanelLeft size={18} />}
            </button>
            <Link
              to={basePath}
              className="text-sm font-semibold text-slate-800 dark:text-slate-200 hover:text-primary transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 hidden sm:block ml-1"
            >
              MemStack
            </Link>
          </div>

          {/* Center: Nav tabs */}
          <nav className="hidden xl:flex items-center gap-0.5 flex-1 min-w-0 ml-4 mr-2 overflow-hidden">
            {visibleNav.map((item) => (
              <NavLink
                key={item.id}
                to={item.path}
                className={() =>
                  `flex shrink-0 items-center gap-1.5 px-2 2xl:px-3 py-1.5 rounded-lg text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 whitespace-nowrap ${
                    isContextualTopNavItemActive(location.pathname, item)
                      ? 'bg-primary/10 text-primary'
                      : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-200'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
            {overflowNav.length > 0 && <OverflowMenu items={overflowNav} />}
          </nav>

          <nav
            className="hidden md:flex xl:hidden items-center flex-1 min-w-0 ml-2 mr-2 overflow-hidden"
            aria-label={t('nav.navigation', 'Navigation')}
          >
            <OverflowMenu
              items={contextualNavItems}
              label={t('nav.navigation', 'Navigation')}
              icon={<Menu size={16} />}
            />
          </nav>

          {/* Right: Actions */}
          <div className="flex items-center gap-1 sm:gap-2 ml-auto flex-none">
            <SearchButton searchPath={searchPath} />
            <BackgroundTasksButton />
            <NotificationDropdown />
            <HeaderUserMenu tenantId={tenantId} currentTenant={currentTenant} />
          </div>
        </div>
      </header>
    </>
  );
};

/**
 * Overflow "More" dropdown for secondary nav items
 */
function OverflowMenu({
  items,
  label,
  icon,
}: {
  items: NavItem[];
  label?: string | undefined;
  icon?: React.ReactNode;
}) {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState<{ left: number; top: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const updateMenuPosition = useCallback(() => {
    const trigger = ref.current;
    if (!trigger) return;

    const rect = trigger.getBoundingClientRect();
    const menuWidth = 192;
    const viewportPadding = 8;
    const maxLeft = window.innerWidth - menuWidth - viewportPadding;

    setMenuPosition({
      left: Math.max(viewportPadding, Math.min(rect.left, maxLeft)),
      top: rect.bottom + 4,
    });
  }, []);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      const insideTrigger = ref.current?.contains(target) ?? false;
      const insideMenu = menuRef.current?.contains(target) ?? false;

      if (!insideTrigger && !insideMenu) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  useEffect(() => {
    if (!open) return;

    updateMenuPosition();
    window.addEventListener('resize', updateMenuPosition);
    window.addEventListener('scroll', updateMenuPosition, true);

    return () => {
      window.removeEventListener('resize', updateMenuPosition);
      window.removeEventListener('scroll', updateMenuPosition, true);
    };
  }, [open, updateMenuPosition]);

  const isAnyActive = items.some((item) => isContextualTopNavItemActive(location.pathname, item));
  const buttonLabel = label ?? t('nav.more', 'More');
  const buttonIcon = icon ?? <MoreHorizontal size={16} />;
  const menu =
    open && menuPosition
      ? createPortal(
          <div
            ref={menuRef}
            className="fixed w-48 bg-white dark:bg-surface-dark rounded-xl shadow-lg border border-slate-200 dark:border-slate-700 py-1 z-50"
            style={{ left: menuPosition.left, top: menuPosition.top }}
          >
            {items.map((item) => {
              const isActive = isContextualTopNavItemActive(location.pathname, item);
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    void navigate(item.path);
                    setOpen(false);
                  }}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset ${
                    isActive
                      ? 'text-primary bg-primary/5'
                      : 'text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800'
                  }`}
                >
                  {item.label}
                </button>
              );
            })}
          </div>,
          document.body
        )
      : null;

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        type="button"
        onClick={() => {
          updateMenuPosition();
          setOpen((currentOpen) => !currentOpen);
        }}
        className={`flex items-center gap-1 px-2 py-1.5 rounded-lg text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 ${
          isAnyActive
            ? 'bg-primary/10 text-primary'
            : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
        }`}
      >
        {buttonIcon}
        <span className="hidden lg:inline">{buttonLabel}</span>
      </button>
      {menu}
    </div>
  );
}

/**
 * Background SubAgent tasks indicator
 */
function BackgroundTasksButton() {
  const { t } = useTranslation();
  const runningCount = useRunningCount();
  const togglePanel = useBackgroundStore((s) => s.togglePanel);

  return (
    <button
      type="button"
      onClick={togglePanel}
      className="relative p-1.5 sm:p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
      aria-label={t('components.layout.header.backgroundTasks', 'Background tasks')}
    >
      <Activity size={18} />
      {runningCount > 0 && (
        <span className="absolute -top-0.5 -right-0.5 min-w-4 h-4 px-1 bg-primary text-white text-2xs font-bold rounded-full flex items-center justify-center">
          {runningCount}
        </span>
      )}
    </button>
  );
}

/**
 * Compact search button
 */
function SearchButton({ searchPath }: { searchPath: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <button
      type="button"
      onClick={() => {
        void navigate(searchPath);
      }}
      className="p-1.5 sm:p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
      aria-label={t('common.search', 'Search')}
    >
      <Search size={18} />
    </button>
  );
}

/**
 * Enhanced user menu with theme, language, settings, billing
 */
function HeaderUserMenu({
  tenantId,
  currentTenant,
}: {
  tenantId: string;
  currentTenant: Tenant | null;
}) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const user = useUser();
  const { logout, setUser } = useAuthActions();
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);
  const tenants = useTenantStore((state) => state.tenants);
  const listTenants = useTenantStore((state) => state.listTenants);
  const setCurrentTenant = useTenantStore((state) => state.setCurrentTenant);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const normalizedTheme = theme as 'light' | 'dark' | 'system';
  const availableTenants = tenants.length > 0 ? tenants : currentTenant ? [currentTenant] : [];

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  useEffect(() => {
    if (open && tenants.length === 0) {
      void listTenants().catch(() => undefined);
    }
  }, [listTenants, open, tenants.length]);

  if (!user) return null;

  const displayName = user.name || (user.email.split('@')[0] ?? '');
  const initials = displayName
    .split(' ')
    .map((n: string) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
  const avatarUrl = user.profile?.avatar_url;
  const normalizedTenantId = tenantId.trim();
  const basePath = normalizedTenantId ? `/tenant/${normalizedTenantId}` : '/tenant';

  const handleLogout = () => {
    logout();
    void navigate('/login');
  };

  const handleTenantSelect = (tenant: Tenant) => {
    setCurrentTenant(tenant);
    setOpen(false);
    void navigate(`/tenant/${tenant.id}`);
  };

  const cycleTheme = () => {
    const themes: Array<'light' | 'dark' | 'system'> = ['light', 'dark', 'system'];
    const idx = themes.indexOf(normalizedTheme);
    setTheme(themes[(idx + 1) % themes.length] ?? 'light');
  };

  // Prefer the resolved tag (i18next normalizes `zh` → `zh-CN` when
  // `nonExplicitSupportedLngs` is set); fall back to the raw value.
  const activeLanguage = i18n.resolvedLanguage || i18n.language || 'en-US';
  const isZh = activeLanguage.toLowerCase().startsWith('zh');

  const toggleLanguage = () => {
    const next = isZh ? 'en-US' : 'zh-CN';
    void i18n.changeLanguage(next);
    authAPI
      .updatePreferredLanguage(next)
      .then((updated) => {
        setUser(updated);
      })
      .catch(() => {
        /* swallow: local i18n already updated */
      });
  };

  const { icon: themeIcon, label: themeLabel } = getThemePresentation(normalizedTheme, t);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => {
          setOpen(!open);
        }}
        className="flex items-center gap-1.5 p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
        aria-label={t('components.layout.header.userMenu', 'User menu')}
      >
        <div className="flex h-7 w-7 items-center justify-center overflow-hidden rounded-full bg-slate-900 text-xs font-medium text-slate-50 dark:bg-slate-100 dark:text-slate-900">
          {avatarUrl ? (
            <img src={avatarUrl} alt={displayName} className="w-full h-full object-cover" />
          ) : (
            initials
          )}
        </div>
        <ChevronDown
          size={14}
          className={`hidden sm:block text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-60 bg-white dark:bg-surface-dark rounded-xl shadow-lg border border-slate-200 dark:border-slate-700 py-1 z-50">
          {/* User info */}
          <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700">
            <p className="text-sm font-medium text-slate-900 dark:text-white truncate">
              {displayName}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 truncate">{user.email}</p>
            {currentTenant && (
              <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-1">
                {currentTenant.name}
              </p>
            )}
          </div>

          {/* Quick actions */}
          <div className="py-1">
            <button
              type="button"
              onClick={cycleTheme}
              aria-label={t('user.themeCycleAria', 'Switch theme. Current theme: {{theme}}', {
                theme: themeLabel,
              })}
              className="w-full flex items-center justify-between px-4 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
            >
              <span className="flex items-center gap-2.5">
                <span className="text-slate-400">{themeIcon}</span>
                {t('user.theme', 'Theme')}
              </span>
              <span className="text-xs text-slate-400">{themeLabel}</span>
            </button>
            <button
              type="button"
              onClick={toggleLanguage}
              className="w-full flex items-center justify-between px-4 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
            >
              <span className="flex items-center gap-2.5">
                <Languages size={16} className="text-slate-400" />
                {t('user.language', 'Language')}
              </span>
              <span className="text-xs text-slate-400">
                {/* i18n-ignore-next: native script convention for language indicator */}
                {isZh ? '中文' : 'English'}
              </span>
            </button>
          </div>

          <div className="border-t border-slate-100 dark:border-slate-700 my-1" />

          {availableTenants.length > 0 && (
            <>
              <div className="px-4 py-2">
                <p className="text-2xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t('nav.tenant', 'Tenant')}
                </p>
              </div>
              <div className="py-1 max-h-44 overflow-y-auto">
                {availableTenants.map((tenant) => {
                  const isSelected = tenant.id === currentTenant?.id;

                  return (
                    <button
                      type="button"
                      key={tenant.id}
                      onClick={() => {
                        handleTenantSelect(tenant);
                      }}
                      className={`w-full flex items-center gap-2.5 px-4 py-2 text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset ${
                        isSelected
                          ? 'bg-primary/5 text-primary'
                          : 'text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800'
                      }`}
                    >
                      <span className="truncate">{tenant.name}</span>
                      {isSelected && <Check size={16} className="ml-auto" />}
                    </button>
                  );
                })}
              </div>

              <div className="border-t border-slate-100 dark:border-slate-700 my-1" />
            </>
          )}

          {/* Navigation */}
          <div className="py-1">
            <MenuLink
              icon={<User size={16} />}
              label={t('user.profile', 'Profile')}
              onClick={() => {
                void navigate(`${basePath}/profile`);
                setOpen(false);
              }}
            />
            <MenuLink
              icon={<Settings size={16} />}
              label={t('user.settings', 'Settings')}
              onClick={() => {
                void navigate(`${basePath}/settings`);
                setOpen(false);
              }}
            />
            <MenuLink
              icon={<CreditCard size={16} />}
              label={t('user.billing', 'Billing')}
              onClick={() => {
                void navigate(`${basePath}/billing`);
                setOpen(false);
              }}
            />
          </div>

          <div className="border-t border-slate-100 dark:border-slate-700 my-1" />

          <button
            type="button"
            onClick={handleLogout}
            className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
          >
            <LogOut size={16} />
            {t('common.logout', 'Logout')}
          </button>
        </div>
      )}
    </div>
  );
}

function MenuLink({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
    >
      <span className="text-slate-400">{icon}</span>
      {label}
    </button>
  );
}

export default TenantHeader;
