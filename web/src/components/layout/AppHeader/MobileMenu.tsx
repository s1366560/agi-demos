/**
 * AppHeader.MobileMenu - Compound Component
 *
 * Mobile menu toggle button for responsive layouts.
 */

import * as React from 'react'

import { Menu } from 'lucide-react'

export interface MobileMenuProps {
  onToggle: () => void
  ariaLabel?: string
  /** @internal Slot for positioning */
  slot?: 'left' | 'right'
}

export const MobileMenu = React.memo(function MobileMenu({
  onToggle,
  ariaLabel = 'Toggle menu',
}: MobileMenuProps) {
  if (!onToggle) {
    return null
  }

  return (
    <button
      onClick={onToggle}
      className="lg:hidden p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg"
      aria-label={ariaLabel}
      type="button"
    >
      <Menu className="w-5 h-5" />
    </button>
  )
})

MobileMenu.displayName = 'AppHeader.MobileMenu'
