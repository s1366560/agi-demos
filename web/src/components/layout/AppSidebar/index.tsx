/**
 * AppSidebar Module Exports
 *
 * Exports all sidebar components following the explicit variant pattern.
 * Replaces the context-prop switching with clear, type-safe components.
 */

// Main component
export { AppSidebar } from './AppSidebar';
export type { AppSidebarProps } from './types';

// Explicit variant components
export { TenantSidebar } from './TenantSidebar';
export type { TenantSidebarProps } from './types';

export { ProjectSidebar } from './ProjectSidebar';
export type { ProjectSidebarProps } from './types';

export { AgentSidebar } from './AgentSidebar';
export type { AgentSidebarProps } from './types';

// Compound components
export { SidebarBrand } from './SidebarBrand';
export type { SidebarBrandProps } from './SidebarBrand';

export { SidebarNavigation } from './SidebarNavigation';

export { SidebarUser } from './SidebarUser';
export type { SidebarUserProps } from './SidebarUser';

export { SidebarNavItem } from './SidebarNavItem';
export type { SidebarNavItemProps } from './SidebarNavItem';

// Context and hooks
export { SidebarContext, SidebarProvider, useSidebarContext } from './SidebarContext';

// Types
export type { SidebarVariant, BaseSidebarProps } from './types';
