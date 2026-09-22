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
  groupId: string;
  labelKey: string;
  descriptionKey: 'featureDirectory.routeDescription';
  displayRole: 'top-nav' | 'overflow';
  aliases: readonly string[];
}>;

export type DesktopNavigationMetadata = Readonly<{
  routeId: string;
  groupId?: string;
  labelKey: string;
  descriptionKey: string;
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

// Presentation groups are independent of the canonical route ownership and permissions.
export const DESKTOP_NAVIGATION_GROUPS = Object.freeze([
  { id: 'tasks-automation', labelKey: 'featureDirectory.group.tasksAutomation', iconKey: 'core' },
  {
    id: 'knowledge-memory',
    labelKey: 'featureDirectory.group.knowledgeMemory',
    iconKey: 'knowledge',
  },
  {
    id: 'agents-extensions',
    labelKey: 'featureDirectory.group.agentsExtensions',
    iconKey: 'agent',
  },
  {
    id: 'workspaces-runtime',
    labelKey: 'featureDirectory.group.workspacesRuntime',
    iconKey: 'workspace',
  },
  { id: 'organization', labelKey: 'featureDirectory.group.organization', iconKey: 'governance' },
] as const satisfies readonly CanonicalDesktopNavigationGroup[]);

type NavigationMetadataTuple = readonly [
  routeId: CanonicalDesktopRouteId,
  labelKey: string,
  displayRole: 'top-nav' | 'overflow',
  alias: string,
  groupId: (typeof DESKTOP_NAVIGATION_GROUPS)[number]['id'],
];

const NAVIGATION_METADATA = [
  [
    'agent-workspace-tenant-agent-workspace',
    'nav.agentWorkspace',
    'top-nav',
    'agent-workspace',
    'tasks-automation',
  ],
  ['tenant-tenant-overview', 'nav.overview', 'top-nav', 'overview', 'organization'],
  ['tenant-tenant-projects', 'nav.projects', 'top-nav', 'projects', 'workspaces-runtime'],
  ['tenant-tenant-workspaces', 'nav.workspaces', 'top-nav', 'workspaces', 'workspaces-runtime'],
  ['tenant-tenant-tasks', 'nav.tasks', 'top-nav', 'tasks', 'tasks-automation'],
  ['tenant-tenant-analytics', 'nav.analytics', 'top-nav', 'analytics', 'organization'],
  [
    'tenant-tenant-agent-configuration',
    'nav.agentConfiguration',
    'top-nav',
    'agent-configuration',
    'agents-extensions',
  ],
  [
    'tenant-tenant-agent-definitions',
    'nav.agentDefinitions',
    'top-nav',
    'agent-definitions',
    'agents-extensions',
  ],
  [
    'tenant-tenant-agent-bindings',
    'nav.agentBindings',
    'top-nav',
    'agent-bindings',
    'agents-extensions',
  ],
  ['tenant-tenant-skills', 'nav.skills', 'top-nav', 'skills', 'agents-extensions'],
  ['tenant-tenant-evolution', 'nav.evolution', 'top-nav', 'evolution', 'agents-extensions'],
  ['tenant-tenant-patterns', 'nav.patterns', 'top-nav', 'patterns', 'agents-extensions'],
  ['tenant-tenant-plugins', 'nav.plugins', 'overflow', 'plugins', 'agents-extensions'],
  ['tenant-tenant-mcp-servers', 'nav.mcpServers', 'overflow', 'mcp-servers', 'agents-extensions'],
  ['tenant-tenant-acp', 'nav.acp', 'overflow', 'acp', 'agents-extensions'],
  ['tenant-tenant-templates', 'nav.templates', 'overflow', 'templates', 'agents-extensions'],
  ['tenant-tenant-providers', 'nav.providers', 'overflow', 'providers', 'agents-extensions'],
  ['tenant-tenant-webhooks', 'nav.webhooks', 'overflow', 'webhooks', 'agents-extensions'],
  ['tenant-tenant-runtimes', 'nav.runtimes', 'overflow', 'runtimes', 'workspaces-runtime'],
  ['tenant-tenant-pool', 'nav.pool', 'overflow', 'pool', 'workspaces-runtime'],
  ['tenant-tenant-instances', 'nav.instances', 'overflow', 'instances', 'workspaces-runtime'],
  ['tenant-tenant-clusters', 'nav.clusters', 'overflow', 'clusters', 'workspaces-runtime'],
  ['tenant-tenant-deploy', 'nav.deploy', 'overflow', 'deploy', 'workspaces-runtime'],
  [
    'tenant-tenant-instance-templates',
    'nav.instanceTemplates',
    'overflow',
    'instance-templates',
    'workspaces-runtime',
  ],
  ['tenant-tenant-genes', 'nav.genes', 'overflow', 'genes', 'agents-extensions'],
  ['tenant-tenant-users', 'nav.users', 'overflow', 'users', 'organization'],
  ['tenant-tenant-audit-logs', 'nav.auditLogs', 'overflow', 'audit-logs', 'organization'],
  ['tenant-tenant-events', 'nav.events', 'overflow', 'events', 'organization'],
  [
    'tenant-tenant-dead-letter-queue',
    'nav.deadLetterQueue',
    'overflow',
    'dead-letter-queue',
    'organization',
  ],
  [
    'tenant-tenant-trust-policies',
    'nav.trustPolicies',
    'overflow',
    'trust-policies',
    'organization',
  ],
  [
    'tenant-tenant-decision-records',
    'nav.decisionRecords',
    'overflow',
    'decision-records',
    'organization',
  ],
  ['tenant-tenant-billing', 'nav.billing', 'overflow', 'billing', 'organization'],
  ['tenant-tenant-org-settings', 'nav.orgSettings', 'overflow', 'org-settings', 'organization'],
  ['tenant-tenant-settings', 'nav.settings', 'overflow', 'settings', 'organization'],
  ['project-project-overview', 'nav.overview', 'top-nav', 'overview', 'workspaces-runtime'],
  ['project-project-workspaces', 'nav.workspaces', 'top-nav', 'workspaces', 'workspaces-runtime'],
  [
    'project-blackboard-dynamic-project-blackboard',
    'nav.blackboard',
    'top-nav',
    'blackboard',
    'tasks-automation',
  ],
  ['project-project-team', 'nav.team', 'top-nav', 'team', 'organization'],
  ['project-project-memories', 'nav.memories', 'top-nav', 'memories', 'knowledge-memory'],
  ['project-project-entities', 'nav.entities', 'top-nav', 'entities', 'knowledge-memory'],
  ['project-project-communities', 'nav.communities', 'top-nav', 'communities', 'knowledge-memory'],
  ['project-project-graph', 'nav.knowledgeGraph', 'top-nav', 'graph', 'knowledge-memory'],
  ['project-project-search', 'nav.deepSearch', 'overflow', 'search', 'knowledge-memory'],
  ['project-project-schema', 'nav.schema', 'overflow', 'schema', 'knowledge-memory'],
  ['project-project-channels', 'nav.channels', 'overflow', 'channels', 'agents-extensions'],
  ['project-project-maintenance', 'nav.maintenance', 'overflow', 'maintenance', 'knowledge-memory'],
  ['project-project-cron-jobs', 'nav.cronJobs', 'overflow', 'cron-jobs', 'tasks-automation'],
  ['project-project-settings', 'nav.settings', 'overflow', 'settings', 'organization'],
  ['project-agent-dashboard', 'Dashboard', 'top-nav', 'dashboard', 'agents-extensions'],
  ['project-agent-logs', 'Activity Logs', 'top-nav', 'logs', 'agents-extensions'],
  ['project-agent-patterns', 'Patterns', 'top-nav', 'patterns', 'agents-extensions'],
] as const satisfies readonly NavigationMetadataTuple[];

export const CANONICAL_DESKTOP_NAVIGATION_METADATA: readonly CanonicalDesktopNavigationMetadata[] =
  Object.freeze(
    NAVIGATION_METADATA.map(([routeId, labelKey, displayRole, alias, groupId]) => ({
      routeId,
      groupId,
      labelKey,
      descriptionKey: 'featureDirectory.routeDescription' as const,
      displayRole,
      aliases: Object.freeze([alias]),
    })),
  );

export const DESKTOP_AUXILIARY_NAVIGATION_METADATA: readonly DesktopNavigationMetadata[] =
  Object.freeze([
    Object.freeze({
      routeId: 'backend-stores',
      groupId: 'workspaces-runtime',
      labelKey: 'backendStores.title',
      descriptionKey: 'backendStores.subtitle',
      displayRole: 'overflow',
      aliases: Object.freeze(['backend-stores']),
    }),
    Object.freeze({
      routeId: 'project-playbooks',
      groupId: 'tasks-automation',
      labelKey: 'projectPlaybooks.title',
      descriptionKey: 'projectPlaybooks.subtitle',
      displayRole: 'overflow',
      aliases: Object.freeze(['project-playbooks', 'playbooks']),
    }),
    Object.freeze({
      routeId: 'project-support',
      groupId: 'organization',
      labelKey: 'projectSupport.title',
      descriptionKey: 'projectSupport.subtitle',
      displayRole: 'overflow',
      aliases: Object.freeze(['project-support', 'support']),
    }),
  ]);

export const DESKTOP_NAVIGATION_METADATA: readonly DesktopNavigationMetadata[] = Object.freeze([
  ...CANONICAL_DESKTOP_NAVIGATION_METADATA,
  ...DESKTOP_AUXILIARY_NAVIGATION_METADATA,
]);
