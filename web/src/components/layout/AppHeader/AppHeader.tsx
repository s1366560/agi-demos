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
  AppHeaderRootProps,
  HeaderVariant,
} from './types'

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
  children,
}: AppHeaderProps) {
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
        <HeaderContent variant={effectiveVariant} />
      </AppHeaderContext.Provider>
    )
  }

  return (
    <AppHeaderContext.Provider value={contextValue}>
      <HeaderWrapper>
        {children}
      </HeaderWrapper>
    </AppHeaderContext.Provider>
  )
})

/**
 * Header wrapper for compound components
 */
function HeaderWrapper({
  children,
}: {
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
      {/* Left: Sidebar toggle + Mobile menu */}
      <div className="flex items-center gap-3">
        {leftChildren}
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
  variant,
}: {
  variant: HeaderVariant
}) {
  const renderContent = () => {
    switch (variant) {
      case 'minimal':
        return (
          <header className="h-16 flex items-center justify-between px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex-none shrink-0">
            <div className="flex items-center gap-3" />
          </header>
        )

      case 'compact':
        return (
          <header className="h-16 flex items-center justify-between px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex-none shrink-0">
            <div className="flex items-center gap-3" />
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
            <div className="flex items-center gap-3" />
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
