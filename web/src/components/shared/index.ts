/**
 * Shared Components Barrel Export
 *
 * Components that are shared across multiple contexts (tenant, project, graph).
 * These components are not domain-specific and can be used anywhere in the app.
 *
 * Sub-categories:
 * - modals: Reusable modal components (DeleteConfirmationModal)
 * - ui: Generic UI components (design system, navigation, workspace)
 */

// Modal components
export { DeleteConfirmationModal } from './modals';

// Design System Components
export {
  // Status indicators
  StatusBadge,
  // State display
  StateDisplay,
  // Empty states
  EmptyStateVariant,
  EmptyStateSimple,
  EmptyStateCards,
  // Navigation
  LanguageSwitcher,
  NotificationPanel,
  ThemeToggle,
  WorkspaceSwitcher,
} from './ui';

// Type exports for design system
export type {
  StatusBadgeProps,
  StatusBadgeStatus,
  StateLoadingProps,
  StateEmptyProps,
  StateErrorProps,
  EmptyStateVariantProps,
  EmptyStateSimpleProps,
  EmptyStateCardsProps,
  SuggestionCard,
} from './ui';
