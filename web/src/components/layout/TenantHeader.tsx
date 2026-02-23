/**
 * TenantHeader - Clean single-row navigation header for tenant pages
 *
 * 3-zone layout:
 *   Left:   Sidebar toggle + brand
 *   Center: Primary navigation tabs + overflow "More" menu
 *   Right:  Search + Notifications + User menu
 */

import React, { useState, useRef, useEffect, useMemo } from 'react';

import { useTranslation } from 'react-i18next';
import { NavLink, Link, useNavigate, useLocation } from 'react-router-dom';

import {
  PanelLeft,
  PanelRight,
  Menu,
  Bell,
  Search,
  ChevronDown,
  Folder,
  Brain,
  Bot,
  Cpu,
  Cable,
  ToyBrick,
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

import { useUser, useAuthActions } from '@/stores/auth';
import { useRunningCount, useBackgroundStore } from '@/stores/backgroundStore';
import { useThemeStore } from '@/stores/theme';

interface TenantHeaderProps {
  tenantId: string;
  sidebarCollapsed: boolean;
  onSidebarToggle: () => void;
  onMobileMenuOpen: () => void;
}

interface NavItem {
  id: string;
  label: string;
  path: string;
  icon: React.ReactNode;
}

const TenantHeader: React.FC<TenantHeaderProps> = ({
  tenantId,
  sidebarCollapsed,
  onSidebarToggle,
  onMobileMenuOpen,
}) => {
  const { t } = useTranslation();
  const basePath = `/tenant/${tenantId}`;

  const allNav: NavItem[] = useMemo(
    () => [
      {
        id: 'projects',
        label: t('nav.projects', 'Projects'),
        path: `${basePath}/projects`,
        icon: <Folder size={16} />,
      },
      {
        id: 'skills',
        label: t('nav.skills', 'Skills'),
        path: `${basePath}/skills`,
        icon: <Brain size={16} />,
      },
      {
        id: 'subagents',
        label: t('nav.subagents', 'Agents'),
        path: `${basePath}/subagents`,
        icon: <Bot size={16} />,
      },
      {
        id: 'mcp-servers',
        label: t('nav.mcpServers', 'MCP'),
        path: `${basePath}/mcp-servers`,
        icon: <Cable size={16} />,
      },
      {
        id: 'plugins',
        label: t('nav.plugins', 'Plugins'),
        path: `${basePath}/plugins`,
        icon: <ToyBrick size={16} />,
      },
      {
        id: 'providers',
        label: t('nav.providers', 'Model Services'),
        path: `${basePath}/providers`,
        icon: <Cpu size={16} />,
      },
    ],
    [basePath, t]
  );

  // With 6 items, all fit on md+ screens; overflow only if needed
  const visibleNav = allNav;
  const overflowNav: NavItem[] = [];

  return (
    <header className="h-14 px-3 sm:px-4 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex items-center flex-none shrink-0">
      <div className="h-full w-full flex items-center gap-1 sm:gap-3">
        {/* Left: Mobile menu + Sidebar toggle + Brand */}
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            type="button"
            onClick={onMobileMenuOpen}
            className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors md:hidden"
            aria-label="Menu"
          >
            <Menu size={18} className="text-slate-500" />
          </button>
          <button
            type="button"
            onClick={onSidebarToggle}
            className="hidden md:flex p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-slate-500"
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? <PanelRight size={18} /> : <PanelLeft size={18} />}
          </button>
          <Link
            to={basePath}
            className="text-sm font-semibold text-slate-800 dark:text-slate-200 hover:text-primary transition-colors hidden sm:block ml-1"
          >
            MemStack
          </Link>
        </div>

        {/* Center: Nav tabs */}
        <nav className="hidden md:flex items-center gap-0.5 flex-1 min-w-0 ml-4">
          {visibleNav.map((item) => (
            <NavLink
              key={item.id}
              to={item.path}
              className={({ isActive }) =>
                `flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap ${
                  isActive
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

        {/* Right: Actions */}
        <div className="flex items-center gap-1 sm:gap-2 ml-auto flex-shrink-0">
          <SearchButton />
          <BackgroundTasksButton />
          <NotificationButton />
          <HeaderUserMenu tenantId={tenantId} />
        </div>
      </div>
    </header>
  );
};

/**
 * Overflow "More" dropdown for secondary nav items
 */
function OverflowMenu({ items }: { items: NavItem[] }) {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const isAnyActive = items.some((item) => location.pathname.startsWith(item.path));

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-sm font-medium transition-colors ${
          isAnyActive
            ? 'bg-primary/10 text-primary'
            : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
        }`}
      >
        <MoreHorizontal size={16} />
        <span className="hidden lg:inline">{t('nav.more', 'More')}</span>
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 w-48 bg-white dark:bg-surface-dark rounded-xl shadow-lg border border-slate-200 dark:border-slate-700 py-1 z-50">
          {items.map((item) => {
            const isActive = location.pathname.startsWith(item.path);
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  navigate(item.path);
                  setOpen(false);
                }}
                className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? 'text-primary bg-primary/5'
                    : 'text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800'
                }`}
              >
                <span className={isActive ? 'text-primary' : 'text-slate-400'}>{item.icon}</span>
                {item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * Background SubAgent tasks indicator
 */
function BackgroundTasksButton() {
  const runningCount = useRunningCount();
  const togglePanel = useBackgroundStore((s) => s.togglePanel);

  return (
    <button
      type="button"
      onClick={togglePanel}
      className="relative p-1.5 sm:p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors"
      aria-label="Background tasks"
    >
      <Activity size={18} />
      {runningCount > 0 && (
        <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 bg-primary text-white text-[10px] font-bold rounded-full flex items-center justify-center">
          {runningCount}
        </span>
      )}
    </button>
  );
}

/**
 * Compact search button (icon only, expandable later)
 */
function SearchButton() {
  return (
    <button
      type="button"
      className="p-1.5 sm:p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors"
      aria-label="Search"
    >
      <Search size={18} />
    </button>
  );
}

/**
 * Notification bell
 */
function NotificationButton() {
  return (
    <button
      type="button"
      className="p-1.5 sm:p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors"
      aria-label="Notifications"
    >
      <Bell size={18} />
    </button>
  );
}

/**
 * Enhanced user menu with theme, language, settings, billing
 */
function HeaderUserMenu({ tenantId }: { tenantId: string }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const user = useUser();
  const { logout } = useAuthActions();
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  if (!user) return null;

  const displayName = user.name || user.email.split('@')[0];
  const initials = displayName
    .split(' ')
    .map((n: string) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
  const avatarUrl = user.profile?.avatar_url;
  const basePath = `/tenant/${tenantId}`;

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const cycleTheme = () => {
    const themes: Array<'light' | 'dark' | 'system'> = ['light', 'dark', 'system'];
    const idx = themes.indexOf(theme as 'light' | 'dark' | 'system');
    setTheme(themes[(idx + 1) % themes.length]);
  };

  const toggleLanguage = () => {
    const next = i18n.language === 'zh-CN' ? 'en-US' : 'zh-CN';
    i18n.changeLanguage(next);
  };

  const themeIcon =
    theme === 'dark' ? (
      <Moon size={16} />
    ) : theme === 'light' ? (
      <Sun size={16} />
    ) : (
      <Monitor size={16} />
    );

  const themeLabel =
    theme === 'dark'
      ? t('theme.dark', 'Dark')
      : theme === 'light'
        ? t('theme.light', 'Light')
        : t('theme.system', 'System');

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        aria-label="User menu"
      >
        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-primary to-primary-dark flex items-center justify-center text-white text-xs font-medium overflow-hidden">
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
          </div>

          {/* Quick actions */}
          <div className="py-1">
            <button
              type="button"
              onClick={cycleTheme}
              className="w-full flex items-center justify-between px-4 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
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
              className="w-full flex items-center justify-between px-4 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
            >
              <span className="flex items-center gap-2.5">
                <Languages size={16} className="text-slate-400" />
                {t('user.language', 'Language')}
              </span>
              <span className="text-xs text-slate-400">
                {i18n.language === 'zh-CN' ? '中文' : 'EN'}
              </span>
            </button>
          </div>

          <div className="border-t border-slate-100 dark:border-slate-700 my-1" />

          {/* Navigation */}
          <div className="py-1">
            <MenuLink
              icon={<User size={16} />}
              label={t('user.profile', 'Profile')}
              onClick={() => {
                navigate('/profile');
                setOpen(false);
              }}
            />
            <MenuLink
              icon={<Settings size={16} />}
              label={t('user.settings', 'Settings')}
              onClick={() => {
                navigate(`${basePath}/settings`);
                setOpen(false);
              }}
            />
            <MenuLink
              icon={<CreditCard size={16} />}
              label={t('user.billing', 'Billing')}
              onClick={() => {
                navigate(`${basePath}/billing`);
                setOpen(false);
              }}
            />
          </div>

          <div className="border-t border-slate-100 dark:border-slate-700 my-1" />

          <button
            type="button"
            onClick={handleLogout}
            className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
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
      className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
    >
      <span className="text-slate-400">{icon}</span>
      {label}
    </button>
  );
}

export default TenantHeader;
