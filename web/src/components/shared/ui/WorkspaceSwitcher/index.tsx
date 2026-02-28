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
import { WorkspaceSwitcher as LegacyWorkspaceSwitcher } from '../WorkspaceSwitcher.legacy';

import { WorkspaceSwitcherMenu } from './Menu';
import { ProjectList } from './ProjectList';
import { TenantList } from './TenantList';
import { WorkspaceSwitcherTrigger } from './Trigger';
import { WorkspaceSwitcherRoot } from './WorkspaceSwitcherRoot';

// Then export them
export { WorkspaceSwitcherRoot } from './WorkspaceSwitcherRoot';
export { WorkspaceSwitcherTrigger } from './Trigger';
export { WorkspaceSwitcherMenu } from './Menu';
export { TenantList } from './TenantList';
export { ProjectList } from './ProjectList';

// Re-export convenience components
export { TenantWorkspaceSwitcher } from './TenantWorkspaceSwitcher';
export { ProjectWorkspaceSwitcher } from './ProjectWorkspaceSwitcher';

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
} from './types';

// Compound components namespace for structured imports

// eslint-disable-next-line react-refresh/only-export-components
export const WorkspaceSwitcherNamespace = {
  Root: WorkspaceSwitcherRoot,
  Trigger: WorkspaceSwitcherTrigger,
  Menu: WorkspaceSwitcherMenu,
  TenantList,
  ProjectList,
};

// Legacy WorkspaceSwitcher - exported for backward compatibility
// @deprecated Use TenantWorkspaceSwitcher or ProjectWorkspaceSwitcher instead.
export const WorkspaceSwitcherLegacy = LegacyWorkspaceSwitcher;

// Main export for backward compatibility - redirects to original implementation
// @deprecated Use TenantWorkspaceSwitcher or ProjectWorkspaceSwitcher instead.
export const WorkspaceSwitcher = LegacyWorkspaceSwitcher;
