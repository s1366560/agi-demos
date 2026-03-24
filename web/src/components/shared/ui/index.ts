/**
 * Shared UI Components Barrel Export
 *
 * Generic UI components used across the application.
 */

// ============================================================================
// Design System Components
// ============================================================================

// Status Badge - Reusable status indicators
export { StatusBadge } from './StatusBadge';
export type { StatusBadgeProps, StatusBadgeStatus } from './StatusBadge';

// State Display - Loading/Empty/Error states compound component
export { StateDisplay } from './StateDisplay';
export type {
  StateLoadingProps,
  StateEmptyProps,
  StateErrorProps,
} from './StateDisplay';

// Empty State Variants - Flexible empty state with simple and cards variants
export { EmptyStateVariant, EmptyStateSimple, EmptyStateCards } from './EmptyStateVariant';
export type {
  EmptyStateVariantProps,
  EmptyStateSimpleProps,
  EmptyStateCardsProps,
  SuggestionCard,
} from './EmptyStateVariant';

// ============================================================================
// Navigation Components
// ============================================================================

export { LanguageSwitcher } from './LanguageSwitcher';
export { NotificationPanel } from './NotificationPanel';
export { ThemeToggle } from './ThemeToggle';

// WorkspaceSwitcher compound components
export {
  WorkspaceSwitcherRoot,
  WorkspaceSwitcherTrigger,
  WorkspaceSwitcherMenu,
  TenantWorkspaceSwitcher,
  ProjectWorkspaceSwitcher,
  TenantList,
  ProjectList,
  WorkspaceSwitcher as WorkspaceSwitcherCompound,
} from './WorkspaceSwitcher';

// Legacy WorkspaceSwitcher - exports the original for backward compatibility
export { WorkspaceSwitcher } from './WorkspaceSwitcher';
