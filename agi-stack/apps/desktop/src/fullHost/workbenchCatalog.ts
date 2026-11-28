import type { WorkbenchHeaderSlot } from '../../../../packages/plugin-slots/src/workbenchHeader';

type Context = 'tenant' | 'project';
type Row = readonly [
  id: string,
  label: string,
  context: Context,
  displayRole: 'top-nav' | 'overflow',
  groupId: string,
  relativePath: string,
  routeFamily: string,
];

const GROUP_LABEL: Record<string, string> = {
  'tenant-core-operations': 'nav.coreOperations',
  'tenant-agent-building': 'nav.agentBuilding',
  'tenant-extensions-integrations': 'nav.extensionsIntegrations',
  'tenant-runtime-infrastructure': 'nav.runtimeInfrastructure',
  'tenant-governance-management': 'nav.governanceManagement',
  'project-workspace': 'nav.projectWorkspace',
  'project-knowledge-base': 'nav.knowledgeBase',
  'project-discovery': 'nav.discovery',
  'project-configuration': 'nav.configuration',
};

/** Same section identity as the cloud workbench. Paths are filled in for the open tenant. */
const SECTIONS: readonly Row[] = [
  ['agent-workspace', 'nav.agentWorkspace', 'tenant', 'top-nav', 'tenant-core-operations', '/agent-workspace', 'agent-workspace'],
  ['overview', 'nav.overview', 'tenant', 'top-nav', 'tenant-core-operations', '/overview', 'tenant'],
  ['projects', 'nav.projects', 'tenant', 'top-nav', 'tenant-core-operations', '/projects', 'tenant'],
  ['workspaces', 'nav.workspaces', 'tenant', 'top-nav', 'tenant-core-operations', '/workspaces', 'tenant'],
  ['tasks', 'nav.tasks', 'tenant', 'top-nav', 'tenant-core-operations', '/tasks', 'tenant'],
  ['analytics', 'nav.analytics', 'tenant', 'top-nav', 'tenant-core-operations', '/analytics', 'tenant'],
  ['agent-configuration', 'nav.agentConfiguration', 'tenant', 'top-nav', 'tenant-agent-building', '/agents', 'tenant'],
  ['agent-definitions', 'nav.agentDefinitions', 'tenant', 'top-nav', 'tenant-agent-building', '/agent-definitions', 'tenant'],
  ['agent-bindings', 'nav.agentBindings', 'tenant', 'top-nav', 'tenant-agent-building', '/agent-bindings', 'tenant'],
  ['skills', 'nav.skills', 'tenant', 'top-nav', 'tenant-agent-building', '/skills', 'tenant'],
  ['evolution', 'nav.evolution', 'tenant', 'top-nav', 'tenant-agent-building', '/evolution', 'tenant'],
  ['patterns', 'nav.patterns', 'tenant', 'top-nav', 'tenant-agent-building', '/patterns', 'tenant'],
  ['plugins', 'nav.plugins', 'tenant', 'overflow', 'tenant-extensions-integrations', '/plugins', 'tenant'],
  ['mcp-servers', 'nav.mcpServers', 'tenant', 'overflow', 'tenant-extensions-integrations', '/mcp-servers', 'tenant'],
  ['acp', 'nav.acp', 'tenant', 'overflow', 'tenant-extensions-integrations', '/acp', 'tenant'],
  ['templates', 'nav.templates', 'tenant', 'overflow', 'tenant-extensions-integrations', '/templates', 'tenant'],
  ['providers', 'nav.providers', 'tenant', 'overflow', 'tenant-extensions-integrations', '/providers', 'tenant'],
  ['webhooks', 'nav.webhooks', 'tenant', 'overflow', 'tenant-extensions-integrations', '/webhooks', 'tenant'],
  ['runtimes', 'nav.runtimes', 'tenant', 'overflow', 'tenant-runtime-infrastructure', '/runtimes', 'tenant'],
  ['pool', 'nav.pool', 'tenant', 'overflow', 'tenant-runtime-infrastructure', '/pool', 'tenant'],
  ['instances', 'nav.instances', 'tenant', 'overflow', 'tenant-runtime-infrastructure', '/instances', 'tenant'],
  ['clusters', 'nav.clusters', 'tenant', 'overflow', 'tenant-runtime-infrastructure', '/clusters', 'tenant'],
  ['deploy', 'nav.deploy', 'tenant', 'overflow', 'tenant-runtime-infrastructure', '/deploy', 'tenant'],
  ['instance-templates', 'nav.instanceTemplates', 'tenant', 'overflow', 'tenant-runtime-infrastructure', '/instance-templates', 'tenant'],
  ['genes', 'nav.genes', 'tenant', 'overflow', 'tenant-runtime-infrastructure', '/genes', 'tenant'],
  ['users', 'nav.users', 'tenant', 'overflow', 'tenant-governance-management', '/users', 'tenant'],
  ['audit-logs', 'nav.auditLogs', 'tenant', 'overflow', 'tenant-governance-management', '/audit-logs', 'tenant'],
  ['events', 'nav.events', 'tenant', 'overflow', 'tenant-governance-management', '/events', 'tenant'],
  ['dead-letter-queue', 'nav.deadLetterQueue', 'tenant', 'overflow', 'tenant-governance-management', '/dead-letter-queue', 'tenant'],
  ['trust-policies', 'nav.trustPolicies', 'tenant', 'overflow', 'tenant-governance-management', '/trust-policies', 'tenant'],
  ['decision-records', 'nav.decisionRecords', 'tenant', 'overflow', 'tenant-governance-management', '/decision-records', 'tenant'],
  ['billing', 'nav.billing', 'tenant', 'overflow', 'tenant-governance-management', '/billing', 'tenant'],
  ['org-settings', 'nav.orgSettings', 'tenant', 'overflow', 'tenant-governance-management', '/org-settings/info', 'tenant'],
  ['settings', 'nav.settings', 'tenant', 'overflow', 'tenant-governance-management', '/settings', 'tenant'],
  ['overview', 'nav.overview', 'project', 'top-nav', 'project-workspace', '', 'project'],
  ['workspaces', 'nav.workspaces', 'project', 'top-nav', 'project-workspace', 'workspaces', 'project'],
  ['blackboard', 'nav.blackboard', 'project', 'top-nav', 'project-workspace', 'blackboard', 'project-blackboard-dynamic'],
  ['team', 'nav.team', 'project', 'top-nav', 'project-workspace', 'team', 'project'],
  ['memories', 'nav.memories', 'project', 'top-nav', 'project-knowledge-base', 'memories', 'project'],
  ['entities', 'nav.entities', 'project', 'top-nav', 'project-knowledge-base', 'entities', 'project'],
  ['communities', 'nav.communities', 'project', 'top-nav', 'project-knowledge-base', 'communities', 'project'],
  ['graph', 'nav.knowledgeGraph', 'project', 'top-nav', 'project-knowledge-base', 'graph', 'project'],
  ['search', 'nav.deepSearch', 'project', 'overflow', 'project-discovery', 'advanced-search', 'project'],
  ['schema', 'nav.schema', 'project', 'overflow', 'project-configuration', 'schema', 'project'],
  ['channels', 'nav.channels', 'project', 'overflow', 'project-configuration', 'channels', 'project'],
  ['maintenance', 'nav.maintenance', 'project', 'overflow', 'project-configuration', 'maintenance', 'project'],
  ['cron-jobs', 'nav.cronJobs', 'project', 'overflow', 'project-configuration', 'cron-jobs', 'project'],
  ['settings', 'nav.settings', 'project', 'overflow', 'project-configuration', 'settings', 'project'],
];

export function tenantBase(tenant: string): string {
  return '/tenant/' + encodeURIComponent(tenant);
}

export function projectBase(tenant: string, project: string): string {
  return tenantBase(tenant) + '/project/' + encodeURIComponent(project);
}

function sectionPath(tenant: string, project: string | null, row: Row): string | null {
  const [, , context, , , relativePath] = row;
  if (context === 'tenant') {
    const relative = relativePath.startsWith('/') ? relativePath : relativePath ? '/' + relativePath : '';
    return tenantBase(tenant) + relative;
  }
  if (!project) return null;
  const relative = relativePath.replace(/^\//, '');
  const base = projectBase(tenant, project);
  return relative ? base + '/' + relative : base;
}

export function buildWorkbenchSlots(
  tenant: string,
  project: string | null,
  context: Context,
): WorkbenchHeaderSlot[] {
  return SECTIONS.flatMap((row) => {
    const [id, label, rowContext, displayRole, groupId, relativePath, routeFamily] = row;
    if (rowContext !== context) return [];
    const path = sectionPath(tenant, project, row);
    if (!path) return [];
    return [
      {
        id,
        label,
        path,
        context,
        displayRole,
        groupId,
        groupLabel: GROUP_LABEL[groupId] ?? groupId,
        relativePath,
        routeFamily,
      },
    ];
  });
}
