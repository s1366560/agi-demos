/**
 * Sidebar Context
 *
 * Shared context for compound components pattern.
 * Provides collapse state and callbacks to child components.
 */

import * as React from 'react';

import type { NavUser } from '@/config/navigation';

export interface SidebarContextValue {
  /** Current collapsed state */
  isCollapsed: boolean;
  /** Callback to toggle collapse */
  onCollapseToggle: () => void;
  /** Open groups state */
  openGroups: Record<string, boolean>;
  /** Callback to toggle group */
  onGroupToggle: (groupId: string) => void;
  /** User information */
  user?: NavUser | undefined;
  /** Callback when user logs out */
  onLogout?: (() => void) | undefined;
  /** Translation function */
  t: (key: string) => string;
  /** Base path for navigation */
  basePath: string;
}

 
// eslint-disable-next-line react-refresh/only-export-components
export const SidebarContext = React.createContext<SidebarContextValue | null>(null);

/**
 * Hook to access sidebar context
 * Throws error if used outside of SidebarProvider
// eslint-disable-next-line react-refresh/only-export-components
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useSidebarContext(): SidebarContextValue {
  const context = React.useContext(SidebarContext);
  if (!context) {
    throw new Error('useSidebarContext must be used within a Sidebar component');
  }
  return context;
}

/**
 * Provider component for sidebar context
 */
export function SidebarProvider({
  children,
  value,
}: {
  children: React.ReactNode;
  value: SidebarContextValue;
}) {
  return <SidebarContext.Provider value={value}>{children}</SidebarContext.Provider>;
}
