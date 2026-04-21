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
  relativePath: string;
  buildPath: (context: NavigationRuntimeContext) => string;
}

const LANDING_PATH = '/tenant';
const PROJECT_DISCOVERY_PATH = '/tenant/projects';
const CANONICAL_ABSOLUTE_PREFIXES = ['/tenant', '/project'];

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
  const joinedPath = relativeSegment ? `${normalizedBasePath}${relativeSegment}` : normalizedBasePath;

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
    relativePath: '/agent-workspace',
    buildPath: (context) => getCanonicalAgentWorkspacePath(context),
  },
  {
    id: 'overview',
    label: 'nav.overview',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    relativePath: '/overview',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/overview'),
  },
  {
    id: 'agent-configuration',
    label: 'nav.agentConfiguration',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    relativePath: '/agents',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/agents'),
  },
  {
    id: 'projects',
    label: 'nav.projects',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    relativePath: '/projects',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/projects'),
  },
  {
    id: 'tasks',
    label: 'nav.tasks',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    relativePath: '/tasks',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/tasks'),
  },
  {
    id: 'users',
    label: 'nav.users',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    relativePath: '/users',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/users'),
  },
  {
    id: 'analytics',
    label: 'nav.analytics',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'overflow',
    relativePath: '/analytics',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/analytics'),
  },
  {
    id: 'workspaces',
    label: 'nav.workspaces',
    routeFamily: 'project',
    contexts: ['tenant', 'project'],
    displayRole: 'top-nav',
    relativePath: 'workspaces',
    buildPath: (context) =>
      context.projectId && context.tenantId
        ? getCanonicalProjectPath({
            tenantId: context.tenantId,
            projectId: context.projectId,
            path: '/workspaces',
          })
        : getCanonicalTenantDestinationPath(context.tenantId, '/workspaces'),
  },
  {
    id: 'skills',
    label: 'nav.skills',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    relativePath: '/skills',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/skills'),
  },
  {
    id: 'subagents',
    label: 'nav.subagents',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    relativePath: '/subagents',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/subagents'),
  },
  {
    id: 'audit-logs',
    label: 'nav.auditLogs',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    relativePath: '/audit-logs',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/audit-logs'),
  },
  {
    id: 'agent-definitions',
    label: 'nav.agentDefinitions',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
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
    relativePath: '/agent-bindings',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/agent-bindings'),
  },
  {
    id: 'mcp-servers',
    label: 'nav.mcpServers',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    relativePath: '/mcp-servers',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/mcp-servers'),
  },
  {
    id: 'plugins',
    label: 'nav.plugins',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    relativePath: '/plugins',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/plugins'),
  },
  {
    id: 'providers',
    label: 'nav.providers',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    relativePath: '/providers',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/providers'),
  },
  {
    id: 'instances',
    label: 'nav.instances',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    relativePath: '/instances',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/instances'),
  },
  {
    id: 'overview',
    label: 'nav.overview',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'top-nav',
    exact: true,
    relativePath: '',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
      }),
  },
  {
    id: 'memories',
    label: 'nav.memories',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'top-nav',
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
    displayRole: 'top-nav',
    relativePath: 'advanced-search',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/advanced-search',
      }),
  },
  {
    id: 'blackboard',
    label: 'nav.blackboard',
    routeFamily: 'project-blackboard-dynamic',
    contexts: ['project'],
    displayRole: 'top-nav',
    relativePath: 'blackboard',
    buildPath: (context) => getCanonicalBlackboardPath(context),
  },
  {
    id: 'schema',
    label: 'nav.schema',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'top-nav',
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
    displayRole: 'top-nav',
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
    displayRole: 'top-nav',
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
    displayRole: 'top-nav',
    relativePath: 'cron-jobs',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/cron-jobs',
      }),
  },
  {
    id: 'team',
    label: 'nav.team',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'top-nav',
    relativePath: 'team',
    buildPath: (context) =>
      getCanonicalProjectPath({
        tenantId: context.tenantId,
        projectId: context.projectId,
        path: '/team',
      }),
  },
  {
    id: 'settings',
    label: 'nav.settings',
    routeFamily: 'project',
    contexts: ['project'],
    displayRole: 'top-nav',
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
export function deriveTopNavigation(
  options: DeriveTopNavigationOptions
): DerivedNavigationItem[] {
  const { currentContext, ...runtimeContext } = options;
  return deriveTopNavigationItems(currentContext, runtimeContext);
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
      id: 'platform',
      title: 'nav.platform',
      collapsible: false,
      items: [
        { id: 'agent-workspace', icon: 'chat', label: 'nav.agentWorkspace', path: '', exact: true },
        { id: 'overview', icon: 'dashboard', label: 'nav.overview', path: '/overview' },
        { id: 'projects', icon: 'folder', label: 'nav.projects', path: '/projects' },
        { id: 'users', icon: 'group', label: 'nav.users', path: '/users' },
        { id: 'analytics', icon: 'monitoring', label: 'nav.analytics', path: '/analytics' },
        { id: 'tasks', icon: 'task', label: 'nav.tasks', path: '/tasks' },
        { id: 'workspaces', icon: 'group_work', label: 'Workspaces', path: '/workspaces' },
        { id: 'agents', icon: 'tune', label: 'nav.agentConfiguration', path: '/agents' },
        { id: 'subagents', icon: 'smart_toy', label: 'nav.subagents', path: '/subagents' },
        { id: 'skills', icon: 'psychology', label: 'nav.skills', path: '/skills' },
        { id: 'plugins', icon: 'extension', label: 'nav.plugins', path: '/plugins' },
        { id: 'templates', icon: 'widgets', label: 'nav.templates', path: '/templates' },
        { id: 'mcp-servers', icon: 'cable', label: 'nav.mcpServers', path: '/mcp-servers' },
        { id: 'patterns', icon: 'account_tree', label: 'Workflow Patterns', path: '/patterns' },
        { id: 'providers', icon: 'model_training', label: 'nav.providers', path: '/providers' },
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
      ],
    },
    {
      id: 'infrastructure',
      title: 'nav.infrastructure',
      collapsible: true,
      items: [
        { id: 'instances', icon: 'dns', label: 'nav.instances', path: '/instances' },
        { id: 'clusters', icon: 'cloud', label: 'nav.clusters', path: '/clusters' },
        { id: 'deploy', icon: 'rocket_launch', label: 'nav.deploy', path: '/deploy' },
        { id: 'genes', icon: 'genetics', label: 'nav.genes', path: '/genes' },
        {
          id: 'instance-templates',
          icon: 'dashboard_customize',
          label: 'nav.instanceTemplates',
          path: '/instance-templates',
        },
      ],
    },
    {
      id: 'administration',
      title: 'nav.administration',
      collapsible: false,
      items: [
        { id: 'pool', icon: 'memory', label: 'nav.pool', path: '/pool' },
        { id: 'audit-logs', icon: 'history', label: 'nav.auditLogs', path: '/audit-logs' },
        { id: 'trust-policies', icon: 'policy', label: 'Trust Policies', path: '/trust-policies' },
        {
          id: 'decision-records',
          icon: 'gavel',
          label: 'Decision Records',
          path: '/decision-records',
        },
        { id: 'events', icon: 'event', label: 'nav.events', path: '/events' },
        { id: 'webhooks', icon: 'webhook', label: 'nav.webhooks', path: '/webhooks' },
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
