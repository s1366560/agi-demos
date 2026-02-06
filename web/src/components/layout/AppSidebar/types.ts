/**
 * AppSidebar Types
 *
 * Type definitions for the refactored AppSidebar component system.
 * Uses explicit variant components instead of context prop switching.
 */

import type { SidebarConfig, NavUser } from '@/config/navigation';

/**
 * Sidebar variant type - explicit instead of context prop
 */
export type SidebarVariant = 'tenant' | 'project' | 'agent';

/**
 * Common props shared across all sidebar components
 */
export interface BaseSidebarProps {
  /** Base path for generating links */
  basePath: string;
  /** Current collapsed state (controlled) */
  collapsed?: boolean;
  /** Default collapsed state */
  defaultCollapsed?: boolean;
  /** Callback when collapse state changes */
  onCollapseToggle?: () => void;
  /** User information for profile section */
  user?: NavUser;
  /** Callback when user logs out */
  onLogout?: () => void;
  /** Currently open groups (controlled) */
  openGroups?: Record<string, boolean>;
  /** Callback when group is toggled */
  onGroupToggle?: (groupId: string) => void;
  /** Translation function for labels */
  t?: (key: string) => string;
}

/**
 * Props for the generic AppSidebar with variant prop
 * Maintains backward compatibility with existing code
 */
export interface AppSidebarProps extends BaseSidebarProps {
  /** Sidebar configuration from navigation.ts */
  config: SidebarConfig;
  /** Variant type (for backward compatibility, use explicit components instead) */
  variant?: SidebarVariant;
  /** Brand element to display in header */
  brand?: React.ReactNode;
  /** @deprecated Use variant prop or explicit variant components */
  context?: SidebarVariant;
}

/**
 * Props for TenantSidebar variant component
 */
export interface TenantSidebarProps extends Omit<BaseSidebarProps, 'basePath'> {
  /** Current tenant ID for path generation */
  tenantId?: string;
}

/**
 * Props for ProjectSidebar variant component
 */
export interface ProjectSidebarProps extends Omit<BaseSidebarProps, 'basePath'> {
  /** Current project ID for path generation */
  projectId?: string;
}

/**
 * Props for AgentSidebar variant component
 */
export interface AgentSidebarProps extends Omit<BaseSidebarProps, 'basePath'> {
  /** Current project ID for navigation */
  projectId?: string;
  /** Current conversation ID for navigation */
  conversationId?: string;
}

/**
 * Props for Sidebar compound components
 */
export interface SidebarBrandProps {
  /** Variant to determine branding */
  variant?: SidebarVariant;
  /** Custom brand element */
  children?: React.ReactNode;
}

export interface SidebarNavigationProps {
  /** Navigation configuration */
  config: SidebarConfig;
  /** Base path for links */
  basePath: string;
}

export interface SidebarUserProps {
  /** User information */
  user: NavUser;
  /** Callback when user logs out */
  onLogout?: () => void;
}
