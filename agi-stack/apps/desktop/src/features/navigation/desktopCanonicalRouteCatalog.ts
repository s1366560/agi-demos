import {
  createDesktopRouteRegistry,
  type DesktopRouteDefinition,
  type DesktopRouteLoader,
  type DesktopRouteLocalPolicy,
  type DesktopRouteRegistry,
  type DesktopRouteScope,
} from './desktopRouteRegistry';

import routeEntryPermissionCatalog from '../../../contracts/desktop-web-parity/parity-route-entry-permissions.v2.json';

type CanonicalRouteMetadata = readonly [
  id: string,
  path: string,
  scope: readonly DesktopRouteScope[],
  navGroup: string,
  localPolicy: DesktopRouteLocalPolicy,
];

const CANONICAL_ROUTE_METADATA = [
  [
    'agent-workspace-tenant-agent-workspace',
    '/tenant/:tenantId/agent-workspace',
    ['tenant'],
    'tenant-core-operations',
    'native_equivalent',
  ],
  [
    'tenant-tenant-overview',
    '/tenant/:tenantId/overview',
    ['tenant'],
    'tenant-core-operations',
    'native_equivalent',
  ],
  [
    'tenant-tenant-projects',
    '/tenant/:tenantId/projects',
    ['tenant'],
    'tenant-core-operations',
    'native_equivalent',
  ],
  [
    'tenant-tenant-workspaces',
    '/tenant/:tenantId/workspaces',
    ['tenant', 'workspace'],
    'tenant-core-operations',
    'native_equivalent',
  ],
  [
    'tenant-tenant-tasks',
    '/tenant/:tenantId/tasks',
    ['tenant'],
    'tenant-core-operations',
    'native_equivalent',
  ],
  [
    'tenant-tenant-analytics',
    '/tenant/:tenantId/analytics',
    ['tenant'],
    'tenant-core-operations',
    'native_equivalent',
  ],
  [
    'tenant-tenant-agent-configuration',
    '/tenant/:tenantId/agents',
    ['tenant'],
    'tenant-agent-building',
    'native_equivalent',
  ],
  [
    'tenant-tenant-agent-definitions',
    '/tenant/:tenantId/agent-definitions',
    ['tenant'],
    'tenant-agent-building',
    'native_equivalent',
  ],
  [
    'tenant-tenant-agent-bindings',
    '/tenant/:tenantId/agent-bindings',
    ['tenant'],
    'tenant-agent-building',
    'native_equivalent',
  ],
  [
    'tenant-tenant-skills',
    '/tenant/:tenantId/skills',
    ['tenant'],
    'tenant-agent-building',
    'native_equivalent',
  ],
  [
    'tenant-tenant-evolution',
    '/tenant/:tenantId/evolution',
    ['tenant'],
    'tenant-agent-building',
    'native_equivalent',
  ],
  [
    'tenant-tenant-patterns',
    '/tenant/:tenantId/patterns',
    ['tenant'],
    'tenant-agent-building',
    'native_equivalent',
  ],
  [
    'tenant-tenant-plugins',
    '/tenant/:tenantId/plugins',
    ['tenant'],
    'tenant-extensions-integrations',
    'native_equivalent',
  ],
  [
    'tenant-tenant-mcp-servers',
    '/tenant/:tenantId/mcp-servers',
    ['tenant'],
    'tenant-extensions-integrations',
    'native_equivalent',
  ],
  [
    'tenant-tenant-acp',
    '/tenant/:tenantId/acp',
    ['tenant'],
    'tenant-extensions-integrations',
    'cloud_only',
  ],
  [
    'tenant-tenant-templates',
    '/tenant/:tenantId/templates',
    ['tenant'],
    'tenant-extensions-integrations',
    'native_equivalent',
  ],
  [
    'tenant-tenant-providers',
    '/tenant/:tenantId/providers',
    ['tenant'],
    'tenant-extensions-integrations',
    'native_equivalent',
  ],
  [
    'tenant-tenant-webhooks',
    '/tenant/:tenantId/webhooks',
    ['tenant'],
    'tenant-extensions-integrations',
    'cloud_only',
  ],
  [
    'tenant-tenant-runtimes',
    '/tenant/:tenantId/runtimes',
    ['tenant', 'global'],
    'tenant-runtime-infrastructure',
    'native_equivalent',
  ],
  [
    'tenant-tenant-pool',
    '/tenant/:tenantId/pool',
    ['tenant', 'global'],
    'tenant-runtime-infrastructure',
    'cloud_only',
  ],
  [
    'tenant-tenant-instances',
    '/tenant/:tenantId/instances',
    ['tenant', 'instance'],
    'tenant-runtime-infrastructure',
    'native_equivalent',
  ],
  [
    'tenant-tenant-clusters',
    '/tenant/:tenantId/clusters',
    ['tenant'],
    'tenant-runtime-infrastructure',
    'cloud_only',
  ],
  [
    'tenant-tenant-deploy',
    '/tenant/:tenantId/deploy',
    ['tenant', 'instance'],
    'tenant-runtime-infrastructure',
    'cloud_only',
  ],
  [
    'tenant-tenant-instance-templates',
    '/tenant/:tenantId/instance-templates',
    ['tenant'],
    'tenant-runtime-infrastructure',
    'native_equivalent',
  ],
  [
    'tenant-tenant-genes',
    '/tenant/:tenantId/genes',
    ['tenant', 'instance'],
    'tenant-runtime-infrastructure',
    'native_equivalent',
  ],
  [
    'tenant-tenant-users',
    '/tenant/:tenantId/users',
    ['tenant'],
    'tenant-governance-management',
    'cloud_only',
  ],
  [
    'tenant-tenant-audit-logs',
    '/tenant/:tenantId/audit-logs',
    ['tenant'],
    'tenant-governance-management',
    'cloud_only',
  ],
  [
    'tenant-tenant-events',
    '/tenant/:tenantId/events',
    ['tenant'],
    'tenant-governance-management',
    'native_equivalent',
  ],
  [
    'tenant-tenant-dead-letter-queue',
    '/tenant/:tenantId/dead-letter-queue',
    ['tenant'],
    'tenant-governance-management',
    'cloud_only',
  ],
  [
    'tenant-tenant-trust-policies',
    '/tenant/:tenantId/trust-policies',
    ['tenant'],
    'tenant-governance-management',
    'cloud_only',
  ],
  [
    'tenant-tenant-decision-records',
    '/tenant/:tenantId/decision-records',
    ['tenant'],
    'tenant-governance-management',
    'cloud_only',
  ],
  [
    'tenant-tenant-billing',
    '/tenant/:tenantId/billing',
    ['tenant'],
    'tenant-governance-management',
    'cloud_only',
  ],
  [
    'tenant-tenant-org-settings',
    '/tenant/:tenantId/org-settings/info',
    ['tenant'],
    'tenant-governance-management',
    'cloud_only',
  ],
  [
    'tenant-tenant-settings',
    '/tenant/:tenantId/settings',
    ['tenant'],
    'tenant-governance-management',
    'cloud_only',
  ],
  [
    'project-project-overview',
    '/tenant/:tenantId/project/:projectId',
    ['tenant', 'project'],
    'project-workspace',
    'native_equivalent',
  ],
  [
    'project-project-workspaces',
    '/tenant/:tenantId/project/:projectId/workspaces',
    ['tenant', 'project', 'workspace'],
    'project-workspace',
    'native_equivalent',
  ],
  [
    'project-blackboard-dynamic-project-blackboard',
    '/tenant/:tenantId/project/:projectId/blackboard',
    ['tenant', 'project', 'workspace'],
    'project-workspace',
    'native_equivalent',
  ],
  [
    'project-project-team',
    '/tenant/:tenantId/project/:projectId/team',
    ['tenant', 'project'],
    'project-workspace',
    'native_equivalent',
  ],
  [
    'project-project-memories',
    '/tenant/:tenantId/project/:projectId/memories',
    ['tenant', 'project'],
    'project-knowledge-base',
    'native_equivalent',
  ],
  [
    'project-project-entities',
    '/tenant/:tenantId/project/:projectId/entities',
    ['tenant', 'project'],
    'project-knowledge-base',
    'native_equivalent',
  ],
  [
    'project-project-communities',
    '/tenant/:tenantId/project/:projectId/communities',
    ['tenant', 'project'],
    'project-knowledge-base',
    'native_equivalent',
  ],
  [
    'project-project-graph',
    '/tenant/:tenantId/project/:projectId/graph',
    ['tenant', 'project'],
    'project-knowledge-base',
    'native_equivalent',
  ],
  [
    'project-project-search',
    '/tenant/:tenantId/project/:projectId/advanced-search',
    ['tenant', 'project'],
    'project-discovery',
    'native_equivalent',
  ],
  [
    'project-project-schema',
    '/tenant/:tenantId/project/:projectId/schema',
    ['tenant', 'project'],
    'project-configuration',
    'native_equivalent',
  ],
  [
    'project-project-channels',
    '/tenant/:tenantId/project/:projectId/channels',
    ['tenant', 'project'],
    'project-configuration',
    'native_equivalent',
  ],
  [
    'project-project-maintenance',
    '/tenant/:tenantId/project/:projectId/maintenance',
    ['tenant', 'project'],
    'project-configuration',
    'native_equivalent',
  ],
  [
    'project-project-cron-jobs',
    '/tenant/:tenantId/project/:projectId/cron-jobs',
    ['tenant', 'project'],
    'project-configuration',
    'native_equivalent',
  ],
  [
    'project-project-settings',
    '/tenant/:tenantId/project/:projectId/settings',
    ['tenant', 'project'],
    'project-configuration',
    'native_equivalent',
  ],
  [
    'project-agent-dashboard',
    '/tenant/:tenantId/project/:projectId/agent',
    ['tenant', 'project'],
    'project-workspace',
    'blocked_by_web_contract',
  ],
  [
    'project-agent-logs',
    '/tenant/:tenantId/project/:projectId/agent/logs',
    ['tenant', 'project'],
    'project-workspace',
    'blocked_by_web_contract',
  ],
  [
    'project-agent-patterns',
    '/tenant/:tenantId/project/:projectId/agent/patterns',
    ['tenant', 'project'],
    'project-workspace',
    'blocked_by_web_contract',
  ],
] as const satisfies readonly CanonicalRouteMetadata[];

export type CanonicalDesktopRouteId =
  (typeof CANONICAL_ROUTE_METADATA)[number][0];

export const CANONICAL_DESKTOP_ROUTE_IDS: readonly CanonicalDesktopRouteId[] =
  Object.freeze(CANONICAL_ROUTE_METADATA.map(([id]) => id));

const CANONICAL_DESKTOP_ROUTE_ID_SET = new Set<string>(
  CANONICAL_DESKTOP_ROUTE_IDS,
);
const ROUTE_ENTRY_PERMISSION_BY_ID = new Map(
  routeEntryPermissionCatalog.capabilities.map((capability) => [
    capability.id,
    capability.route_entry_permissions,
  ]),
);

export function createDesktopCanonicalRouteCatalog<TModule>(
  loaders: Readonly<Record<string, unknown>>,
): DesktopRouteRegistry<TModule> {
  if (
    ROUTE_ENTRY_PERMISSION_BY_ID.size !==
      routeEntryPermissionCatalog.capabilities.length ||
    ROUTE_ENTRY_PERMISSION_BY_ID.size !== CANONICAL_DESKTOP_ROUTE_IDS.length
  ) {
    throw new Error('desktop_route_entry_permission_catalog_invalid');
  }
  for (const id of Object.keys(loaders)) {
    if (!CANONICAL_DESKTOP_ROUTE_ID_SET.has(id)) {
      throw new Error(`desktop_route_loader_unknown:${id}`);
    }
  }
  for (const id of CANONICAL_DESKTOP_ROUTE_IDS) {
    if (!ROUTE_ENTRY_PERMISSION_BY_ID.has(id)) {
      throw new Error(`desktop_route_entry_permission_missing:${id}`);
    }
    if (!Object.hasOwn(loaders, id)) {
      throw new Error(`desktop_route_loader_missing:${id}`);
    }
    if (typeof loaders[id] !== 'function') {
      throw new Error(`desktop_route_loader_invalid:${id}`);
    }
  }

  const definitions = CANONICAL_ROUTE_METADATA.map(
    ([id, path, scope, navGroup, localPolicy]) =>
      ({
        id,
        path,
        scope,
        navGroup,
        capability: id,
        requiredPermission: routeEntryPermissions(id),
        localPolicy,
        loader: loaders[id] as DesktopRouteLoader<TModule>,
      }) satisfies DesktopRouteDefinition<TModule>,
  );
  return createDesktopRouteRegistry(definitions);
}

function routeEntryPermissions(
  id: CanonicalDesktopRouteId,
): readonly (readonly string[])[] {
  const requirements = ROUTE_ENTRY_PERMISSION_BY_ID.get(id);
  if (!requirements) {
    throw new Error(`desktop_route_entry_permission_missing:${id}`);
  }
  return requirements.map((requirement) => [
    requirement.authentication,
    ...requirement.authorization,
  ]);
}
