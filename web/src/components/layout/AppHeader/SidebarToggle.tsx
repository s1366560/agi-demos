/**
 * AppHeader.SidebarToggle - Compound Component
 *
 * Sidebar toggle button for collapsing/expanding the sidebar.
 */

import * as React from 'react'

import { PanelLeft, PanelRight } from 'lucide-react'

export interface SidebarToggleProps {
  collapsed: boolean
  onToggle: () => void
  ariaLabel?: string
  /** @internal Slot for positioning */
  slot?: 'left' | 'right'
}

export const SidebarToggle = React.memo(function SidebarToggle({
  collapsed,
  onToggle,
  ariaLabel,
}: SidebarToggleProps) {
  if (!onToggle) {
    return null
  }

  const defaultLabel = collapsed ? 'Expand sidebar' : 'Collapse sidebar'

  return (
    <button
      onClick={onToggle}
      className="p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
      aria-label={ariaLabel || defaultLabel}
      title={ariaLabel || defaultLabel}
      type="button"
    >
      {collapsed ? (
        <PanelRight className="w-5 h-5" />
      ) : (
        <PanelLeft className="w-5 h-5" />
      )}
    </button>
  )
})

SidebarToggle.displayName = 'AppHeader.SidebarToggle'
