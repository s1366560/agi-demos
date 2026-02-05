/**
 * AppHeader.Notifications - Compound Component
 *
 * Notification bell with badge count.
 */

import * as React from 'react'

import { Bell } from 'lucide-react'

export interface NotificationsProps {
  count?: number
  onClick?: () => void
  ariaLabel?: string
}

export const Notifications = React.memo(function Notifications({
  count = 0,
  onClick,
  ariaLabel = 'Notifications',
}: NotificationsProps) {
  return (
    <button
      onClick={onClick}
      className="relative p-2 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors"
      aria-label={ariaLabel}
      type="button"
    >
      <Bell className="w-5 h-5" />
      {count > 0 && (
        <span className="absolute top-2 right-2 size-2 bg-red-500 rounded-full border-2 border-white dark:border-surface-dark" />
      )}
    </button>
  )
})

Notifications.displayName = 'AppHeader.Notifications'
