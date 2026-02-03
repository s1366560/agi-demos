/**
 * WorkspaceSwitcher Component Types
 *
 * Defines the type system for the compound WorkspaceSwitcher component.
 */

import type { Tenant, Project } from '@/types/memory'

/**
 * Workspace mode - determines which entity type to switch between
 */
export type WorkspaceMode = 'tenant' | 'project'

/**
 * Keyboard navigation keys
 */
export type KeyboardKey =
  | 'ArrowDown'
  | 'ArrowUp'
  | 'ArrowLeft'
  | 'ArrowRight'
  | 'Home'
  | 'End'
  | 'Enter'
  | ' '
  | 'Escape'
  | 'Tab'

/**
 * Workspace context state shared across compound components
 */
export interface WorkspaceContextValue {
  mode: WorkspaceMode
  isOpen: boolean
  setIsOpen: (open: boolean) => void
  focusedIndex: number
  setFocusedIndex: (index: number) => void
  menuItemsCount: number
  setMenuItemsCount: (count: number) => void
  registerMenuItemRef: (index: number, ref: HTMLButtonElement | null) => void
  getMenuItemRef: (index: number) => HTMLButtonElement | null
  triggerButtonRef: React.RefObject<HTMLButtonElement>
}

/**
 * Props for the root WorkspaceSwitcher component
 */
export interface WorkspaceSwitcherRootProps {
  children: React.ReactNode
  mode?: WorkspaceMode
  defaultOpen?: boolean
  onOpenChange?: (open: boolean) => void
}

/**
 * Props for the Trigger component
 */
export interface WorkspaceTriggerProps {
  className?: string
  children?: React.ReactNode
}

/**
 * Props for the Menu component
 */
export interface WorkspaceMenuProps {
  className?: string
  children: React.ReactNode
  label: string
}

/**
 * Props for TenantList component
 */
export interface TenantListProps {
  tenants: Tenant[]
  currentTenant: Tenant | null
  onTenantSelect: (tenant: Tenant) => void
  onCreateTenant?: () => void
  createLabel?: string
}

/**
 * Props for ProjectList component
 */
export interface ProjectListProps {
  projects: Project[]
  currentProjectId: string | null
  onProjectSelect: (project: Project) => void
  onBackToTenant?: () => void
  backToTenantLabel?: string
}

/**
 * Props for the TenantWorkspaceSwitcher convenience component
 */
export interface TenantWorkspaceSwitcherProps {
  onTenantSelect?: (tenant: Tenant) => void
  onCreateTenant?: () => void
  createLabel?: string
  triggerClassName?: string
  menuClassName?: string
}

/**
 * Props for the ProjectWorkspaceSwitcher convenience component
 */
export interface ProjectWorkspaceSwitcherProps {
  currentProjectId?: string | null
  onProjectSelect?: (project: Project) => void
  onBackToTenant?: () => void
  backToTenantLabel?: string
  triggerClassName?: string
  menuClassName?: string
}

/**
 * Props for backward compatibility with the original WorkspaceSwitcher
 */
export interface LegacyWorkspaceSwitcherProps {
  mode: WorkspaceMode
}

/**
 * Keyboard event handler type
 */
export type KeyboardEventHandler = (
  event: React.KeyboardEvent,
  index?: number
) => void

/**
 * Menu item state for keyboard navigation
 */
export interface MenuItemState {
  ref: HTMLButtonElement | null
  focused: boolean
  disabled?: boolean
}
