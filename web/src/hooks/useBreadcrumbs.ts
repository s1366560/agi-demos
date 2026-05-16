/**
 * useBreadcrumbs Hook
 *
 * Generates breadcrumb navigation based on the current route and canonical
 * navigation derivation helpers.
 */

import { useLocation, useParams } from 'react-router-dom';

import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { useProjectStore } from '@/stores/project';

import {
  getCanonicalAgentPath,
  getCanonicalAgentWorkspacePath,
  getCanonicalProjectPath,
  getCanonicalTenantDestinationPath,
  getCanonicalTenantPath,
  parseNavigationPath,
} from '@/config/navigation';

import type { Breadcrumb } from '@/config/navigation';

export type BreadcrumbContext = 'tenant' | 'project' | 'agent' | 'schema';

/**
 * Options for customizing breadcrumb behavior
 */
export interface BreadcrumbOptions {
  /** Custom label mapping for path segments */
  labels?: Record<string, string> | undefined;
  /** Maximum number of breadcrumbs to show (null for unlimited) */
  maxDepth?: number | null | undefined;
  /** Whether to make the last breadcrumb non-clickable (empty path) */
  hideLast?: boolean | undefined;
  /** Custom home breadcrumb label */
  homeLabel?: string | undefined;
}

function getCustomLabel(segment: string, customLabels: Record<string, string>): string | null {
  return customLabels[segment] || null;
}

function formatBreadcrumbLabel(segment: string): string {
  return segment
    .split('-')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function getSegmentLabel(
  segment: string | undefined,
  customLabels: Record<string, string>
): string {
  const safeSegment = segment ?? '';
  return getCustomLabel(safeSegment, customLabels) || formatBreadcrumbLabel(safeSegment);
}

/**
 * Generate breadcrumbs for the current page.
 */
export function useBreadcrumbs(
  context: BreadcrumbContext,
  options?: BreadcrumbOptions
): Breadcrumb[] {
  const params = useParams();
  const location = useLocation();
  const currentProject = useProjectStore((state) => state.currentProject);
  const currentConversation = useConversationsStore((state) => state.currentConversation);

  const {
    labels: customLabels = {},
    maxDepth = null,
    hideLast = false,
    homeLabel = 'Home',
  } = options || {};

  const parsedPath = parseNavigationPath(location.pathname);
  const tenantId = params.tenantId ?? parsedPath.tenantId;
  const projectId = params.projectId ?? parsedPath.projectId;
  const homePath = getCanonicalTenantPath();
  const tenantProjectsPath = getCanonicalTenantDestinationPath(tenantId, '/projects');
  const projectBasePath = getCanonicalProjectPath({ tenantId, projectId });
  const agentBasePath = getCanonicalAgentPath({ tenantId, projectId });

  const breadcrumbs: Breadcrumb[] = [];
  const isRootPath = parsedPath.normalizedPath === homePath;

  if (context === 'tenant') {
    if (isRootPath) {
      return [];
    }

    breadcrumbs.push({ label: homeLabel, path: homePath });

    if (parsedPath.family === 'agent-workspace') {
      const conversationLabel = currentConversation?.title || 'Agent Workspace';
      breadcrumbs.push({
        label: conversationLabel,
        path: getCanonicalAgentWorkspacePath({
          tenantId,
          conversationId: parsedPath.conversationId,
        }),
      });
    } else if (parsedPath.section) {
      breadcrumbs.push({
        label: getSegmentLabel(parsedPath.section, customLabels),
        path: getCanonicalTenantDestinationPath(tenantId, `/${parsedPath.section}`),
      });
    }
  }

  if (context === 'project' || context === 'agent' || context === 'schema') {
    breadcrumbs.push({ label: homeLabel, path: homePath });
    breadcrumbs.push({ label: 'Projects', path: tenantProjectsPath });

    breadcrumbs.push({
      label: currentProject?.name || 'Project',
      path: projectBasePath,
    });

    if (context === 'project') {
      if (parsedPath.section && parsedPath.section !== 'agent' && parsedPath.section !== 'schema') {
        breadcrumbs.push({
          label: getSegmentLabel(parsedPath.section, customLabels),
          path: getCanonicalProjectPath({
            tenantId,
            projectId,
            path: `/${parsedPath.section}`,
          }),
        });
      }
    }

    if (context === 'agent') {
      breadcrumbs.push({
        label: 'Agent',
        path: agentBasePath,
      });

      const agentSubPage =
        parsedPath.section === 'agent' ? parsedPath.subSection : parsedPath.section;

      if (agentSubPage) {
        breadcrumbs.push({
          label: getSegmentLabel(agentSubPage, customLabels),
          path: getCanonicalAgentPath({
            tenantId,
            projectId,
            path: agentSubPage,
          }),
        });
      }
    }

    if (context === 'schema') {
      const schemaBasePath = getCanonicalProjectPath({
        tenantId,
        projectId,
        path: '/schema',
      });

      breadcrumbs.push({
        label: 'Schema',
        path: schemaBasePath,
      });

      const schemaSubPage = parsedPath.section === 'schema' ? parsedPath.subSection : undefined;
      if (schemaSubPage) {
        breadcrumbs.push({
          label: getSegmentLabel(schemaSubPage, customLabels),
          path: getCanonicalProjectPath({
            tenantId,
            projectId,
            path: `/schema/${schemaSubPage}`,
          }),
        });
      }
    }
  }

  let result = maxDepth && maxDepth > 0 ? breadcrumbs.slice(-maxDepth) : breadcrumbs;

  if (hideLast && result.length > 0) {
    result = result.map((crumb, index) => ({
      ...crumb,
      path: index === result.length - 1 ? '' : crumb.path,
    }));
  }

  return result;
}
