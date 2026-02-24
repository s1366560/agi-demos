/**
 * AppHeader - Compound Component
 *
 * A reusable header component using the compound component pattern.
 * Features responsive layout that adapts to different screen sizes.
 *
 * Usage:
 *   <AppHeader basePath="/tenant">
 *     <AppHeader.SidebarToggle collapsed={false} onToggle={...} />
 *     <AppHeader.Search />
 *     <AppHeader.Tools>
 *       <AppHeader.ThemeToggle />
 *       <AppHeader.LanguageSwitcher />
 *     </AppHeader.Tools>
 *     <AppHeader.Notifications count={3} />
 *     <AppHeader.WorkspaceSwitcher mode="tenant" />
 *     <AppHeader.UserMenu />
 *   </AppHeader>
 *
 * Variant presets:
 *   <AppHeader basePath="/tenant" variant="full" />
 *   <AppHeader basePath="/tenant" variant="minimal" />
 */

import * as React from 'react';

// Import subcomponents
import { useThemeStore } from '@/stores/theme';

import { useBreadcrumbs } from '@/hooks/useBreadcrumbs';

import { LanguageSwitcher } from './LanguageSwitcher';
import { MobileMenu } from './MobileMenu';
import { Notifications } from './Notifications';
import { PrimaryAction } from './PrimaryAction';
import { Search } from './Search';
import { SidebarToggle } from './SidebarToggle';
import { ThemeToggle } from './ThemeToggle';
import { Tools } from './Tools';
import { UserMenu } from './UserMenu';
import { WorkspaceSwitcher } from './WorkspaceSwitcher';

// Import types
import type { AppHeaderRootProps, HeaderVariant, Breadcrumb } from './types';

// Import theme store for simple toggle

// Import breadcrumbs hook

/**
 * Context for compound components
 */
interface AppHeaderContextValue {
  basePath: string;
  context?: 'tenant' | 'project' | 'agent' | undefined;
}

const AppHeaderContext = React.createContext<AppHeaderContextValue | null>(null);

/**
 * Breadcrumb display component
 */
function BreadcrumbNav({ breadcrumbs }: { breadcrumbs: Breadcrumb[] }) {
  if (!breadcrumbs || breadcrumbs.length === 0) return null;

  return (
    <nav
      aria-label="Breadcrumb"
      className="flex items-center text-sm text-slate-500 dark:text-slate-400"
    >
      {breadcrumbs.map((crumb, index) => {
        const isLast = index === breadcrumbs.length - 1;
        return (
          <React.Fragment key={index}>
            {index > 0 && <span className="mx-2 text-slate-300 dark:text-slate-600">/</span>}
            {isLast ? (
              <span className="font-medium text-slate-900 dark:text-white truncate max-w-32 sm:max-w-48">
                {crumb.label}
              </span>
            ) : (
              <a
                href={crumb.path}
                className="hover:text-slate-700 dark:hover:text-slate-200 transition-colors truncate max-w-24 sm:max-w-32"
              >
                {crumb.label}
              </a>
            )}
          </React.Fragment>
        );
      })}
    </nav>
  );
}

/**
 * Root AppHeader component
 */
interface AppHeaderProps extends AppHeaderRootProps {
  children?: React.ReactNode | undefined;
  breadcrumbs?: Breadcrumb[] | undefined;
}

export const AppHeaderRoot = React.memo(function AppHeader({
  basePath,
  context = 'tenant',
  variant = 'full',
  breadcrumbs,
  children,
}: AppHeaderProps) {
  const contextValue: AppHeaderContextValue = React.useMemo(
    () => ({ basePath, context }),
    [basePath, context]
  );

  // If no children provided, use variant preset (default to 'full')
  const hasChildren = children && React.Children.count(children) > 0;
  if (!hasChildren) {
    const effectiveVariant = variant === 'custom' ? 'full' : variant;
    return (
      <AppHeaderContext.Provider value={contextValue}>
        <HeaderContent variant={effectiveVariant} breadcrumbs={breadcrumbs} context={context} />
      </AppHeaderContext.Provider>
    );
  }

  return (
    <AppHeaderContext.Provider value={contextValue}>
      <HeaderWrapper breadcrumbs={breadcrumbs} context={context}>
        {children}
      </HeaderWrapper>
    </AppHeaderContext.Provider>
  );
});

/**
 * Header wrapper for compound components
 * Uses a responsive three-section layout: left | center | right
 */
function HeaderWrapper({
  children,
  breadcrumbs: customBreadcrumbs,
  context = 'tenant',
}: {
  children: React.ReactNode;
  breadcrumbs?: Breadcrumb[] | undefined;
  context?: 'tenant' | 'project' | 'agent' | undefined;
}) {
  // Get breadcrumbs from hook if not provided
  const hookBreadcrumbs = useBreadcrumbs(context);
  const breadcrumbs = customBreadcrumbs ?? hookBreadcrumbs;

  // Group children by section using slot prop
  const leftChildren: React.ReactNode[] = [];
  const centerChildren: React.ReactNode[] = [];
  const rightChildren: React.ReactNode[] = [];

  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child)) return;

    // Check the slot prop to determine position
    const slot = (child.props as any)?.slot ?? 'right';

    if (slot === 'left') {
      leftChildren.push(child);
    } else if (slot === 'center') {
      centerChildren.push(child);
    } else {
      rightChildren.push(child);
    }
  });

  return (
    <header className="h-16 px-4 sm:px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex items-center flex-none shrink-0">
      <div className="h-full w-full flex items-center justify-between gap-4">
        {/* Left section: Sidebar toggle + Navigation */}
        <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0">
          {leftChildren}
          {/* Show breadcrumbs in left if no explicit left children */}
          {leftChildren.length === 0 && breadcrumbs && <BreadcrumbNav breadcrumbs={breadcrumbs} />}
        </div>

        {/* Center section: Title/Breadcrumbs (hidden on small screens if empty) */}
        {centerChildren.length > 0 && (
          <div className="hidden sm:flex items-center justify-center flex-1 min-w-0 mx-4">
            {centerChildren}
          </div>
        )}

        {/* Right section: Actions - with responsive spacing and wrapping */}
        <div className="flex items-center gap-2 sm:gap-3 lg:gap-4 flex-shrink-0">
          {rightChildren}
        </div>
      </div>
    </header>
  );
}

/**
 * Header content for variant presets
 * Features responsive layout that adapts to different screen sizes
 */
function HeaderContent({
  variant,
  breadcrumbs: customBreadcrumbs,
  context = 'tenant',
}: {
  variant: HeaderVariant;
  breadcrumbs?: Breadcrumb[] | undefined;
  context?: 'tenant' | 'project' | 'agent' | undefined;
}) {
  // Get breadcrumbs from hook if not provided
  const hookBreadcrumbs2 = useBreadcrumbs(context);
  const breadcrumbs = customBreadcrumbs ?? hookBreadcrumbs2;

  const renderContent = () => {
    switch (variant) {
      case 'minimal':
        return (
          <header className="h-16 px-4 sm:px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex items-center flex-none shrink-0">
            <div className="h-full w-full flex items-center justify-between">
              <div className="flex items-center gap-2 sm:gap-3">
                {breadcrumbs && <BreadcrumbNav breadcrumbs={breadcrumbs} />}
              </div>
              <div className="flex items-center gap-2 sm:gap-3" />
            </div>
          </header>
        );

      case 'compact':
        return (
          <header className="h-16 px-4 sm:px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex items-center flex-none shrink-0">
            <div className="h-full w-full flex items-center justify-between gap-4">
              {/* Left: Breadcrumb */}
              <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0">
                {breadcrumbs && <BreadcrumbNav breadcrumbs={breadcrumbs} />}
              </div>

              {/* Right: Essential actions only */}
              <div className="flex items-center gap-2 sm:gap-3 lg:gap-4 flex-shrink-0">
                {/* Theme toggle - always visible */}
                <div className="hidden sm:block">
                  <ThemeToggle />
                </div>
                {/* Simplified theme toggle for mobile */}
                <div className="sm:hidden">
                  <SimpleThemeToggle />
                </div>
                <UserMenu />
              </div>
            </div>
          </header>
        );

      case 'full':
        return (
          <header className="h-16 px-4 sm:px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex items-center flex-none shrink-0">
            <div className="h-full w-full flex items-center justify-between gap-2 sm:gap-4">
              {/* Left: Breadcrumbs */}
              <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0 min-w-0">
                {breadcrumbs && <BreadcrumbNav breadcrumbs={breadcrumbs} />}
              </div>

              {/* Right: Actions - responsive visibility */}
              <div className="flex items-center gap-2 sm:gap-3 lg:gap-4 flex-shrink-0">
                {/* Search - hidden on mobile, shown on md+ */}
                <div className="hidden md:block">
                  <Search />
                </div>

                {/* Search icon button for mobile/tablet */}
                <button
                  type="button"
                  className="md:hidden p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors flex-shrink-0"
                  aria-label="Search"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                    />
                  </svg>
                </button>

                {/* Theme toggle - always visible */}
                <div className="hidden sm:block">
                  <ThemeToggle />
                </div>
                {/* Simple theme toggle for mobile */}
                <div className="sm:hidden">
                  <SimpleThemeToggle />
                </div>

                {/* Language switcher - hidden on small screens */}
                <div className="hidden lg:block">
                  <LanguageSwitcher />
                </div>

                {/* Notifications */}
                <Notifications />

                {/* Divider - hidden on small screens */}
                <div className="hidden sm:block h-6 w-px bg-slate-200 dark:bg-slate-700 mx-1 flex-shrink-0" />

                {/* Workspace switcher - responsive width */}
                <div className="w-40 sm:w-48 lg:w-56 flex-shrink-0">
                  <WorkspaceSwitcher mode="tenant" />
                </div>

                {/* Divider - hidden on small screens */}
                <div className="hidden sm:block h-6 w-px bg-slate-200 dark:bg-slate-700 mx-1 flex-shrink-0" />

                {/* User menu - compact on mobile */}
                <UserMenu />
              </div>
            </div>
          </header>
        );

      default:
        return null;
    }
  };

  return renderContent();
}

/**
 * Simple theme toggle for mobile - shows only current theme with dropdown
 */
function SimpleThemeToggle() {
  const [isOpen, setIsOpen] = React.useState(false);
  const dropdownRef = React.useRef<HTMLDivElement>(null);
  const theme = useThemeStore((state) => state.theme);
  const setTheme = useThemeStore((state) => state.setTheme);

  React.useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => { document.removeEventListener('mousedown', handleClickOutside); };
  }, []);

  const themeIcons = {
    light: (
      <svg
        className="w-5 h-5 text-yellow-500"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"
        />
      </svg>
    ),
    dark: (
      <svg
        className="w-5 h-5 text-indigo-400"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M20.354 24.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
        />
      </svg>
    ),
    system: (
      <svg className="w-5 h-5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
        />
      </svg>
    ),
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => { setIsOpen(!isOpen); }}
        className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        aria-label="Toggle theme"
        type="button"
      >
        {themeIcons[theme as keyof typeof themeIcons]}
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-32 bg-white dark:bg-surface-dark rounded-lg shadow-lg border border-slate-200 dark:border-slate-700 py-1 z-50">
          {(['light', 'dark', 'system'] as const).map((t) => (
            <button
              key={t}
              onClick={() => {
                setTheme(t);
                setIsOpen(false);
              }}
              className={`w-full flex items-center gap-2 px-3 py-2 text-sm capitalize transition-colors ${
                theme === t
                  ? 'bg-slate-50 dark:bg-slate-800 text-primary'
                  : 'text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800'
              }`}
              type="button"
            >
              {themeIcons[t]}
              {t}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Attach subcomponents to AppHeader
const AppHeader = Object.assign(AppHeaderRoot, {
  SidebarToggle,
  MobileMenu,
  Search,
  Notifications,
  Tools,
  ThemeToggle,
  LanguageSwitcher,
  WorkspaceSwitcher,
  UserMenu,
  PrimaryAction,
});

export { AppHeader };
export default AppHeader;
