import type { CanonicalDesktopRouteId } from './desktopCanonicalRouteCatalog';

export type DesktopNavigationIconKey =
  | 'core'
  | 'agent'
  | 'extensions'
  | 'runtime'
  | 'governance'
  | 'workspace'
  | 'knowledge'
  | 'discovery'
  | 'configuration';

export type CanonicalDesktopNavigationMetadata = Readonly<{
  routeId: CanonicalDesktopRouteId;
  labelKey: string;
  descriptionKey: 'featureDirectory.routeDescription';
  displayRole: 'top-nav' | 'overflow';
  aliases: readonly string[];
}>;

export type CanonicalDesktopNavigationGroup = Readonly<{
  id: string;
  labelKey: string;
  iconKey: DesktopNavigationIconKey;
}>;

export const CANONICAL_DESKTOP_NAVIGATION_GROUPS = Object.freeze([
  {
    id: 'tenant-core-operations',
    labelKey: 'featureDirectory.group.tenantCore',
    iconKey: 'core',
  },
  {
    id: 'tenant-agent-building',
    labelKey: 'featureDirectory.group.agentBuilding',
    iconKey: 'agent',
  },
  {
    id: 'tenant-extensions-integrations',
    labelKey: 'featureDirectory.group.extensions',
    iconKey: 'extensions',
  },
  {
    id: 'tenant-runtime-infrastructure',
    labelKey: 'featureDirectory.group.runtime',
    iconKey: 'runtime',
  },
  {
    id: 'tenant-governance-management',
    labelKey: 'featureDirectory.group.governance',
    iconKey: 'governance',
  },
  {
    id: 'project-workspace',
    labelKey: 'featureDirectory.group.projectWorkspace',
    iconKey: 'workspace',
  },
  {
    id: 'project-knowledge-base',
    labelKey: 'featureDirectory.group.knowledge',
    iconKey: 'knowledge',
  },
  {
    id: 'project-discovery',
    labelKey: 'featureDirectory.group.discovery',
    iconKey: 'discovery',
  },
  {
    id: 'project-configuration',
    labelKey: 'featureDirectory.group.projectConfiguration',
    iconKey: 'configuration',
  },
] as const satisfies readonly CanonicalDesktopNavigationGroup[]);

type NavigationMetadataTuple = readonly [
  routeId: CanonicalDesktopRouteId,
  labelKey: string,
  displayRole: 'top-nav' | 'overflow',
  alias: string,
];

const NAVIGATION_METADATA = [
  ['agent-workspace-tenant-agent-workspace', 'nav.agentWorkspace', 'top-nav', 'agent-workspace'],
  ['tenant-tenant-overview', 'nav.overview', 'top-nav', 'overview'],
  ['tenant-tenant-projects', 'nav.projects', 'top-nav', 'projects'],
  ['tenant-tenant-workspaces', 'nav.workspaces', 'top-nav', 'workspaces'],
  ['tenant-tenant-tasks', 'nav.tasks', 'top-nav', 'tasks'],
  ['tenant-tenant-analytics', 'nav.analytics', 'top-nav', 'analytics'],
  ['tenant-tenant-agent-configuration', 'nav.agentConfiguration', 'top-nav', 'agent-configuration'],
  ['tenant-tenant-agent-definitions', 'nav.agentDefinitions', 'top-nav', 'agent-definitions'],
  ['tenant-tenant-agent-bindings', 'nav.agentBindings', 'top-nav', 'agent-bindings'],
  ['tenant-tenant-skills', 'nav.skills', 'top-nav', 'skills'],
  ['tenant-tenant-evolution', 'nav.evolution', 'top-nav', 'evolution'],
  ['tenant-tenant-patterns', 'nav.patterns', 'top-nav', 'patterns'],
  ['tenant-tenant-plugins', 'nav.plugins', 'overflow', 'plugins'],
  ['tenant-tenant-mcp-servers', 'nav.mcpServers', 'overflow', 'mcp-servers'],
  ['tenant-tenant-acp', 'nav.acp', 'overflow', 'acp'],
  ['tenant-tenant-templates', 'nav.templates', 'overflow', 'templates'],
  ['tenant-tenant-providers', 'nav.providers', 'overflow', 'providers'],
  ['tenant-tenant-webhooks', 'nav.webhooks', 'overflow', 'webhooks'],
  ['tenant-tenant-runtimes', 'nav.runtimes', 'overflow', 'runtimes'],
  ['tenant-tenant-pool', 'nav.pool', 'overflow', 'pool'],
  ['tenant-tenant-instances', 'nav.instances', 'overflow', 'instances'],
  ['tenant-tenant-clusters', 'nav.clusters', 'overflow', 'clusters'],
  ['tenant-tenant-deploy', 'nav.deploy', 'overflow', 'deploy'],
  ['tenant-tenant-instance-templates', 'nav.instanceTemplates', 'overflow', 'instance-templates'],
  ['tenant-tenant-genes', 'nav.genes', 'overflow', 'genes'],
  ['tenant-tenant-users', 'nav.users', 'overflow', 'users'],
  ['tenant-tenant-audit-logs', 'nav.auditLogs', 'overflow', 'audit-logs'],
  ['tenant-tenant-events', 'nav.events', 'overflow', 'events'],
  ['tenant-tenant-dead-letter-queue', 'nav.deadLetterQueue', 'overflow', 'dead-letter-queue'],
  ['tenant-tenant-trust-policies', 'nav.trustPolicies', 'overflow', 'trust-policies'],
  ['tenant-tenant-decision-records', 'nav.decisionRecords', 'overflow', 'decision-records'],
  ['tenant-tenant-billing', 'nav.billing', 'overflow', 'billing'],
  ['tenant-tenant-org-settings', 'nav.orgSettings', 'overflow', 'org-settings'],
  ['tenant-tenant-settings', 'nav.settings', 'overflow', 'settings'],
  ['project-project-overview', 'nav.overview', 'top-nav', 'overview'],
  ['project-project-workspaces', 'nav.workspaces', 'top-nav', 'workspaces'],
  ['project-blackboard-dynamic-project-blackboard', 'nav.blackboard', 'top-nav', 'blackboard'],
  ['project-project-team', 'nav.team', 'top-nav', 'team'],
  ['project-project-memories', 'nav.memories', 'top-nav', 'memories'],
  ['project-project-entities', 'nav.entities', 'top-nav', 'entities'],
  ['project-project-communities', 'nav.communities', 'top-nav', 'communities'],
  ['project-project-graph', 'nav.knowledgeGraph', 'top-nav', 'graph'],
  ['project-project-search', 'nav.deepSearch', 'overflow', 'search'],
  ['project-project-schema', 'nav.schema', 'overflow', 'schema'],
  ['project-project-channels', 'nav.channels', 'overflow', 'channels'],
  ['project-project-maintenance', 'nav.maintenance', 'overflow', 'maintenance'],
  ['project-project-cron-jobs', 'nav.cronJobs', 'overflow', 'cron-jobs'],
  ['project-project-settings', 'nav.settings', 'overflow', 'settings'],
  ['project-agent-dashboard', 'Dashboard', 'top-nav', 'dashboard'],
  ['project-agent-logs', 'Activity Logs', 'top-nav', 'logs'],
  ['project-agent-patterns', 'Patterns', 'top-nav', 'patterns'],
] as const satisfies readonly NavigationMetadataTuple[];

export const CANONICAL_DESKTOP_NAVIGATION_METADATA: readonly CanonicalDesktopNavigationMetadata[] =
  Object.freeze(
    NAVIGATION_METADATA.map(([routeId, labelKey, displayRole, alias]) => ({
      routeId,
      labelKey,
      descriptionKey: 'featureDirectory.routeDescription' as const,
      displayRole,
      aliases: Object.freeze([alias]),
    })),
  );
