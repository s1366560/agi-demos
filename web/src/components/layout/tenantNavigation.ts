import { deriveTopNavigationItems } from '@/config/navigation';

export interface TenantTopNavItem {
  id: string;
  label: string;
  path: string;
  exact?: boolean | undefined;
}

const TENANT_NAV_FALLBACK_LABELS: Record<string, string> = {
  'agent-workspace': 'Agent Workspace',
  'agent-configuration': 'Agent Configuration',
  'audit-logs': 'Audit Logs',
  billing: 'Billing',
  clusters: 'Clusters',
  'dead-letter-queue': 'Dead Letter Queue',
  'decision-records': 'Decision Records',
  deploy: 'Deploy',
  events: 'Events',
  evolution: 'Evolution',
  genes: 'Gene Market',
  'instance-templates': 'Instance Templates',
  instances: 'Instances',
  'mcp-servers': 'MCP',
  overview: 'Overview',
  patterns: 'Workflow Patterns',
  pool: 'Agent Pool',
  plugins: 'Plugins',
  projects: 'Projects',
  providers: 'Model Services',
  runtimes: 'Runtimes',
  settings: 'Settings',
  skills: 'Skills',
  subagents: 'Agents',
  tasks: 'Tasks',
  templates: 'Templates',
  'trust-policies': 'Trust Policies',
  users: 'Users',
  webhooks: 'Webhooks',
  workspaces: 'Workspaces',
  'org-settings': 'Organization Settings',
};

const PROJECT_NAV_FALLBACK_LABELS: Record<string, string> = {
  blackboard: 'Blackboard',
  channels: 'Channels',
  communities: 'Communities',
  'cron-jobs': 'Cron Jobs',
  entities: 'Entities',
  graph: 'Knowledge Graph',
  maintenance: 'Maintenance',
  memories: 'Memories',
  overview: 'Overview',
  schema: 'Schema',
  search: 'Deep Search',
  settings: 'Settings',
  team: 'Team',
  workspaces: 'Workspaces',
};

interface ContextualNavOptions {
  basePath: string;
  projectBasePath: string | null;
  preferredWorkspaceId: string | null;
  t: (key: string, fallback?: string) => string;
  tenantId?: string | undefined;
  projectId?: string | undefined;
}

function stripSearch(path: string): string {
  return path.split('?')[0] || path;
}

export function getContextualTopNavItems({
  basePath,
  projectBasePath,
  preferredWorkspaceId,
  t,
  tenantId,
  projectId,
}: ContextualNavOptions): TenantTopNavItem[] {
  const currentContext = projectBasePath ? 'project' : 'tenant';
  const fallbackLabels =
    currentContext === 'project' ? PROJECT_NAV_FALLBACK_LABELS : TENANT_NAV_FALLBACK_LABELS;

  return deriveTopNavigationItems(currentContext, {
    tenantId,
    projectId,
    preferredWorkspaceId,
  }).map((item) => ({
    id: item.id,
    label: t(item.label, fallbackLabels[item.id] ?? item.label),
    path: item.path || (projectBasePath ?? basePath),
    exact: item.exact,
  }));
}

export function isContextualTopNavItemActive(pathname: string, item: TenantTopNavItem): boolean {
  const matchPath = stripSearch(item.path);

  if (item.exact) {
    return pathname === matchPath || pathname === `${matchPath}/`;
  }

  return pathname === matchPath || pathname.startsWith(`${matchPath}/`);
}
