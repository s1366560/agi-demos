/**
 * Shared Components Barrel Export
 *
 * Components that are shared across multiple contexts (tenant, project, graph).
 * These components are not domain-specific and can be used anywhere in the app.
 *
 * Sub-categories:
 * - layouts: Layout components (AppLayout, ResponsiveLayout, Layout)
 * - modals: Reusable modal components (DeleteConfirmationModal)
 * - ui: Generic UI components (LanguageSwitcher, NotificationPanel, ThemeToggle, WorkspaceSwitcher)
 */

// Layout components
export { AppLayout, ResponsiveLayout, Layout } from './layouts';

// Modal components
export { DeleteConfirmationModal } from './modals';

// UI components
export { LanguageSwitcher, NotificationPanel, ThemeToggle, WorkspaceSwitcher } from './ui';
