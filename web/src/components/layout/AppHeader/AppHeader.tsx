/**
 * AppHeader - Compound Component
 *
 * A reusable header component using the compound component pattern.
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

import * as React from 'react'

import { Link } from 'react-router-dom'

import { useBreadcrumbs } from '@/hooks/useBreadcrumbs'

// Import subcomponents
import { LanguageSwitcher } from './LanguageSwitcher'
import { MobileMenu } from './MobileMenu'
import { Notifications } from './Notifications'
import { PrimaryAction } from './PrimaryAction'
import { Search } from './Search'
import { SidebarToggle } from './SidebarToggle'
import { ThemeToggle } from './ThemeToggle'
import { Tools } from './Tools'
import { UserMenu } from './UserMenu'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'

// Import types
import type {
  Breadcrumb,
  AppHeaderRootProps,
  HeaderVariant,
} from './types'

/**
 * Default breadcrumbs when no custom breadcrumbs provided
 */
function DefaultBreadcrumbs({ crumbs }: { crumbs: Breadcrumb[] }) {
  if (crumbs.length === 0) return null

  return (
    <nav className="flex items-center text-sm">
      {crumbs.map((crumb, index, array) => (
        <React.Fragment key={crumb.path}>
          {index > 0 && (
            <span className="mx-2 text-slate-300 dark:text-slate-600">/</span>
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
  )
}

/**
 * Context for compound components
 */
interface AppHeaderContextValue {
  basePath: string
  context?: 'tenant' | 'project' | 'agent'
}

const AppHeaderContext = React.createContext<AppHeaderContextValue | null>(null)

/**
 * Root AppHeader component
 */
interface AppHeaderProps extends AppHeaderRootProps {
  children?: React.ReactNode
}

export const AppHeaderRoot = React.memo(function AppHeader({
  basePath,
  context = 'tenant',
  variant = 'full',
  breadcrumbs: customBreadcrumbs,
  breadcrumbOptions,
  children,
}: AppHeaderProps) {
  // Use custom breadcrumbs or generate from hook
  const defaultBreadcrumbs = useBreadcrumbs(context, breadcrumbOptions)
  const breadcrumbs = customBreadcrumbs ?? defaultBreadcrumbs

  const contextValue: AppHeaderContextValue = React.useMemo(
    () => ({ basePath, context }),
    [basePath, context]
  )

  // If no children provided, use variant preset (default to 'full')
  const hasChildren = children && React.Children.count(children) > 0
  if (!hasChildren) {
    const effectiveVariant = variant === 'custom' ? 'full' : variant
    return (
      <AppHeaderContext.Provider value={contextValue}>
        <HeaderContent
          breadcrumbs={breadcrumbs}
          variant={effectiveVariant}
        />
      </AppHeaderContext.Provider>
    )
  }

  return (
    <AppHeaderContext.Provider value={contextValue}>
      <HeaderWrapper breadcrumbs={breadcrumbs}>
        {children}
      </HeaderWrapper>
    </AppHeaderContext.Provider>
  )
})

/**
 * Header wrapper for compound components
 */
function HeaderWrapper({
  breadcrumbs,
  children,
}: {
  breadcrumbs: Breadcrumb[]
  children: React.ReactNode
}) {
  // Group children by section using slot prop
  const leftChildren: React.ReactNode[] = []
  const rightChildren: React.ReactNode[] = []

  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child)) return

    // Check the slot prop to determine position
    // Default to 'right' if no slot is specified
    const slot = (child.props as any)?.slot ?? 'right'

    if (slot === 'left') {
      leftChildren.push(child)
    } else {
      rightChildren.push(child)
    }
  })

  return (
    <header className="h-16 flex items-center justify-between px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex-none shrink-0">
      {/* Left: Sidebar toggle + Mobile menu + Breadcrumbs */}
      <div className="flex items-center gap-3">
        {leftChildren}
        <div className="ml-1">
          <DefaultBreadcrumbs crumbs={breadcrumbs} />
        </div>
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-4">
        {rightChildren}
      </div>
    </header>
  )
}

/**
 * Header content for variant presets
 */
function HeaderContent({
  breadcrumbs,
  variant,
}: {
  breadcrumbs: Breadcrumb[]
  variant: HeaderVariant
}) {
  const renderContent = () => {
    switch (variant) {
      case 'minimal':
        return (
          <header className="h-16 flex items-center justify-between px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex-none shrink-0">
            <div className="flex items-center gap-3">
              <div className="ml-1">
                <DefaultBreadcrumbs crumbs={breadcrumbs} />
              </div>
            </div>
          </header>
        )

      case 'compact':
        return (
          <header className="h-16 flex items-center justify-between px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex-none shrink-0">
            <div className="flex items-center gap-3">
              <div className="ml-1">
                <DefaultBreadcrumbs crumbs={breadcrumbs} />
              </div>
            </div>
            <div className="flex items-center gap-4">
              <ThemeToggle />
              <LanguageSwitcher />
              <UserMenu />
            </div>
          </header>
        )

      case 'full':
        return (
          <header className="h-16 flex items-center justify-between px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex-none shrink-0">
            <div className="flex items-center gap-3">
              <div className="ml-1">
                <DefaultBreadcrumbs crumbs={breadcrumbs} />
              </div>
            </div>
            <div className="flex items-center gap-4">
              <Search />
              <ThemeToggle />
              <LanguageSwitcher />
              <Notifications />
              <div className="h-6 w-px bg-slate-200 dark:bg-slate-700" />
              <WorkspaceSwitcher mode="tenant" />
              <div className="h-6 w-px bg-slate-200 dark:bg-slate-700" />
              <UserMenu />
            </div>
          </header>
        )

      default:
        return null
    }
  }

  return renderContent()
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
})

export { AppHeader }
export default AppHeader
