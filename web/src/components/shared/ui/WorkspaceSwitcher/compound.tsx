/**
 * Compound Components exports
 *
 * This file exports compound components without importing the legacy WorkspaceSwitcher
 * to avoid circular dependencies.
 */

// Export compound components
export { WorkspaceSwitcherRoot } from './WorkspaceSwitcherRoot'
export { WorkspaceSwitcherTrigger } from './Trigger'
export { WorkspaceSwitcherMenu } from './Menu'
export { TenantList } from './TenantList'
export { ProjectList } from './ProjectList'
