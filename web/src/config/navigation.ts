/**
 * Navigation Configuration - Types, path derivation, and canonical navigation outputs.
 *
 * This module keeps legacy sidebar config compatibility while introducing a
 * derivation-based canonical navigation model for top-nav and helper consumers.
 */

/**
 * User information for display in navigation
 */
export interface NavUser {
  name: string;
  email: string;
  avatar?: string | undefined;
}

/**
 * Navigation item configuration
 *
 * @property id - Unique identifier for the nav item
 * @property icon - Material Symbols icon name
 * @property label - i18n key (e.g., "nav.overview") or direct label
 * @property path - Relative path from the layout base
 * @property exact - Match exact path (default: false)
 * @property badge - Optional badge number to display
 * @property permission - Optional permission key for access control
 * @property hidden - Whether to hide this item (default: false)
 * @property disabled - Whether to disable this item (default: false)
 */
export interface NavItem {
  id: string;
  icon: string;
  label: string;
  path: string;
  exact?: boolean | undefined;
  badge?: number | undefined;
  permission?: string | undefined;
  hidden?: boolean | undefined;
  disabled?: boolean | undefined;
}

/**
 * Navigation group for organizing items
 *
 * @property id - Unique identifier for the group
 * @property title - i18n key for group title
 * @property items - Navigation items in this group
 * @property collapsible - Whether group can be collapsed
 * @property defaultOpen - Initial open state (default: true)
 */
export interface NavGroup {
  id: string;
  title: string;
  items: NavItem[];
  collapsible?: boolean | undefined;
  defaultOpen?: boolean | undefined;
}

/**
 * Tab item for top tab navigation
 *
 * @property id - Unique identifier
 * @property label - Display label or i18n key
 * @property path - Relative path
 * @property icon - Optional icon name
 */
export interface TabItem {
  id: string;
  label: string;
  path: string;
  icon?: string | undefined;
}

/**
 * Breadcrumb item
 *
 * @property label - Display label
 * @property path - Full path (empty for current page)
 */
export interface Breadcrumb {
  label: string;
  path: string;
}

/**
 * Sidebar configuration
 *
 * @property groups - Navigation groups
 * @property bottom - Bottom section navigation items
 * @property showUser - Whether to show user profile section
 * @property width - Expanded width in pixels
 * @property collapsedWidth - Collapsed width in pixels
 */
export interface SidebarConfig {
  groups: NavGroup[];
  bottom?: NavItem[] | undefined;
  showUser?: boolean | undefined;
  width?: number | undefined;
  collapsedWidth?: number | undefined;
}

/**
 * Layout type enumeration
 */
export type LayoutType = 'tenant' | 'project' | 'agent' | 'schema';

/**
 * Explicit canonical route families used by the derivation layer.
 */
export type RouteFamily =
  | 'landing'
  | 'tenant'
  | 'agent-workspace'
  | 'project'
  | 'project-blackboard-dynamic';

/**
 * Contexts that can request top-level functional navigation.
 */
export type TopNavigationContext = 'tenant' | 'project' | 'agent';

/**
 * Display-role metadata for derived navigation items.
 */
export type NavigationDisplayRole = 'top-nav' | 'overflow' | 'breadcrumb-visible';

/**
 * Logical group ids for contextual navigation presentation.
 */
export type NavigationGroupId =
  | 'tenant-core-operations'
  | 'tenant-agent-building'
  | 'tenant-extensions-integrations'
  | 'tenant-runtime-infrastructure'
  | 'tenant-governance-management'
  | 'project-workspace'
  | 'project-knowledge-base'
  | 'project-discovery'
  | 'project-configuration';

interface NavigationGroupDefinition {
  id: NavigationGroupId;
  label: string;
}

/**
 * Runtime inputs for canonical path derivation.
 */
export interface NavigationRuntimeContext {
  tenantId?: string | undefined;
  projectId?: string | undefined;
  conversationId?: string | undefined;
  preferredWorkspaceId?: string | null | undefined;
}

export interface DeriveTopNavigationOptions extends NavigationRuntimeContext {
  currentContext: TopNavigationContext;
}

/**
 * Rich navigation output derived from the canonical registry.
 */
export interface DerivedNavigationItem extends TabItem {
  context: TopNavigationContext;
  displayRole: NavigationDisplayRole;
  exact?: boolean | undefined;
  groupId?: NavigationGroupId | undefined;
  groupLabel?: string | undefined;
  relativePath: string;
  routeFamily: RouteFamily;
}

/**
 * Parsed route details for helpers such as breadcrumbs and active-state checks.
 */
export interface ParsedNavigationPath {
  family: RouteFamily;
  isLegacyAlias: boolean;
  normalizedPath: string;
  projectId?: string | undefined;
  section?: string | undefined;
  segments: string[];
  subSection?: string | undefined;
  tenantId?: string | undefined;
  conversationId?: string | undefined;
}

/**
 * Navigation configuration per layout
 */
export interface NavConfig {
  tenant: {
    sidebar: SidebarConfig;
  };
  project: {
    sidebar: SidebarConfig;
  };
  agent: {
    sidebar: SidebarConfig;
    tabs: TabItem[];
  };
  schema: {
    tabs: TabItem[];
  };
}

/**
 * Navigation state managed by stores
 */
export interface NavigationState {
  sidebarCollapsed: boolean;
  activeGroup: Record<string, boolean>;
}

/**
 * Props for navigation context
 */
export interface NavigationContextValue {
  state: NavigationState;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleGroup: (groupId: string) => void;
  setGroupOpen: (groupId: string, open: boolean) => void;
}

interface CanonicalDestinationDefinition {
  id: string;
  label: string;
  routeFamily: RouteFamily;
  contexts: readonly TopNavigationContext[];
  displayRole: NavigationDisplayRole;
  exact?: boolean | undefined;
  groupId: NavigationGroupId;
  relativePath: string;
  buildPath: (context: NavigationRuntimeContext) => string;
}

const LANDING_PATH = '/tenant';
const PROJECT_DISCOVERY_PATH = '/tenant/projects';
const CANONICAL_ABSOLUTE_PREFIXES = ['/tenant', '/project'];
const TENANT_AUXILIARY_CONTENT_SECTIONS = ['profile'] as const;

const NAVIGATION_GROUPS: Record<NavigationGroupId, NavigationGroupDefinition> = {
  'tenant-core-operations': {
    id: 'tenant-core-operations',
    label: 'nav.coreOperations',
  },
  'tenant-agent-building': {
    id: 'tenant-agent-building',
    label: 'nav.agentBuilding',
  },
  'tenant-extensions-integrations': {
    id: 'tenant-extensions-integrations',
    label: 'nav.extensionsIntegrations',
  },
  'tenant-runtime-infrastructure': {
    id: 'tenant-runtime-infrastructure',
    label: 'nav.runtimeInfrastructure',
  },
  'tenant-governance-management': {
    id: 'tenant-governance-management',
    label: 'nav.governanceManagement',
  },
  'project-workspace': {
    id: 'project-workspace',
    label: 'nav.projectWorkspace',
  },
  'project-knowledge-base': {
    id: 'project-knowledge-base',
    label: 'nav.knowledgeBase',
  },
  'project-discovery': {
    id: 'project-discovery',
    label: 'nav.discovery',
  },
  'project-configuration': {
    id: 'project-configuration',
    label: 'nav.configuration',
  },
};

function stripHash(path: string): string {
  return path.split('#')[0] || path;
}

function splitSearch(path: string): { pathname: string; search: string } {
  const withoutHash = stripHash(path);
  const queryIndex = withoutHash.indexOf('?');

  if (queryIndex < 0) {
    return {
      pathname: withoutHash,
      search: '',
    };
  }

  return {
    pathname: withoutHash.slice(0, queryIndex),
    search: withoutHash.slice(queryIndex),
  };
}

function normalizePathname(path: string): string {
  const trimmed = path.trim();
  if (!trimmed || trimmed === '/') {
    return '/';
  }

  const withLeadingSlash = trimmed.startsWith('/') ? trimmed : `/${trimmed}`;
  const compact = withLeadingSlash.replace(/\/+/g, '/');

  return compact.length > 1 ? compact.replace(/\/+$/, '') : compact;
}

function sanitizeSegment(segment: string): string {
  return segment.replace(/^\/+|\/+$/g, '');
}

function buildRelativeSegment(path: string): string {
  const normalized = sanitizeSegment(splitSearch(path).pathname);
  return normalized ? `/${normalized}` : '';
}

export function normalizeNavigationPath(path: string): string {
  return normalizePathname(splitSearch(path).pathname);
}

export function normalizeNavigationReference(path: string): string {
  const { pathname, search } = splitSearch(path);
  const normalizedPath = normalizePathname(pathname);
  return search ? `${normalizedPath}${search}` : normalizedPath;
}

export function isCanonicalAbsolutePath(path: string): boolean {
  const normalizedPath = normalizeNavigationPath(path);
  return CANONICAL_ABSOLUTE_PREFIXES.some(
    (prefix) => normalizedPath === prefix || normalizedPath.startsWith(`${prefix}/`)
  );
}

export function joinNavigationPaths(basePath: string, path: string): string {
  if (!path) {
    return normalizeNavigationPath(basePath);
  }

  if (isCanonicalAbsolutePath(path)) {
    return normalizeNavigationReference(path);
  }

  const { search } = splitSearch(path);
  const normalizedBasePath = normalizeNavigationPath(basePath);
  const relativeSegment = buildRelativeSegment(path);
  const joinedPath = relativeSegment
    ? `${normalizedBasePath}${relativeSegment}`
    : normalizedBasePath;

  return search ? `${joinedPath}${search}` : joinedPath;
}

export function getCanonicalTenantPath(tenantId?: string): string {
  return tenantId ? `/tenant/${tenantId}` : LANDING_PATH;
}

export function getCanonicalTenantDestinationPath(
  tenantId: string | undefined,
  path: string
): string {
  return joinNavigationPaths(getCanonicalTenantPath(tenantId), path);
}

export function getCanonicalAgentWorkspacePath(
  context: Pick<NavigationRuntimeContext, 'conversationId' | 'tenantId'>
): string {
  const basePath = getCanonicalTenantPath(context.tenantId);
  const relativePath = context.conversationId
    ? `/agent-workspace/${context.conversationId}`
    : '/agent-workspace';

  return joinNavigationPaths(basePath, relativePath);
}

export function getCanonicalProjectPath(
  context: Pick<NavigationRuntimeContext, 'projectId' | 'tenantId'> & {
    path?: string | undefined;
  }
): string {
  if (!context.tenantId || !context.projectId) {
    return PROJECT_DISCOVERY_PATH;
  }

  const basePath = `/tenant/${context.tenantId}/project/${context.projectId}`;
  return context.path ? joinNavigationPaths(basePath, context.path) : basePath;
}

export function getCanonicalAgentPath(
  context: Pick<NavigationRuntimeContext, 'projectId' | 'tenantId'> & {
    path?: string | undefined;
  }
): string {
  if (!context.tenantId || !context.projectId) {
    return PROJECT_DISCOVERY_PATH;
  }

  const agentRelativePath = context.path ? joinNavigationPaths('/agent', context.path) : '/agent';
  return getCanonicalProjectPath({
    tenantId: context.tenantId,
    projectId: context.projectId,
    path: agentRelativePath,
  });
}

export function getCanonicalBlackboardPath(
  context: Pick<NavigationRuntimeContext, 'preferredWorkspaceId' | 'projectId' | 'tenantId'>
): string {
  if (!context.tenantId || !context.projectId) {
    return PROJECT_DISCOVERY_PATH;
  }

  const basePath = getCanonicalProjectPath({
    tenantId: context.tenantId,
    projectId: context.projectId,
    path: '/blackboard',
  });

  if (!context.preferredWorkspaceId) {
    return basePath;
  }

  const searchParams = new URLSearchParams({
    workspaceId: context.preferredWorkspaceId,
  });

  return `${basePath}?${searchParams.toString()}`;
}

export function parseNavigationPath(pathname: string): ParsedNavigationPath {
  const normalizedPath = normalizeNavigationPath(pathname);
  const segments = normalizedPath.split('/').filter(Boolean);

  if (normalizedPath === '/' || normalizedPath === LANDING_PATH) {
    return {
      family: 'landing',
      isLegacyAlias: false,
      normalizedPath: normalizedPath === '/' ? LANDING_PATH : normalizedPath,
      segments,
    };
  }

  if (segments[0] === 'tenant') {
    const tenantId = segments[1];

    if (!tenantId) {
      return {
        family: 'landing',
        isLegacyAlias: false,
        normalizedPath: LANDING_PATH,
        segments,
      };
    }

    if (segments[2] === 'project' && segments[3]) {
      const section = segments[4];
      return {
        family: section === 'blackboard' ? 'project-blackboard-dynamic' : 'project',
        isLegacyAlias: false,
        normalizedPath,
        projectId: segments[3],
        section,
        segments,
        subSection: segments[5],
        tenantId,
      };
    }

    if (segments[2] === 'agent-workspace') {
      return {
        family: 'agent-workspace',
        conversationId: segments[3],
        isLegacyAlias: false,
        normalizedPath,
        section: segments[2],
        segments,
        subSection: segments[4],
        tenantId,
      };
    }

    return {
      family: 'tenant',
      isLegacyAlias: false,
      normalizedPath,
      section: segments[2],
      segments,
      subSection: segments[3],
      tenantId,
    };
  }

  if (segments[0] === 'project' && segments[1]) {
    const section = segments[2];
    return {
      family: section === 'blackboard' ? 'project-blackboard-dynamic' : 'project',
      isLegacyAlias: true,
      normalizedPath,
      projectId: segments[1],
      section,
      segments,
      subSection: segments[3],
    };
  }

  return {
    family: 'landing',
    isLegacyAlias: true,
    normalizedPath,
    section: segments[0],
    segments,
    subSection: segments[1],
  };
}

const CANONICAL_NAVIGATION_DESTINATIONS: readonly CanonicalDestinationDefinition[] = [
  {
    id: 'agent-workspace',
    label: 'nav.agentWorkspace',
    routeFamily: 'agent-workspace',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-core-operations',
    relativePath: '/agent-workspace',
    buildPath: (context) => getCanonicalAgentWorkspacePath(context),
  },
  {
    id: 'overview',
    label: 'nav.overview',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-core-operations',
    relativePath: '/overview',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/overview'),
  },
  {
    id: 'projects',
    label: 'nav.projects',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-core-operations',
    relativePath: '/projects',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/projects'),
  },
  {
    id: 'workspaces',
    label: 'nav.workspaces',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-core-operations',
    relativePath: '/workspaces',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/workspaces'),
  },
  {
    id: 'tasks',
    label: 'nav.tasks',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-core-operations',
    relativePath: '/tasks',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/tasks'),
  },
  {
    id: 'analytics',
    label: 'nav.analytics',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-core-operations',
    relativePath: '/analytics',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/analytics'),
  },
  {
    id: 'agent-configuration',
    label: 'nav.agentConfiguration',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-agent-building',
    relativePath: '/agents',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/agents'),
  },
  {
    id: 'subagents',
    label: 'nav.subagents',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-agent-building',
    relativePath: '/subagents',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/subagents'),
  },
  {
    id: 'agent-definitions',
    label: 'nav.agentDefinitions',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-agent-building',
    relativePath: '/agent-definitions',
    buildPath: (context) =>
      getCanonicalTenantDestinationPath(context.tenantId, '/agent-definitions'),
  },
  {
    id: 'agent-bindings',
    label: 'nav.agentBindings',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-agent-building',
    relativePath: '/agent-bindings',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/agent-bindings'),
  },
  {
    id: 'skills',
    label: 'nav.skills',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-agent-building',
    relativePath: '/skills',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/skills'),
  },
  {
    id: 'evolution',
    label: 'nav.evolution',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-agent-building',
    relativePath: '/evolution',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/evolution'),
  },
  {
    id: 'patterns',
    label: 'nav.patterns',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-agent-building',
    relativePath: '/patterns',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/patterns'),
  },
  {
    id: 'plugins',
    label: 'nav.plugins',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-extensions-integrations',
    relativePath: '/plugins',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/plugins'),
  },
  {
    id: 'mcp-servers',
    label: 'nav.mcpServers',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-extensions-integrations',
    relativePath: '/mcp-servers',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/mcp-servers'),
  },
  {
    id: 'templates',
    label: 'nav.templates',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-extensions-integrations',
    relativePath: '/templates',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/templates'),
  },
  {
    id: 'providers',
    label: 'nav.providers',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-extensions-integrations',
    relativePath: '/providers',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/providers'),
  },
  {
    id: 'webhooks',
    label: 'nav.webhooks',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-extensions-integrations',
    relativePath: '/webhooks',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/webhooks'),
  },
  {
    id: 'runtimes',
    label: 'nav.runtimes',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-runtime-infrastructure',
    relativePath: '/runtimes',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/runtimes'),
  },
  {
    id: 'pool',
    label: 'nav.pool',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-runtime-infrastructure',
    relativePath: '/pool',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/pool'),
  },
  {
    id: 'instances',
    label: 'nav.instances',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-runtime-infrastructure',
    relativePath: '/instances',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/instances'),
  },
  {
    id: 'clusters',
    label: 'nav.clusters',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-runtime-infrastructure',
    relativePath: '/clusters',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/clusters'),
  },
  {
    id: 'deploy',
    label: 'nav.deploy',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-runtime-infrastructure',
    relativePath: '/deploy',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/deploy'),
  },
  {
    id: 'instance-templates',
    label: 'nav.instanceTemplates',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-runtime-infrastructure',
    relativePath: '/instance-templates',
    buildPath: (context) =>
      getCanonicalTenantDestinationPath(context.tenantId, '/instance-templates'),
  },
  {
    id: 'genes',
    label: 'nav.genes',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-runtime-infrastructure',
    relativePath: '/genes',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/genes'),
  },
  {
    id: 'users',
    label: 'nav.users',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-governance-management',
    relativePath: '/users',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/users'),
  },
  {
    id: 'audit-logs',
    label: 'nav.auditLogs',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-governance-management',
    relativePath: '/audit-logs',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/audit-logs'),
  },
  {
    id: 'events',
    label: 'nav.events',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-governance-management',
    relativePath: '/events',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/events'),
  },
  {
    id: 'dead-letter-queue',
    label: 'nav.deadLetterQueue',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-governance-management',
    relativePath: '/dead-letter-queue',
    buildPath: (context) =>
      getCanonicalTenantDestinationPath(context.tenantId, '/dead-letter-queue'),
  },
  {
    id: 'trust-policies',
    label: 'nav.trustPolicies',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-governance-management',
    relativePath: '/trust-policies',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/trust-policies'),
  },
  {
    id: 'decision-records',
    label: 'nav.decisionRecords',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-governance-management',
    relativePath: '/decision-records',
    buildPath: (context) =>
      getCanonicalTenantDestinationPath(context.tenantId, '/decision-records'),
  },
  {
    id: 'billing',
    label: 'nav.billing',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-governance-management',
    relativePath: '/billing',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/billing'),
  },
  {
    id: 'org-settings',
    label: 'nav.orgSettings',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-governance-management',
    relativePath: '/org-settings/info',
    buildPath: (context) =>
      getCanonicalTenantDestinationPath(context.tenantId, '/org-settings/info'),
  },
  {
    id: 'settings',
    label: 'nav.settings',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    groupId: 'tenant-governance-management',
    relativePath: '/settings',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/settings'),
  },
  {
    id: 'overview',
    label: 'nav.overview',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'top-nav',
    exact: true,
    groupId: 'project-workspace',
    relativePath: '',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
      }),
  },
  {
    id: 'workspaces',
    label: 'nav.workspaces',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'top-nav',
    groupId: 'project-workspace',
    relativePath: 'workspaces',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/workspaces',
      }),
  },
  {
    id: 'blackboard',
    label: 'nav.blackboard',
    routeFamily: 'project-blackboard-dynamic',
    contexts: ['project'],
    displayRole: 'top-nav',
    groupId: 'project-workspace',
    relativePath: 'blackboard',
    buildPath: (context) => getCanonicalBlackboardPath(context),
  },
  {
    id: 'team',
    label: 'nav.team',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'top-nav',
    groupId: 'project-workspace',
    relativePath: 'team',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/team',
      }),
  },
  {
    id: 'memories',
    label: 'nav.memories',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'top-nav',
    groupId: 'project-knowledge-base',
    relativePath: 'memories',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/memories',
      }),
  },
  {
    id: 'entities',
    label: 'nav.entities',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'top-nav',
    groupId: 'project-knowledge-base',
    relativePath: 'entities',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/entities',
      }),
  },
  {
    id: 'communities',
    label: 'nav.communities',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'top-nav',
    groupId: 'project-knowledge-base',
    relativePath: 'communities',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/communities',
      }),
  },
  {
    id: 'graph',
    label: 'nav.knowledgeGraph',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'top-nav',
    groupId: 'project-knowledge-base',
    relativePath: 'graph',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/graph',
      }),
  },
  {
    id: 'search',
    label: 'nav.deepSearch',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'overflow',
    groupId: 'project-discovery',
    relativePath: 'advanced-search',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/advanced-search',
      }),
  },
  {
    id: 'schema',
    label: 'nav.schema',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'overflow',
    groupId: 'project-configuration',
    relativePath: 'schema',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/schema',
      }),
  },
  {
    id: 'channels',
    label: 'nav.channels',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'overflow',
    groupId: 'project-configuration',
    relativePath: 'channels',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/channels',
      }),
  },
  {
    id: 'maintenance',
    label: 'nav.maintenance',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'overflow',
    groupId: 'project-configuration',
    relativePath: 'maintenance',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/maintenance',
      }),
  },
  {
    id: 'cron-jobs',
    label: 'nav.cronJobs',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'overflow',
    groupId: 'project-configuration',
    relativePath: 'cron-jobs',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/cron-jobs',
      }),
  },
  {
    id: 'settings',
    label: 'nav.settings',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'overflow',
    groupId: 'project-configuration',
    relativePath: 'settings',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/settings',
      }),
  },
  {
    id: 'dashboard',
    label: 'Dashboard',
    routeFamily: 'project',
    contexts: ['agent'],
    displayRole: 'top-nav',
    exact: true,
    groupId: 'project-workspace',
    relativePath: '',
    buildPath: (context) =>
      getCanonicalAgentPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
      }),
  },
  {
    id: 'logs',
    label: 'Activity Logs',
    routeFamily: 'project',
    contexts: ['agent'],
    displayRole: 'top-nav',
    groupId: 'project-workspace',
    relativePath: 'logs',
    buildPath: (context) =>
      getCanonicalAgentPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: 'logs',
      }),
  },
  {
    id: 'patterns',
    label: 'Patterns',
    routeFamily: 'project',
    contexts: ['agent'],
    displayRole: 'top-nav',
    groupId: 'project-workspace',
    relativePath: 'patterns',
    buildPath: (context) =>
      getCanonicalAgentPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: 'patterns',
      }),
  },
] as const;

export function getCanonicalNavigationRegistry(): readonly CanonicalDestinationDefinition[] {
  return CANONICAL_NAVIGATION_DESTINATIONS;
}

export function deriveTopNavigationItems(
  context: TopNavigationContext,
  runtimeContext: NavigationRuntimeContext = {}
): DerivedNavigationItem[] {
  const visible = CANONICAL_NAVIGATION_DESTINATIONS.filter((destination) =>
    destination.contexts.includes(context)
  );
  const ordered = [
    ...visible.filter((destination) => destination.displayRole === 'top-nav'),
    ...visible.filter((destination) => destination.displayRole !== 'top-nav'),
  ];

  return ordered.map((destination) => ({
    context,
    displayRole: destination.displayRole,
    exact: destination.exact,
    groupId: destination.groupId,
    groupLabel: NAVIGATION_GROUPS[destination.groupId].label,
    id: destination.id,
    label: destination.label,
    path: destination.buildPath(runtimeContext),
    relativePath: destination.relativePath,
    routeFamily: destination.routeFamily,
  }));
}

/**
 * Compatibility wrapper for existing shell consumers that still call the old
 * deriveTopNavigation API by passing the current context in the options bag.
 */
export function deriveTopNavigation(options: DeriveTopNavigationOptions): DerivedNavigationItem[] {
  const { currentContext, ...runtimeContext } = options;
  return deriveTopNavigationItems(currentContext, runtimeContext);
}

export function getTenantContentSections(): string[] {
  const tenantSections = CANONICAL_NAVIGATION_DESTINATIONS.filter((destination) =>
    destination.contexts.includes('tenant')
  )
    .map((destination) => sanitizeSegment(destination.relativePath).split('/')[0])
    .filter((section): section is string => Boolean(section));

  return Array.from(new Set([...tenantSections, ...TENANT_AUXILIARY_CONTENT_SECTIONS, 'project']));
}

function cloneSidebarConfig(config: SidebarConfig): SidebarConfig {
  return {
    ...config,
    groups: config.groups.map((group) => ({
      ...group,
      items: group.items.map((item) => ({ ...item })),
    })),
    bottom: config.bottom?.map((item) => ({ ...item })),
  };
}

// ============================================================================
// NAVIGATION CONFIGURATION DATA
// ============================================================================

/**
 * Tenant sidebar configuration
 */
const TENANT_SIDEBAR_CONFIG: SidebarConfig = {
  width: 256,
  collapsedWidth: 80,
  showUser: true,
  groups: [
    {
      id: 'core-operations',
      title: 'nav.coreOperations',
      collapsible: false,
      items: [
        { id: 'agent-workspace', icon: 'chat', label: 'nav.agentWorkspace', path: '', exact: true },
        { id: 'overview', icon: 'dashboard', label: 'nav.overview', path: '/overview' },
        { id: 'projects', icon: 'folder', label: 'nav.projects', path: '/projects' },
        { id: 'workspaces', icon: 'group_work', label: 'nav.workspaces', path: '/workspaces' },
        { id: 'tasks', icon: 'task', label: 'nav.tasks', path: '/tasks' },
        { id: 'analytics', icon: 'monitoring', label: 'nav.analytics', path: '/analytics' },
      ],
    },
    {
      id: 'agent-building',
      title: 'nav.agentBuilding',
      collapsible: true,
      defaultOpen: true,
      items: [
        {
          id: 'agent-configuration',
          icon: 'tune',
          label: 'nav.agentConfiguration',
          path: '/agents',
        },
        { id: 'subagents', icon: 'smart_toy', label: 'nav.subagents', path: '/subagents' },
        {
          id: 'agent-definitions',
          icon: 'hub',
          label: 'nav.agentDefinitions',
          path: '/agent-definitions',
        },
        {
          id: 'agent-bindings',
          icon: 'link',
          label: 'nav.agentBindings',
          path: '/agent-bindings',
        },
        { id: 'skills', icon: 'psychology', label: 'nav.skills', path: '/skills' },
        { id: 'evolution', icon: 'genetics', label: 'nav.evolution', path: '/evolution' },
        { id: 'patterns', icon: 'account_tree', label: 'nav.patterns', path: '/patterns' },
      ],
    },
    {
      id: 'extensions-integrations',
      title: 'nav.extensionsIntegrations',
      collapsible: true,
      defaultOpen: true,
      items: [
        { id: 'plugins', icon: 'extension', label: 'nav.plugins', path: '/plugins' },
        { id: 'mcp-servers', icon: 'cable', label: 'nav.mcpServers', path: '/mcp-servers' },
        { id: 'templates', icon: 'widgets', label: 'nav.templates', path: '/templates' },
        { id: 'providers', icon: 'model_training', label: 'nav.providers', path: '/providers' },
        { id: 'webhooks', icon: 'webhook', label: 'nav.webhooks', path: '/webhooks' },
      ],
    },
    {
      id: 'runtime-infrastructure',
      title: 'nav.runtimeInfrastructure',
      collapsible: true,
      defaultOpen: true,
      items: [
        { id: 'runtimes', icon: 'monitor_heart', label: 'nav.runtimes', path: '/runtimes' },
        { id: 'pool', icon: 'memory', label: 'nav.pool', path: '/pool' },
        { id: 'instances', icon: 'dns', label: 'nav.instances', path: '/instances' },
        { id: 'clusters', icon: 'cloud', label: 'nav.clusters', path: '/clusters' },
        { id: 'deploy', icon: 'rocket_launch', label: 'nav.deploy', path: '/deploy' },
        {
          id: 'instance-templates',
          icon: 'dashboard_customize',
          label: 'nav.instanceTemplates',
          path: '/instance-templates',
        },
        { id: 'genes', icon: 'genetics', label: 'nav.genes', path: '/genes' },
      ],
    },
    {
      id: 'governance-management',
      title: 'nav.governanceManagement',
      collapsible: true,
      defaultOpen: true,
      items: [
        { id: 'users', icon: 'group', label: 'nav.users', path: '/users' },
        { id: 'audit-logs', icon: 'history', label: 'nav.auditLogs', path: '/audit-logs' },
        { id: 'events', icon: 'event', label: 'nav.events', path: '/events' },
        {
          id: 'dead-letter-queue',
          icon: 'event',
          label: 'nav.deadLetterQueue',
          path: '/dead-letter-queue',
        },
        {
          id: 'trust-policies',
          icon: 'policy',
          label: 'nav.trustPolicies',
          path: '/trust-policies',
        },
        {
          id: 'decision-records',
          icon: 'gavel',
          label: 'nav.decisionRecords',
          path: '/decision-records',
        },
        { id: 'billing', icon: 'credit_card', label: 'nav.billing', path: '/billing' },
        {
          id: 'org-settings',
          icon: 'business',
          label: 'nav.orgSettings',
          path: '/org-settings/info',
        },
        { id: 'settings', icon: 'settings', label: 'nav.settings', path: '/settings' },
      ],
    },
  ],
  bottom: [],
};

/**
 * Project sidebar configuration
 */
const PROJECT_SIDEBAR_CONFIG: SidebarConfig = {
  width: 256,
  collapsedWidth: 80,
  showUser: true,
  groups: [
    {
      id: 'main',
      title: '',
      collapsible: false,
      defaultOpen: true,
      items: [{ id: 'overview', icon: 'dashboard', label: 'nav.overview', path: '', exact: true }],
    },
    {
      id: 'knowledge',
      title: 'nav.knowledgeBase',
      collapsible: true,
      defaultOpen: true,
      items: [
        { id: 'memories', icon: 'database', label: 'nav.memories', path: '/memories' },
        { id: 'entities', icon: 'category', label: 'nav.entities', path: '/entities' },
        { id: 'communities', icon: 'groups', label: 'nav.communities', path: '/communities' },
        { id: 'graph', icon: 'hub', label: 'nav.knowledgeGraph', path: '/graph' },
        { id: 'blackboard', icon: 'forum', label: 'nav.blackboard', path: '/blackboard' },
      ],
    },
    {
      id: 'discovery',
      title: 'nav.discovery',
      collapsible: true,
      defaultOpen: true,
      items: [
        { id: 'search', icon: 'travel_explore', label: 'nav.deepSearch', path: '/advanced-search' },
      ],
    },
    {
      id: 'config',
      title: 'nav.configuration',
      collapsible: true,
      defaultOpen: true,
      items: [
        { id: 'schema', icon: 'code', label: 'nav.schema', path: '/schema' },
        { id: 'channels', icon: 'chat', label: 'nav.channels', path: '/channels' },
        { id: 'maintenance', icon: 'build', label: 'nav.maintenance', path: '/maintenance' },
        { id: 'cron-jobs', icon: 'schedule', label: 'nav.cronJobs', path: '/cron-jobs' },
        { id: 'team', icon: 'manage_accounts', label: 'nav.team', path: '/team' },
        { id: 'settings', icon: 'settings', label: 'nav.settings', path: '/settings' },
      ],
    },
  ],
  bottom: [{ id: 'support', icon: 'help', label: 'nav.support', path: '/support' }],
};

/**
 * Agent sidebar configuration
 *
 * Note: basePath is set to /project/{projectId} in AgentSidebar component
 * All paths are relative to that base (e.g., '' = /project/{projectId})
 */
const AGENT_SIDEBAR_CONFIG: SidebarConfig = {
  width: 256,
  collapsedWidth: 80,
  showUser: true,
  groups: [
    {
      id: 'main',
      title: '',
      collapsible: false,
      items: [
        {
          id: 'back-to-project',
          icon: 'arrow_back',
          label: 'Back to Project',
          path: '',
          exact: true,
        },
        { id: 'overview', icon: 'dashboard', label: 'Project Overview', path: '' },
        { id: 'memories', icon: 'database', label: 'Memories', path: '/memories' },
        { id: 'entities', icon: 'category', label: 'Entities', path: '/entities' },
        { id: 'graph', icon: 'hub', label: 'Knowledge Graph', path: '/graph' },
        { id: 'search', icon: 'search', label: 'Deep Search', path: '/advanced-search' },
      ],
    },
  ],
  bottom: [
    { id: 'settings', icon: 'settings', label: 'Project Settings', path: '/settings' },
    { id: 'support', icon: 'help', label: 'Help & Support', path: '/support' },
  ],
};

/**
 * Schema tabs configuration
 */
const SCHEMA_TABS: TabItem[] = [
  { id: 'overview', label: 'Overview', path: '' },
  { id: 'entities', label: 'Entity Types', path: 'entities' },
  { id: 'edges', label: 'Edge Types', path: 'edges' },
  { id: 'mapping', label: 'Mapping', path: 'mapping' },
];

// ============================================================================
// EXPORT FUNCTIONS
// ============================================================================

/**
 * Get complete navigation configuration
 */
export function getNavigationConfig(): NavConfig {
  return {
    tenant: { sidebar: getTenantSidebarConfig() },
    project: { sidebar: getProjectSidebarConfig() },
    agent: { sidebar: getAgentConfig().sidebar, tabs: getAgentConfig().tabs },
    schema: { tabs: getSchemaTabs() },
  };
}

/**
 * Backwards-compatible alias used by existing tests.
 */
export const _getNavigationConfig = getNavigationConfig;

/**
 * Get tenant sidebar configuration
 */
export function getTenantSidebarConfig(): SidebarConfig {
  return cloneSidebarConfig(TENANT_SIDEBAR_CONFIG);
}

/**
 * Get project sidebar configuration.
 *
 * When runtime context is provided, dynamic destinations such as blackboard are
 * derived from the canonical path builders while preserving legacy relative
 * semantics for existing shell consumers.
 */
export function getProjectSidebarConfig(
  runtimeContext?: Pick<NavigationRuntimeContext, 'preferredWorkspaceId'>
): SidebarConfig {
  const config = cloneSidebarConfig(PROJECT_SIDEBAR_CONFIG);

  if (!runtimeContext?.preferredWorkspaceId) {
    return config;
  }

  const preferredWorkspaceId = runtimeContext.preferredWorkspaceId;

  return {
    ...config,
    groups: config.groups.map((group) => ({
      ...group,
      items: group.items.map((item) =>
        item.id === 'blackboard'
          ? {
              ...item,
              path: `/blackboard?workspaceId=${preferredWorkspaceId}`,
            }
          : item
      ),
    })),
  };
}

/**
 * Compatibility wrapper for project sidebar consumers migrating to the
 * derivation-based config API.
 */
export function deriveProjectSidebarConfig(
  runtimeContext?: Pick<NavigationRuntimeContext, 'preferredWorkspaceId'>
): SidebarConfig {
  return getProjectSidebarConfig(runtimeContext);
}

/**
 * Get agent configuration (sidebar + tabs)
 */
export function getAgentConfig(): { sidebar: SidebarConfig; tabs: TabItem[] } {
  return {
    sidebar: cloneSidebarConfig(AGENT_SIDEBAR_CONFIG),
    tabs: deriveTopNavigationItems('agent').map(({ id, label, relativePath }) => ({
      id,
      label,
      path: relativePath,
    })),
  };
}

/**
 * Get schema tabs configuration
 */
export function getSchemaTabs(): TabItem[] {
  return SCHEMA_TABS.map((tab) => ({ ...tab }));
}

/**
 * Get project header tabs for contextual navigation in TenantHeader.
 *
 * The default output remains relative for compatibility with the current shell,
 * while callers that need canonical full paths should use deriveTopNavigationItems.
 */
export function getProjectHeaderTabs(): TabItem[] {
  return deriveTopNavigationItems('project').map(({ id, label, relativePath }) => ({
    id,
    label,
    path: relativePath,
  }));
}
