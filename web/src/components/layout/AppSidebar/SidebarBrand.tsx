/**
 * SidebarBrand Component
 *
 * Brand section of the sidebar, showing the MemStack logo and name.
 */

import type { SidebarVariant } from './types'

export interface SidebarBrandProps {
  /** Variant to determine branding style */
  variant?: SidebarVariant
  /** Custom brand element (overrides default) */
  children?: React.ReactNode
}

/**
 * Get default brand element for each variant
 */
function getDefaultBrand(_variant?: SidebarVariant): React.ReactNode {
  return (
    <div className="flex items-center gap-3 px-2">
      <div className="bg-primary/10 p-2 rounded-lg border border-primary/20">
        <span className="material-symbols-outlined text-primary">memory</span>
      </div>
      <h1 className="text-slate-900 dark:text-white text-lg font-bold leading-none tracking-tight">
        MemStack<span className="text-primary">.ai</span>
      </h1>
    </div>
  )
}

/**
 * SidebarBrand component - displays the brand/logo section
 */
export function SidebarBrand({ variant, children }: SidebarBrandProps) {
  const content = children ?? getDefaultBrand(variant)

  return (
    <div data-testid="sidebar-brand" data-variant={variant}>
      {content}
    </div>
  )
}
