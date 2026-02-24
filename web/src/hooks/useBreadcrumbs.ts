/**
 * useBreadcrumbs Hook
 *
 * Generates breadcrumb navigation based on current route and context.
 *
 * @example
 * ```tsx
 * // Basic usage
 * const breadcrumbs = useBreadcrumbs('project')
 *
 * // With custom labels
 * const breadcrumbs = useBreadcrumbs('project', {
 *   labels: { 'custom-page': 'My Custom Page' }
 * })
 *
 * // With options
 * const breadcrumbs = useBreadcrumbs('project', {
 *   maxDepth: 3,
 *   hideLast: true,
 *   labels: { 'memories': 'Memory Bank' }
 * })
 * ```
 */

import { useParams, useLocation } from 'react-router-dom';

import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { useProjectStore } from '@/stores/project';

import type { Breadcrumb } from '@/config/navigation';

export type BreadcrumbContext = 'tenant' | 'project' | 'agent' | 'schema';

/**
 * Options for customizing breadcrumb behavior
 */
export interface BreadcrumbOptions {
  /** Custom label mapping for path segments */
  labels?: Record<string, string>;
  /** Maximum number of breadcrumbs to show (null for unlimited) */
  maxDepth?: number | null;
  /** Whether to make the last breadcrumb non-clickable (empty path) */
  hideLast?: boolean;
  /** Custom home breadcrumb label */
  homeLabel?: string;
}

/**
 * Generate breadcrumbs for the current page
 *
 * @param context - The layout context (tenant, project, agent, schema)
 * @param options - Optional configuration for breadcrumb behavior
 */
export function useBreadcrumbs(
  context: BreadcrumbContext,
  options?: BreadcrumbOptions
): Breadcrumb[] {
  const params = useParams();
  const location = useLocation();
  // Use selective selectors to prevent unnecessary re-renders
  const currentProject = useProjectStore((state) => state.currentProject);
  const currentConversation = useConversationsStore((state) => state.currentConversation);

  const {
    labels: customLabels = {},
    maxDepth = null,
    hideLast = false,
    homeLabel = 'Home',
  } = options || {};

  const { tenantId, projectId } = params;

  const breadcrumbs: Breadcrumb[] = [];
  // Remove trailing slash and split
  const cleanPath =
    location.pathname.endsWith('/') && location.pathname.length > 1
      ? location.pathname.slice(0, -1)
      : location.pathname;
  const paths = cleanPath.split('/').filter(Boolean);

  // Common base breadcrumb
  // Skip for root or /tenant path (entry points)
  const isRootPath = paths.length === 0;
  const isGenericTenantPath = context === 'tenant' && paths.length === 1 && paths[0] === 'tenant';
  if (!isRootPath && !isGenericTenantPath) {
    breadcrumbs.push({ label: homeLabel, path: '/tenant' });
  }

  if (context === 'tenant') {
    // Tenant-level breadcrumbs
    if (paths.length > 2) {
      const section = paths[2];
      // Handle special case for agent-workspace - show conversation name if available
      if (section === 'agent-workspace') {
        // Show conversation name if available, otherwise show 'Agent Workspace'
        const conversationName = currentConversation?.title || 'Agent Workspace';
        breadcrumbs.push({
          label: conversationName,
          path: `/tenant/${tenantId}/agent-workspace`,
        });
      } else {
        const label = getCustomLabel(section ?? '', customLabels) || formatBreadcrumbLabel(section ?? '');
        breadcrumbs.push({
          label,
          path: location.pathname,
        });
      }
    } else if (paths.length === 2) {
      // Specific tenant view - might need project context
      if (paths[0] === 'tenant' && projectId) {
        breadcrumbs.push({ label: 'Projects', path: `/tenant/${tenantId}/projects` });
      }
    }
  }

  if (context === 'project' || context === 'agent' || context === 'schema') {
    // Add "Projects" breadcrumb
    breadcrumbs.push({ label: 'Projects', path: '/tenant/projects' });

    // Add current project breadcrumb
    if (currentProject) {
      breadcrumbs.push({
        label: currentProject.name,
        path: `/project/${projectId}`,
      });
    } else if (projectId) {
      breadcrumbs.push({
        label: 'Project',
        path: `/project/${projectId}`,
      });
    }

    // Add page-specific breadcrumb
    if (context === 'project' && paths.length > 2) {
      const section = paths[2];
      const label = getCustomLabel(section ?? '', customLabels) || formatBreadcrumbLabel(section ?? '');
      breadcrumbs.push({
        label,
        path: location.pathname,
      });
    }

    // Agent context specific
    if (context === 'agent') {
      breadcrumbs.push({
        label: 'Agent',
        path: `/project/${projectId}/agent`,
      });

      // Add agent sub-page
      if (paths.length > 3) {
        const subPage = paths[3];
        const label = getCustomLabel(subPage ?? '', customLabels) || formatBreadcrumbLabel(subPage ?? '');
        breadcrumbs.push({
          label,
          path: location.pathname,
        });
      }
    }

    // Schema context specific
    if (context === 'schema' && paths.length > 3) {
      const subPage = paths[3];
      const label = getCustomLabel(subPage ?? '', customLabels) || formatBreadcrumbLabel(subPage ?? '');
      breadcrumbs.push({
        label: 'Schema',
        path: `/project/${projectId}/schema`,
      });
      breadcrumbs.push({
        label,
        path: location.pathname,
      });
    }
  }

  // Apply maxDepth limit
  let result = maxDepth && maxDepth > 0 ? breadcrumbs.slice(-maxDepth) : breadcrumbs;

  // Apply hideLast option
  if (hideLast && result.length > 0) {
    result = result.map((crumb, index) => ({
      ...crumb,
      path: index === result.length - 1 ? '' : crumb.path,
    }));
  }

  return result;
}

/**
 * Get custom label from options, or return null if not found
 */
function getCustomLabel(segment: string, customLabels: Record<string, string>): string | null {
  return customLabels[segment] || null;
}

/**
 * Format a URL segment into a readable label
 */
function formatBreadcrumbLabel(segment: string): string {
  // Handle kebab-case
  return segment
    .split('-')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}
