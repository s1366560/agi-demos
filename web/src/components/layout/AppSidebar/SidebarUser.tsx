/**
 * SidebarUser Component
 *
 * User profile section with avatar, name, email, and logout button.
 */

import { useSidebarContext } from './SidebarContext'
import type { NavUser } from '@/config/navigation'

export interface SidebarUserProps {
  /** User information */
  user: NavUser
  /** Callback when user logs out */
  onLogout?: () => void
}

/**
 * SidebarUser component - displays user profile section
 */
export function SidebarUser({ user, onLogout }: SidebarUserProps) {
  const { isCollapsed } = useSidebarContext()

  return (
    <div className="p-3 border-t border-slate-100 dark:border-slate-800">
      <div
        className={`flex items-center gap-3 p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700/50 group ${
          isCollapsed ? 'justify-center' : ''
        }`}
      >
        {/* Avatar */}
        <div className="size-8 rounded-full bg-gradient-to-br from-primary to-primary-light flex items-center justify-center text-xs font-bold text-white shrink-0 shadow-sm">
          {user.name?.[0]?.toUpperCase() || 'U'}
        </div>

        {/* User info */}
        {!isCollapsed && (
          <>
            <div className="flex flex-col overflow-hidden min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-900 dark:text-white truncate">
                {user.name}
              </p>
              <p className="text-xs text-slate-500 truncate">{user.email}</p>
            </div>
          </>
        )}

        {/* Logout button */}
        {onLogout && !isCollapsed && (
          <button
            onClick={onLogout}
            className="p-1.5 text-slate-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md transition-colors opacity-0 group-hover:opacity-100"
            title="Sign out"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
          </button>
        )}
      </div>
    </div>
  )
}
