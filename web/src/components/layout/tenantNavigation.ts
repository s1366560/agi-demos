import {
  deriveTopNavigationItems,
  type NavigationDisplayRole,
  type NavigationGroupId,
} from '@/config/navigation';

export interface TenantTopNavItem {
  id: string;
  label: string;
  path: string;
  displayRole?: NavigationDisplayRole | undefined;
  exact?: boolean | undefined;
  groupId?: NavigationGroupId | undefined;
  groupLabel?: string | undefined;
}

export interface TenantTopNavGroup {
  id: string;
  label: string;
  items: TenantTopNavItem[];
}

const TENANT_NAV_FALLBACK_LABELS: Record<string, string> = {
  'agent-workspace': 'Agent Workspace',
  acp: 'ACP',
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

const NAV_GROUP_FALLBACK_LABELS: Record<NavigationGroupId, string> = {
  'tenant-core-operations': 'Core Operations',
  'tenant-agent-building': 'Agent Building',
  'tenant-extensions-integrations': 'Extensions & Integrations',
  'tenant-runtime-infrastructure': 'Runtime & Infrastructure',
  'tenant-governance-management': 'Governance & Management',
  'project-workspace': 'Project Workspace',
  'project-knowledge-base': 'Knowledge Base',
  'project-discovery': 'Discovery',
  'project-configuration': 'Configuration',
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
    displayRole: item.displayRole,
    id: item.id,
    label: t(item.label, fallbackLabels[item.id] ?? item.label),
    path: item.path || (projectBasePath ?? basePath),
    exact: item.exact,
    groupId: item.groupId,
    groupLabel: item.groupLabel
      ? t(item.groupLabel, item.groupId ? NAV_GROUP_FALLBACK_LABELS[item.groupId] : item.groupLabel)
      : undefined,
  }));
}

export function groupTenantTopNavItems(items: TenantTopNavItem[]): TenantTopNavGroup[] {
  const groups: TenantTopNavGroup[] = [];
  const groupIndex = new Map<string, TenantTopNavGroup>();

  items.forEach((item) => {
    const groupId = item.groupId ?? 'ungrouped';
    const groupLabel = item.groupLabel ?? '';
    let group = groupIndex.get(groupId);

    if (!group) {
      group = {
        id: groupId,
        label: groupLabel,
        items: [],
      };
      groupIndex.set(groupId, group);
      groups.push(group);
    }

    group.items.push(item);
  });

  return groups;
}

export function isContextualTopNavItemActive(pathname: string, item: TenantTopNavItem): boolean {
  const matchPath = stripSearch(item.path);

  if (item.exact) {
    return pathname === matchPath || pathname === `${matchPath}/`;
  }

  return pathname === matchPath || pathname.startsWith(`${matchPath}/`);
}
