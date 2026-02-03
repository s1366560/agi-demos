/**
 * WorkspaceSwitcher - Compound Component for Workspace Switching
 *
 * A flexible compound component pattern for switching between tenants and projects.
 *
 * ## Usage
 *
 * ### Convenience Components (Recommended)
 * ```tsx
 * <TenantWorkspaceSwitcher />
 * <ProjectWorkspaceSwitcher />
 * ```
 *
 * ### Compound Components (Advanced Customization)
 * ```tsx
 * <WorkspaceSwitcherRoot mode="tenant">
 *   <WorkspaceSwitcherTrigger>
 *     <CustomTriggerContent />
 *   </WorkspaceSwitcherTrigger>
 *   <WorkspaceSwitcherMenu label="Switch Tenant">
 *     <TenantList tenants={tenants} ... />
 *   </WorkspaceSwitcherMenu>
 * </WorkspaceSwitcherRoot>
 * ```
 *
 * ### Backward Compatible API
 * ```tsx
 * <WorkspaceSwitcher mode="tenant" />
 * <WorkspaceSwitcher mode="project" />
 * ```
 */

// First, import all components
import { WorkspaceSwitcherRoot } from './WorkspaceSwitcherRoot'
import { WorkspaceSwitcherTrigger } from './Trigger'
import { WorkspaceSwitcherMenu } from './Menu'
import { TenantList } from './TenantList'
import { ProjectList } from './ProjectList'
import { TenantWorkspaceSwitcher } from './TenantWorkspaceSwitcher'
import { ProjectWorkspaceSwitcher } from './ProjectWorkspaceSwitcher'
import { WorkspaceProvider, useWorkspaceContext } from './WorkspaceContext'
import { WorkspaceSwitcher as LegacyWorkspaceSwitcher } from '../WorkspaceSwitcher.legacy'

// Then export them
export { WorkspaceSwitcherRoot } from './WorkspaceSwitcherRoot'
export { WorkspaceSwitcherTrigger } from './Trigger'
export { WorkspaceSwitcherMenu } from './Menu'
export { TenantList } from './TenantList'
export { ProjectList } from './ProjectList'
export { TenantWorkspaceSwitcher } from './TenantWorkspaceSwitcher'
export { ProjectWorkspaceSwitcher } from './ProjectWorkspaceSwitcher'
export { WorkspaceProvider, useWorkspaceContext } from './WorkspaceContext'

// Re-export types
export type {
  WorkspaceMode,
  KeyboardEventHandler,
  KeyboardKey,
  WorkspaceContextValue,
  WorkspaceSwitcherRootProps,
  WorkspaceTriggerProps,
  WorkspaceMenuProps,
  TenantListProps,
  ProjectListProps,
  TenantWorkspaceSwitcherProps,
  ProjectWorkspaceSwitcherProps,
  LegacyWorkspaceSwitcherProps,
  MenuItemState,
} from './types'

// Compound components namespace for structured imports
export const WorkspaceSwitcherNamespace = {
  Root: WorkspaceSwitcherRoot,
  Trigger: WorkspaceSwitcherTrigger,
  Menu: WorkspaceSwitcherMenu,
  TenantList,
  ProjectList,
}

// Legacy WorkspaceSwitcher - exported for backward compatibility
// @deprecated Use TenantWorkspaceSwitcher or ProjectWorkspaceSwitcher instead.
export { LegacyWorkspaceSwitcher as WorkspaceSwitcherLegacy }

// Main export for backward compatibility - redirects to original implementation
// @deprecated Use TenantWorkspaceSwitcher or ProjectWorkspaceSwitcher instead.
export const WorkspaceSwitcher = LegacyWorkspaceSwitcher
