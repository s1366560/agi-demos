/**
 * TenantHeader - Clean single-row navigation header for tenant pages
 *
 * 3-zone layout:
 *   Left:   Sidebar toggle + brand
 *   Center: Primary navigation tabs + overflow "More" menu
 *   Right:  Search + Notifications + User menu
 */

import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';

import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useLocation } from 'react-router-dom';

import {
  PanelLeft,
  PanelRight,
  Menu,
  Search,
  Check,
  ChevronDown,
  User,
  Settings,
  CreditCard,
  LogOut,
  Sun,
  Moon,
  Monitor,
  Languages,
  Activity,
  Command,
} from 'lucide-react';

import { useAuthActions, useUser } from '@/stores/auth';
import { useBackgroundStore, useRunningCount } from '@/stores/backgroundStore';
import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';
import { useThemeStore } from '@/stores/theme';
import { useCurrentWorkspace, useWorkspaces } from '@/stores/workspace';

import { authAPI } from '@/services/api';

import { NotificationDropdown } from './NotificationDropdown';
import {
  getContextualTopNavItems,
  groupTenantTopNavItems,
  isContextualTopNavItemActive,
} from './tenantNavigation';

import type { Tenant } from '@/types/memory';

import type { TenantTopNavGroup } from './tenantNavigation';

interface TenantHeaderProps {
  tenantId: string;
  sidebarCollapsed: boolean;
  onSidebarToggle: () => void;
  onMobileMenuOpen: () => void;
  projectId?: string | undefined;
  onCommandPaletteOpen?: (() => void) | undefined;
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

const TenantHeader: React.FC<TenantHeaderProps> = ({
  tenantId,
  sidebarCollapsed,
  onSidebarToggle,
  onMobileMenuOpen,
  projectId,
  onCommandPaletteOpen,
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
  const contextualNavGroups = useMemo(
    () => groupTenantTopNavItems(contextualNavItems),
    [contextualNavItems]
  );
  const searchPath = projectBasePath ? `${projectBasePath}/advanced-search` : null;
  const isMacPlatform = typeof navigator !== 'undefined' && /mac/i.test(navigator.userAgent);
  const commandPaletteLabel = isMacPlatform
    ? t('commandPalette.trigger', 'Command palette (⌘K)')
    : t('commandPalette.triggerNonMac', 'Command palette (Ctrl K)');

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
            {currentTenant ? (
              <span className="hidden md:flex items-center gap-1.5 min-w-0 text-xs text-slate-500 dark:text-slate-400">
                <span aria-hidden className="text-slate-300 dark:text-slate-600">
                  /
                </span>
                <span
                  className="max-w-36 truncate font-medium"
                  title={currentTenant.name}
                  data-testid="header-tenant-name"
                >
                  {currentTenant.name}
                </span>
                {effectiveProjectId && tenantCurrentProject ? (
                  <>
                    <span aria-hidden className="text-slate-300 dark:text-slate-600">
                      /
                    </span>
                    <span className="max-w-36 truncate" title={tenantCurrentProject.name}>
                      {tenantCurrentProject.name}
                    </span>
                  </>
                ) : null}
              </span>
            ) : null}
          </div>

          {/* Center: Nav tabs */}
          <nav className="hidden xl:flex items-center gap-0.5 flex-1 min-w-0 ml-4 mr-2 overflow-hidden">
            {contextualNavGroups.map((group) => (
              <GroupedNavDropdown key={group.id} group={group} />
            ))}
          </nav>

          <nav
            className="hidden md:flex xl:hidden items-center flex-1 min-w-0 ml-2 mr-2 overflow-hidden"
            aria-label={t('nav.navigation', 'Navigation')}
          >
            <GroupedNavMenu
              groups={contextualNavGroups}
              label={t('nav.navigation', 'Navigation')}
              icon={<Menu size={16} />}
            />
          </nav>

          {/* Right: Actions */}
          <div className="flex items-center gap-1 sm:gap-2 ml-auto flex-none">
            {onCommandPaletteOpen ? (
              <button
                type="button"
                onClick={onCommandPaletteOpen}
                className="hidden md:flex items-center gap-2 h-9 px-2.5 rounded-lg border border-slate-200 dark:border-border-dark text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-700 dark:hover:text-slate-200 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                aria-label={commandPaletteLabel}
                title={commandPaletteLabel}
              >
                <Command size={16} />
                <kbd className="text-[10px] font-medium tracking-wide opacity-70">
                  {isMacPlatform ? '⌘K' : 'Ctrl K'}
                </kbd>
              </button>
            ) : null}
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
 * Desktop dropdown for one logical navigation group.
 */
function GroupedNavDropdown({ group }: { group: TenantTopNavGroup }) {
  return <GroupedNavMenu groups={[group]} label={group.label} showGroupHeaders={false} />;
}

/**
 * Dropdown menu for one or more logical navigation groups.
 */
function GroupedNavMenu({
  groups,
  label,
  icon,
  showGroupHeaders = true,
}: {
  groups: TenantTopNavGroup[];
  label?: string | undefined;
  icon?: React.ReactNode;
  showGroupHeaders?: boolean | undefined;
}) {
  const { t } = useTranslation();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState<{ left: number; top: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  // Set when the menu is opened from the keyboard; the first/last link gets
  // focus once the portal has rendered.
  const focusOnOpenRef = useRef<'first' | 'last' | null>(null);
  const items = useMemo(() => groups.flatMap((group) => group.items), [groups]);

  const updateMenuPosition = useCallback(() => {
    const trigger = ref.current;
    if (!trigger) return;

    const rect = trigger.getBoundingClientRect();
    const menuWidth = 240;
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

  // Escape closes the menu and returns focus to the trigger.
  useEffect(() => {
    if (!open) return undefined;

    function handleEscapeKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener('keydown', handleEscapeKey);
    return () => {
      document.removeEventListener('keydown', handleEscapeKey);
    };
  }, [open]);

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

  // Move focus into the menu when it was opened from the keyboard.
  useEffect(() => {
    if (!open || !menuPosition || focusOnOpenRef.current === null) return;

    const links = menuRef.current?.querySelectorAll<HTMLAnchorElement>('a[href]');
    const target = focusOnOpenRef.current === 'first' ? links?.[0] : links?.[links.length - 1];
    focusOnOpenRef.current = null;
    target?.focus();
  }, [open, menuPosition]);

  // Arrow/Home/End keys move focus between menu links, cycling at the edges.
  const handleMenuKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const menu = menuRef.current;
    if (!menu) return;
    const links = Array.from(menu.querySelectorAll<HTMLAnchorElement>('a[href]'));
    if (links.length === 0) return;

    const currentIndex = links.findIndex((link) => link === document.activeElement);
    let nextIndex: number;
    switch (event.key) {
      case 'ArrowDown':
        nextIndex = currentIndex < 0 ? 0 : (currentIndex + 1) % links.length;
        break;
      case 'ArrowUp':
        nextIndex =
          currentIndex < 0 ? links.length - 1 : (currentIndex - 1 + links.length) % links.length;
        break;
      case 'Home':
        nextIndex = 0;
        break;
      case 'End':
        nextIndex = links.length - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    links[nextIndex]?.focus();
  };

  // Arrow keys on the trigger open the menu and move focus into it.
  const handleTriggerKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    focusOnOpenRef.current = event.key === 'ArrowDown' ? 'first' : 'last';
    if (!open) {
      updateMenuPosition();
      setOpen(true);
    } else {
      const links = menuRef.current?.querySelectorAll<HTMLAnchorElement>('a[href]');
      const target = focusOnOpenRef.current === 'first' ? links?.[0] : links?.[links.length - 1];
      focusOnOpenRef.current = null;
      target?.focus();
    }
  };

  const isAnyActive = items.some((item) => isContextualTopNavItemActive(location.pathname, item));
  const buttonLabel = label ?? t('nav.more', 'More');
  const trailingIcon = <ChevronDown size={14} />;
  const menu =
    open && menuPosition
      ? createPortal(
          <div
            ref={menuRef}
            role="menu"
            aria-label={buttonLabel}
            onKeyDown={handleMenuKeyDown}
            className="fixed w-60 bg-white dark:bg-surface-dark rounded-xl shadow-lg border border-slate-200 dark:border-slate-700 py-1 z-50"
            style={{ left: menuPosition.left, top: menuPosition.top }}
          >
            {groups.map((group, groupIndex) => (
              <div
                key={group.id}
                className={
                  groupIndex > 0 ? 'border-t border-slate-100 pt-1 dark:border-slate-800' : ''
                }
              >
                {showGroupHeaders && group.label ? (
                  <p className="px-3 pb-1 pt-2 text-2xs font-semibold uppercase tracking-wider text-slate-400">
                    {group.label}
                  </p>
                ) : null}
                {group.items.map((item) => {
                  const isActive = isContextualTopNavItemActive(location.pathname, item);
                  return (
                    <Link
                      key={item.id}
                      to={item.path}
                      onClick={() => {
                        setOpen(false);
                      }}
                      aria-current={isActive ? 'page' : undefined}
                      className={`w-full flex items-center gap-2.5 px-3 py-2 text-left text-sm no-underline transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset ${
                        isActive
                          ? 'text-primary bg-primary/5'
                          : 'text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800'
                      }`}
                    >
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            ))}
          </div>,
          document.body
        )
      : null;

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => {
          updateMenuPosition();
          setOpen((currentOpen) => !currentOpen);
        }}
        onKeyDown={handleTriggerKeyDown}
        aria-label={buttonLabel}
        aria-expanded={open}
        aria-haspopup="menu"
        className={`flex items-center gap-1 px-2 py-1.5 rounded-lg text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 ${
          isAnyActive
            ? 'bg-primary/10 text-primary'
            : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
        }`}
      >
        {icon}
        <span className="hidden lg:inline">{buttonLabel}</span>
        {trailingIcon}
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
  const setPanel = useBackgroundStore((s) => s.setPanel);
  const backgroundTasksLabel =
    runningCount > 0
      ? t(
          'components.layout.header.backgroundTasksWithCount',
          'Background tasks, {{count}} running',
          {
            count: runningCount,
          }
        )
      : t('components.layout.header.backgroundTasks', 'Background tasks');

  return (
    <button
      type="button"
      onClick={() => {
        setPanel(true);
      }}
      className="relative p-1.5 sm:p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
      aria-label={backgroundTasksLabel}
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
 * Compact search button. Only projects expose a search surface today, so at
 * tenant level the entry renders disabled with an explanation instead of
 * mislinking to the project list.
 */
function SearchButton({ searchPath }: { searchPath: string | null }) {
  const { t } = useTranslation();

  if (!searchPath) {
    return (
      <span
        title={t(
          'components.layout.header.searchRequiresProject',
          'Search is available inside a project'
        )}
        className="inline-flex"
      >
        <button
          type="button"
          disabled
          aria-label={t('common.search', 'Search')}
          className="p-1.5 sm:p-2 rounded-lg text-slate-300 dark:text-slate-600 cursor-not-allowed"
        >
          <Search size={18} />
        </button>
      </span>
    );
  }

  return (
    <Link
      to={searchPath}
      className="p-1.5 sm:p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
      aria-label={t('common.search', 'Search')}
    >
      <Search size={18} />
    </Link>
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
  const clearProjects = useProjectStore((state) => state.clearProjects);
  const tenants = useTenantStore((state) => state.tenants);
  const listTenants = useTenantStore((state) => state.listTenants);
  const [open, setOpen] = useState(false);
  const [tenantsLoadError, setTenantsLoadError] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
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

  // Escape closes the menu and returns focus to the trigger.
  useEffect(() => {
    if (!open) return undefined;

    function handleEscapeKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener('keydown', handleEscapeKey);
    return () => {
      document.removeEventListener('keydown', handleEscapeKey);
    };
  }, [open]);

  useEffect(() => {
    if (open && tenants.length === 0) {
      void listTenants()
        .then(() => {
          setTenantsLoadError(false);
        })
        .catch(() => {
          setTenantsLoadError(true);
        });
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
    setOpen(false);
    if (tenant.id === normalizedTenantId) {
      return;
    }
    clearProjects();
    void navigate(`/tenant/${tenant.id}/overview`);
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
        ref={triggerRef}
        type="button"
        onClick={() => {
          setOpen(!open);
        }}
        className="flex items-center gap-1.5 p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
        aria-label={t('components.layout.header.userMenu', 'User menu')}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <div className="flex h-7 w-7 items-center justify-center overflow-hidden rounded-full bg-slate-900 text-xs font-medium text-slate-50 dark:bg-slate-100 dark:text-slate-900">
          {avatarUrl ? (
            <img
              src={avatarUrl}
              alt={displayName}
              loading="lazy"
              decoding="async"
              className="w-full h-full object-cover"
            />
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

          {tenantsLoadError && availableTenants.length === 0 && (
            <div className="flex items-center justify-between gap-2 px-4 py-2 text-xs text-rose-600 dark:text-rose-400">
              <span>
                {t('components.layout.header.tenantsLoadFailed', 'Failed to load tenant list')}
              </span>
              <button
                type="button"
                onClick={() => {
                  setTenantsLoadError(false);
                  void listTenants().catch(() => {
                    setTenantsLoadError(true);
                  });
                }}
                className="shrink-0 font-medium underline hover:no-underline"
              >
                {t('common.retry', 'Retry')}
              </button>
            </div>
          )}

          {availableTenants.length > 0 && (
            <>
              <div className="px-4 py-2">
                <p className="text-2xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t('nav.tenant', 'Tenant')}
                </p>
              </div>
              <div className="py-1 max-h-44 overflow-y-auto">
                {availableTenants.map((tenant) => {
                  const isSelected = tenant.id === normalizedTenantId;

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
              to={`${basePath}/profile`}
              onClick={() => {
                setOpen(false);
              }}
            />
            <MenuLink
              icon={<Settings size={16} />}
              label={t('user.settings', 'Settings')}
              to={`${basePath}/settings`}
              onClick={() => {
                setOpen(false);
              }}
            />
            <MenuLink
              icon={<CreditCard size={16} />}
              label={t('user.billing', 'Billing')}
              to={`${basePath}/billing`}
              onClick={() => {
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
  to,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  to: string;
  onClick: () => void;
}) {
  return (
    <Link
      to={to}
      onClick={onClick}
      className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
    >
      <span className="text-slate-400">{icon}</span>
      {label}
    </Link>
  );
}

export default TenantHeader;
