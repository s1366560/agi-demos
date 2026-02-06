/**
 * AppSidebar Component (Refactored)
 *
 * Main sidebar component supporting both explicit variant components
 * and backward compatibility with the legacy context prop.
 */

import * as React from 'react';
import { useState, useCallback } from 'react';

import { SidebarBrand } from './SidebarBrand';
import { SidebarProvider, useSidebarContext } from './SidebarContext';
import { SidebarNavigation } from './SidebarNavigation';
import { SidebarUser } from './SidebarUser';

import type { AppSidebarProps, SidebarVariant } from './types';
import type { SidebarConfig } from '@/config/navigation';

/**
 * Collapse toggle button component
 */
function CollapseToggleButton() {
  const { isCollapsed, onCollapseToggle } = useSidebarContext();

  return (
    <button
      onClick={onCollapseToggle}
      data-testid="collapse-toggle"
      className="absolute top-20 -right-3 w-6 h-6 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-full flex items-center justify-center shadow-sm hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors z-30"
      title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
    >
      <svg className="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        {isCollapsed ? (
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        ) : (
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        )}
      </svg>
    </button>
  );
}

/**
 * Main sidebar content component
 */
function SidebarContent({
  config,
  variant,
  brand,
  user,
  onLogout,
}: {
  config: SidebarConfig;
  variant?: SidebarVariant;
  brand?: React.ReactNode;
  user?: { name: string; email: string };
  onLogout?: () => void;
}) {
  const { isCollapsed } = useSidebarContext();

  return (
    <aside
      data-testid="app-sidebar"
      className={`flex flex-col bg-surface-light dark:bg-surface-dark border-r border-slate-200 dark:border-border-dark flex-none z-20 transition-all duration-300 ease-in-out relative ${
        isCollapsed ? 'collapsed w-20' : 'w-64'
      }`}
      style={{
        width: isCollapsed ? `${config.collapsedWidth ?? 80}px` : `${config.width ?? 256}px`,
      }}
    >
      {/* Brand Header */}
      <div className="h-16 flex items-center px-4 border-b border-slate-100 dark:border-slate-800/50 shrink-0">
        {isCollapsed ? (
          <div className="w-full flex justify-center">
            <div className="bg-primary/10 p-2 rounded-lg border border-primary/20">
              <span className="material-symbols-outlined text-primary">memory</span>
            </div>
          </div>
        ) : (
          (brand ?? <SidebarBrand variant={variant} />)
        )}
      </div>

      {/* Navigation */}
      <SidebarNavigation config={config} />

      {/* User Profile */}
      {config.showUser && user && <SidebarUser user={user} onLogout={onLogout} />}

      {/* Collapse Toggle Button */}
      <CollapseToggleButton />
    </aside>
  );
}

/**
 * Main AppSidebar component
 *
 * Supports:
 * 1. New variant prop for explicit variant specification
 * 2. Legacy context prop for backward compatibility
 * 3. Compound components pattern via children
 */
export function AppSidebar({
  config,
  basePath,
  variant,
  context,
  collapsed: controlledCollapsed,
  defaultCollapsed = false,
  onCollapseToggle,
  user,
  onLogout,
  openGroups: controlledOpenGroups,
  onGroupToggle,
  brand,
  t = (key: string) => key,
  children,
}: AppSidebarProps & { children?: React.ReactNode }) {
  // Use variant prop, fall back to context prop for backward compatibility
  const sidebarVariant: SidebarVariant = variant ?? context ?? 'tenant';

  // Internal state for uncontrolled mode
  const [internalCollapsed, setInternalCollapsed] = useState(defaultCollapsed);
  const [internalOpenGroups, setInternalOpenGroups] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    config.groups.forEach((group) => {
      if (group.defaultOpen !== undefined) {
        initial[group.id] = group.defaultOpen;
      }
    });
    return initial;
  });

  // Determine collapsed state (controlled vs uncontrolled)
  const isCollapsed = controlledCollapsed ?? internalCollapsed;

  // Determine open groups state (controlled vs uncontrolled)
  const isOpenGroups = controlledOpenGroups ?? internalOpenGroups;

  // Handle collapse toggle
  const handleCollapseToggle = useCallback(() => {
    if (onCollapseToggle) {
      onCollapseToggle();
    } else {
      setInternalCollapsed(!isCollapsed);
    }
  }, [isCollapsed, onCollapseToggle]);

  // Handle group toggle
  const handleGroupToggle = useCallback(
    (groupId: string) => {
      if (onGroupToggle) {
        onGroupToggle(groupId);
      } else {
        setInternalOpenGroups((prev) => ({ ...prev, [groupId]: !prev[groupId] }));
      }
    },
    [onGroupToggle]
  );

  // Context value
  const contextValue = {
    isCollapsed,
    onCollapseToggle: handleCollapseToggle,
    openGroups: isOpenGroups,
    onGroupToggle: handleGroupToggle,
    user,
    onLogout,
    t,
    basePath,
  };

  return (
    <SidebarProvider value={contextValue}>
      {children ?? (
        <SidebarContent
          config={config}
          variant={sidebarVariant}
          brand={brand}
          user={user}
          onLogout={onLogout}
        />
      )}
    </SidebarProvider>
  );
}

export default AppSidebar;
