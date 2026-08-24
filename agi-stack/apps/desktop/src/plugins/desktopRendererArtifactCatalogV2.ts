import {
  createAppAuxiliaryRouteRegistry,
  createAppProjectAdministrationRouteRegistry,
  createAppProjectAgentRouteRegistry,
  createAppProjectDiscoveryRouteRegistry,
  createAppProjectKnowledgeRouteRegistry,
  createAppProjectWorkspaceRouteRegistry,
  createAppRouteRegistry,
  createAppRuntimeInfrastructureRouteRegistry,
  createAppTenantAgentBuildingRouteRegistry,
  createAppTenantCoreRouteRegistry,
  createAppTenantExtensionsIntegrationsRouteRegistry,
  type AppRouteRegistryRefs,
} from '../features/navigation/appRouteRegistry';
import { AGENT_WORKSPACE_ROUTE_ID } from '../features/agent-workspace/agentWorkspaceRouteModule';
import {
  CANONICAL_DESKTOP_NAVIGATION_METADATA,
  DESKTOP_AUXILIARY_NAVIGATION_METADATA,
} from '../features/navigation/desktopCanonicalNavigationCatalog';
import {
  DESKTOP_PRODUCTION_ROUTE_IDS,
  DEVICE_APPROVAL_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
  PROJECT_AGENT_DASHBOARD_ROUTE_ID,
  PROJECT_AGENT_LOGS_ROUTE_ID,
  PROJECT_AGENT_PATTERNS_ROUTE_ID,
  PROJECT_CHANNELS_ROUTE_ID,
  PROJECT_COMMUNITIES_ROUTE_ID,
  PROJECT_CRON_JOBS_ROUTE_ID,
  PROJECT_ENTITIES_ROUTE_ID,
  PROJECT_GRAPH_ROUTE_ID,
  PROJECT_MEMORIES_ROUTE_ID,
  PROJECT_MAINTENANCE_ROUTE_ID,
  PROJECT_BLACKBOARD_ROUTE_ID,
  PROJECT_OVERVIEW_ROUTE_ID,
  PROJECT_SCHEMA_ROUTE_ID,
  PROJECT_SEARCH_ROUTE_ID,
  PROJECT_SETTINGS_ROUTE_ID,
  PROJECT_TEAM_ROUTE_ID,
  PROJECT_WORKSPACES_ROUTE_ID,
  TENANT_CLUSTERS_ROUTE_ID,
  TENANT_ANALYTICS_ROUTE_ID,
  TENANT_ACP_ROUTE_ID,
  TENANT_AGENT_BINDINGS_ROUTE_ID,
  TENANT_AGENT_DASHBOARD_ROUTE_ID,
  TENANT_AGENT_DEFINITIONS_ROUTE_ID,
  TENANT_DEPLOY_ROUTE_ID,
  TENANT_EVOLUTION_ROUTE_ID,
  TENANT_INSTANCES_ROUTE_ID,
  TENANT_INSTANCE_TEMPLATES_ROUTE_ID,
  TENANT_PATTERNS_ROUTE_ID,
  TENANT_POOL_ROUTE_ID,
  TENANT_OVERVIEW_ROUTE_ID,
  TENANT_MCP_SERVERS_ROUTE_ID,
  TENANT_PLUGINS_ROUTE_ID,
  TENANT_PROVIDERS_ROUTE_ID,
  TENANT_PROJECTS_ROUTE_ID,
  TENANT_RUNTIMES_ROUTE_ID,
  TENANT_SKILLS_ROUTE_ID,
  TENANT_TASKS_ROUTE_ID,
  TENANT_TEMPLATES_ROUTE_ID,
  TENANT_WEBHOOKS_ROUTE_ID,
  TENANT_WORKSPACES_ROUTE_ID,
} from '../features/navigation/desktopProductionRouteRegistry';

import type { DesktopRouteModule } from '../features/navigation/desktopRouteModule';
import type { DesktopRouteRegistry } from '../features/navigation/desktopRouteRegistry';
import type { UiSlotDefinition } from './uiSlotRegistry';

type DesktopRendererContributionKindV2 = 'route' | 'navigation' | 'ui-slot';

interface DesktopRendererContributionV2 {
  readonly id: string;
  readonly kind: DesktopRendererContributionKindV2;
  readonly order: number;
  readonly payload: Readonly<Record<string, unknown>>;
  readonly sourceEntryId: string;
}

export const DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2 = 'desktop.routes.production.v1';
export const DESKTOP_AUXILIARY_ROUTE_ARTIFACT_ID_V2 = 'desktop.routes.auxiliary.v1';
export const DESKTOP_PROJECT_KNOWLEDGE_ROUTE_ARTIFACT_ID_V2 = 'desktop.routes.project-knowledge.v1';
export const DESKTOP_PROJECT_AGENT_ROUTE_ARTIFACT_ID_V2 = 'desktop.routes.project-agent.v1';
export const DESKTOP_PROJECT_ADMINISTRATION_ROUTE_ARTIFACT_ID_V2 =
  'desktop.routes.project-administration.v1';
export const DESKTOP_RUNTIME_INFRASTRUCTURE_ROUTE_ARTIFACT_ID_V2 =
  'desktop.routes.runtime-infrastructure.v1';
export const DESKTOP_PROJECT_WORKSPACE_ROUTE_ARTIFACT_ID_V2 =
  'desktop.routes.project-workspace.v1';
export const DESKTOP_PROJECT_DISCOVERY_ROUTE_ARTIFACT_ID_V2 =
  'desktop.routes.project-discovery.v1';
export const DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2 = 'desktop.routes.tenant-core.v1';
export const DESKTOP_TENANT_AGENT_BUILDING_ROUTE_ARTIFACT_ID_V2 =
  'desktop.routes.tenant-agent-building.v1';
export const DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ARTIFACT_ID_V2 =
  'desktop.routes.tenant-extensions-integrations.v1';
export const DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2 = 'desktop.navigation.default.v1';
export const DESKTOP_AUXILIARY_NAVIGATION_ARTIFACT_ID_V2 = 'desktop.navigation.auxiliary.v1';
export const DESKTOP_PROJECT_KNOWLEDGE_NAVIGATION_ARTIFACT_ID_V2 =
  'desktop.navigation.project-knowledge.v1';
export const DESKTOP_PROJECT_AGENT_NAVIGATION_ARTIFACT_ID_V2 =
  'desktop.navigation.project-agent.v1';
export const DESKTOP_PROJECT_ADMINISTRATION_NAVIGATION_ARTIFACT_ID_V2 =
  'desktop.navigation.project-administration.v1';
export const DESKTOP_RUNTIME_INFRASTRUCTURE_NAVIGATION_ARTIFACT_ID_V2 =
  'desktop.navigation.runtime-infrastructure.v1';
export const DESKTOP_PROJECT_WORKSPACE_NAVIGATION_ARTIFACT_ID_V2 =
  'desktop.navigation.project-workspace.v1';
export const DESKTOP_PROJECT_DISCOVERY_NAVIGATION_ARTIFACT_ID_V2 =
  'desktop.navigation.project-discovery.v1';
export const DESKTOP_TENANT_CORE_NAVIGATION_ARTIFACT_ID_V2 =
  'desktop.navigation.tenant-core.v1';
export const DESKTOP_TENANT_AGENT_BUILDING_NAVIGATION_ARTIFACT_ID_V2 =
  'desktop.navigation.tenant-agent-building.v1';
export const DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_NAVIGATION_ARTIFACT_ID_V2 =
  'desktop.navigation.tenant-extensions-integrations.v1';
export const DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2 = 'desktop.ui-slots.default.v1';

const AUTHENTICATION_KERNEL_ROUTE_IDS_V2 = new Set<string>([
  DEVICE_APPROVAL_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
]);
const AUXILIARY_ROUTE_ID_SET_V2 = new Set<string>(
  DESKTOP_AUXILIARY_NAVIGATION_METADATA.map(({ routeId }) => routeId),
);
const AUXILIARY_ROUTE_IDS_V2 = Object.freeze(
  DESKTOP_PRODUCTION_ROUTE_IDS.filter((routeId) => AUXILIARY_ROUTE_ID_SET_V2.has(routeId)),
);
const PROJECT_KNOWLEDGE_ROUTE_ID_SET_V2 = new Set<string>([
  PROJECT_TEAM_ROUTE_ID,
  PROJECT_MEMORIES_ROUTE_ID,
  PROJECT_ENTITIES_ROUTE_ID,
  PROJECT_COMMUNITIES_ROUTE_ID,
  PROJECT_GRAPH_ROUTE_ID,
]);
const PROJECT_KNOWLEDGE_ROUTE_IDS_V2 = Object.freeze(
  DESKTOP_PRODUCTION_ROUTE_IDS.filter((routeId) => PROJECT_KNOWLEDGE_ROUTE_ID_SET_V2.has(routeId)),
);
const PROJECT_AGENT_ROUTE_ID_SET_V2 = new Set<string>([
  PROJECT_AGENT_DASHBOARD_ROUTE_ID,
  PROJECT_AGENT_LOGS_ROUTE_ID,
  PROJECT_AGENT_PATTERNS_ROUTE_ID,
]);
const PROJECT_AGENT_ROUTE_IDS_V2 = Object.freeze(
  DESKTOP_PRODUCTION_ROUTE_IDS.filter((routeId) => PROJECT_AGENT_ROUTE_ID_SET_V2.has(routeId)),
);
const PROJECT_ADMINISTRATION_ROUTE_ID_SET_V2 = new Set<string>([
  PROJECT_SCHEMA_ROUTE_ID,
  PROJECT_CHANNELS_ROUTE_ID,
  PROJECT_MAINTENANCE_ROUTE_ID,
  PROJECT_CRON_JOBS_ROUTE_ID,
  PROJECT_SETTINGS_ROUTE_ID,
]);
const PROJECT_ADMINISTRATION_ROUTE_IDS_V2 = Object.freeze(
  DESKTOP_PRODUCTION_ROUTE_IDS.filter((routeId) =>
    PROJECT_ADMINISTRATION_ROUTE_ID_SET_V2.has(routeId),
  ),
);
const RUNTIME_INFRASTRUCTURE_ROUTE_ID_SET_V2 = new Set<string>([
  TENANT_RUNTIMES_ROUTE_ID,
  TENANT_POOL_ROUTE_ID,
  TENANT_INSTANCES_ROUTE_ID,
  TENANT_CLUSTERS_ROUTE_ID,
  TENANT_DEPLOY_ROUTE_ID,
  TENANT_INSTANCE_TEMPLATES_ROUTE_ID,
]);
const RUNTIME_INFRASTRUCTURE_ROUTE_IDS_V2 = Object.freeze(
  DESKTOP_PRODUCTION_ROUTE_IDS.filter((routeId) =>
    RUNTIME_INFRASTRUCTURE_ROUTE_ID_SET_V2.has(routeId),
  ),
);
const PROJECT_WORKSPACE_ROUTE_ID_SET_V2 = new Set<string>([
  PROJECT_OVERVIEW_ROUTE_ID,
  PROJECT_WORKSPACES_ROUTE_ID,
  PROJECT_BLACKBOARD_ROUTE_ID,
]);
const PROJECT_WORKSPACE_ROUTE_IDS_V2 = Object.freeze(
  DESKTOP_PRODUCTION_ROUTE_IDS.filter((routeId) => PROJECT_WORKSPACE_ROUTE_ID_SET_V2.has(routeId)),
);
const PROJECT_DISCOVERY_ROUTE_ID_SET_V2 = new Set<string>([PROJECT_SEARCH_ROUTE_ID]);
const PROJECT_DISCOVERY_ROUTE_IDS_V2 = Object.freeze(
  DESKTOP_PRODUCTION_ROUTE_IDS.filter((routeId) => PROJECT_DISCOVERY_ROUTE_ID_SET_V2.has(routeId)),
);
const TENANT_CORE_ROUTE_ID_SET_V2 = new Set<string>([
  AGENT_WORKSPACE_ROUTE_ID,
  TENANT_OVERVIEW_ROUTE_ID,
  TENANT_PROJECTS_ROUTE_ID,
  TENANT_WORKSPACES_ROUTE_ID,
  TENANT_TASKS_ROUTE_ID,
  TENANT_ANALYTICS_ROUTE_ID,
]);
const TENANT_CORE_ROUTE_IDS_V2 = Object.freeze(
  DESKTOP_PRODUCTION_ROUTE_IDS.filter((routeId) => TENANT_CORE_ROUTE_ID_SET_V2.has(routeId)),
);
const TENANT_AGENT_BUILDING_ROUTE_ID_SET_V2 = new Set<string>([
  TENANT_AGENT_DASHBOARD_ROUTE_ID,
  TENANT_AGENT_DEFINITIONS_ROUTE_ID,
  TENANT_AGENT_BINDINGS_ROUTE_ID,
  TENANT_SKILLS_ROUTE_ID,
  TENANT_EVOLUTION_ROUTE_ID,
  TENANT_PATTERNS_ROUTE_ID,
]);
const TENANT_AGENT_BUILDING_ROUTE_IDS_V2 = Object.freeze(
  DESKTOP_PRODUCTION_ROUTE_IDS.filter((routeId) =>
    TENANT_AGENT_BUILDING_ROUTE_ID_SET_V2.has(routeId),
  ),
);
const TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ID_SET_V2 = new Set<string>([
  TENANT_PLUGINS_ROUTE_ID,
  TENANT_MCP_SERVERS_ROUTE_ID,
  TENANT_ACP_ROUTE_ID,
  TENANT_TEMPLATES_ROUTE_ID,
  TENANT_PROVIDERS_ROUTE_ID,
  TENANT_WEBHOOKS_ROUTE_ID,
]);
const TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_IDS_V2 = Object.freeze(
  DESKTOP_PRODUCTION_ROUTE_IDS.filter((routeId) =>
    TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ID_SET_V2.has(routeId),
  ),
);
const DEFAULT_BUSINESS_ROUTE_IDS_V2 = Object.freeze(
  DESKTOP_PRODUCTION_ROUTE_IDS.filter(
    (routeId) =>
      !AUTHENTICATION_KERNEL_ROUTE_IDS_V2.has(routeId) &&
      !AUXILIARY_ROUTE_ID_SET_V2.has(routeId) &&
      !PROJECT_KNOWLEDGE_ROUTE_ID_SET_V2.has(routeId) &&
      !PROJECT_AGENT_ROUTE_ID_SET_V2.has(routeId) &&
      !PROJECT_ADMINISTRATION_ROUTE_ID_SET_V2.has(routeId) &&
      !RUNTIME_INFRASTRUCTURE_ROUTE_ID_SET_V2.has(routeId) &&
      !PROJECT_WORKSPACE_ROUTE_ID_SET_V2.has(routeId) &&
      !PROJECT_DISCOVERY_ROUTE_ID_SET_V2.has(routeId) &&
      !TENANT_CORE_ROUTE_ID_SET_V2.has(routeId) &&
      !TENANT_AGENT_BUILDING_ROUTE_ID_SET_V2.has(routeId) &&
      !TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ID_SET_V2.has(routeId),
  ),
);
const DEFAULT_NAVIGATION_ROUTE_IDS_V2 = Object.freeze([
  ...CANONICAL_DESKTOP_NAVIGATION_METADATA.filter(
    ({ routeId }) =>
      !PROJECT_KNOWLEDGE_ROUTE_ID_SET_V2.has(routeId) &&
      !PROJECT_AGENT_ROUTE_ID_SET_V2.has(routeId) &&
      !PROJECT_ADMINISTRATION_ROUTE_ID_SET_V2.has(routeId) &&
      !RUNTIME_INFRASTRUCTURE_ROUTE_ID_SET_V2.has(routeId) &&
      !PROJECT_WORKSPACE_ROUTE_ID_SET_V2.has(routeId) &&
      !PROJECT_DISCOVERY_ROUTE_ID_SET_V2.has(routeId) &&
      !TENANT_CORE_ROUTE_ID_SET_V2.has(routeId) &&
      !TENANT_AGENT_BUILDING_ROUTE_ID_SET_V2.has(routeId) &&
      !TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ID_SET_V2.has(routeId),
  ).map(({ routeId }) => routeId),
]);
const AUXILIARY_NAVIGATION_ROUTE_IDS_V2 = Object.freeze([
  ...DESKTOP_AUXILIARY_NAVIGATION_METADATA.map(({ routeId }) => routeId),
]);
const PROJECT_KNOWLEDGE_NAVIGATION_ROUTE_IDS_V2 = Object.freeze([
  ...CANONICAL_DESKTOP_NAVIGATION_METADATA.filter(({ routeId }) =>
    PROJECT_KNOWLEDGE_ROUTE_ID_SET_V2.has(routeId),
  ).map(({ routeId }) => routeId),
]);
const PROJECT_AGENT_NAVIGATION_ROUTE_IDS_V2 = Object.freeze([
  ...CANONICAL_DESKTOP_NAVIGATION_METADATA.filter(({ routeId }) =>
    PROJECT_AGENT_ROUTE_ID_SET_V2.has(routeId),
  ).map(({ routeId }) => routeId),
]);
const PROJECT_ADMINISTRATION_NAVIGATION_ROUTE_IDS_V2 = Object.freeze([
  ...CANONICAL_DESKTOP_NAVIGATION_METADATA.filter(({ routeId }) =>
    PROJECT_ADMINISTRATION_ROUTE_ID_SET_V2.has(routeId),
  ).map(({ routeId }) => routeId),
]);
const RUNTIME_INFRASTRUCTURE_NAVIGATION_ROUTE_IDS_V2 = Object.freeze([
  ...CANONICAL_DESKTOP_NAVIGATION_METADATA.filter(({ routeId }) =>
    RUNTIME_INFRASTRUCTURE_ROUTE_ID_SET_V2.has(routeId),
  ).map(({ routeId }) => routeId),
]);
const PROJECT_WORKSPACE_NAVIGATION_ROUTE_IDS_V2 = Object.freeze([
  ...CANONICAL_DESKTOP_NAVIGATION_METADATA.filter(({ routeId }) =>
    PROJECT_WORKSPACE_ROUTE_ID_SET_V2.has(routeId),
  ).map(({ routeId }) => routeId),
]);
const PROJECT_DISCOVERY_NAVIGATION_ROUTE_IDS_V2 = Object.freeze([
  ...CANONICAL_DESKTOP_NAVIGATION_METADATA.filter(({ routeId }) =>
    PROJECT_DISCOVERY_ROUTE_ID_SET_V2.has(routeId),
  ).map(({ routeId }) => routeId),
]);
const TENANT_CORE_NAVIGATION_ROUTE_IDS_V2 = Object.freeze([
  ...CANONICAL_DESKTOP_NAVIGATION_METADATA.filter(({ routeId }) =>
    TENANT_CORE_ROUTE_ID_SET_V2.has(routeId),
  ).map(({ routeId }) => routeId),
]);
const TENANT_AGENT_BUILDING_NAVIGATION_ROUTE_IDS_V2 = Object.freeze([
  ...CANONICAL_DESKTOP_NAVIGATION_METADATA.filter(({ routeId }) =>
    TENANT_AGENT_BUILDING_ROUTE_ID_SET_V2.has(routeId),
  ).map(({ routeId }) => routeId),
]);
const TENANT_EXTENSIONS_INTEGRATIONS_NAVIGATION_ROUTE_IDS_V2 = Object.freeze([
  ...CANONICAL_DESKTOP_NAVIGATION_METADATA.filter(({ routeId }) =>
    TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ID_SET_V2.has(routeId),
  ).map(({ routeId }) => routeId),
]);
const DEFAULT_UI_SLOT_DEFINITIONS_V2: readonly UiSlotDefinition[] = Object.freeze([
  Object.freeze({
    pluginId: 'builtin-ui',
    slot: 'settings_page',
    id: 'plugin-settings',
    contract: 'ui-builtin:plugin-settings',
    moduleRef: 'builtin:plugin-settings',
    permission: 'ui.settings.plugins',
    sandbox: true,
  }),
  Object.freeze({
    pluginId: 'builtin-ui',
    slot: 'tool_result_renderer',
    id: 'structured-tool-result',
    contract: 'ui-builtin:structured-tool-result',
    moduleRef: 'builtin:structured-tool-result',
    permission: 'ui.render',
    sandbox: true,
  }),
]);

interface DesktopRendererArtifactBaseV2 {
  readonly id: string;
  readonly kind: DesktopRendererContributionKindV2;
}

export interface DesktopRouteArtifactV2 extends DesktopRendererArtifactBaseV2 {
  readonly createRegistry: (refs: AppRouteRegistryRefs) => DesktopRouteRegistry<DesktopRouteModule>;
  readonly kind: 'route';
  readonly routeIds: readonly string[];
}

export interface DesktopNavigationArtifactV2 extends DesktopRendererArtifactBaseV2 {
  readonly discoveryRouteIds: readonly string[];
  readonly kind: 'navigation';
  readonly routeIds: readonly string[];
}

export interface DesktopUiSlotArtifactV2 extends DesktopRendererArtifactBaseV2 {
  readonly kind: 'ui-slot';
  readonly slotDefinitions: readonly UiSlotDefinition[];
}

export type DesktopRendererArtifactV2 =
  | DesktopRouteArtifactV2
  | DesktopNavigationArtifactV2
  | DesktopUiSlotArtifactV2;

export class DesktopRendererArtifactErrorV2 extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'DesktopRendererArtifactErrorV2';
  }
}

const DESKTOP_RENDERER_ARTIFACT_CATALOG_V2 = new Map<string, DesktopRendererArtifactV2>([
  [
    DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2,
    defineDesktopRouteArtifactV2(
      DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2,
      DEFAULT_BUSINESS_ROUTE_IDS_V2,
      createAppRouteRegistry,
    ),
  ],
  [
    DESKTOP_AUXILIARY_ROUTE_ARTIFACT_ID_V2,
    defineDesktopRouteArtifactV2(
      DESKTOP_AUXILIARY_ROUTE_ARTIFACT_ID_V2,
      AUXILIARY_ROUTE_IDS_V2,
      createAppAuxiliaryRouteRegistry,
    ),
  ],
  [
    DESKTOP_PROJECT_KNOWLEDGE_ROUTE_ARTIFACT_ID_V2,
    defineDesktopRouteArtifactV2(
      DESKTOP_PROJECT_KNOWLEDGE_ROUTE_ARTIFACT_ID_V2,
      PROJECT_KNOWLEDGE_ROUTE_IDS_V2,
      createAppProjectKnowledgeRouteRegistry,
    ),
  ],
  [
    DESKTOP_PROJECT_AGENT_ROUTE_ARTIFACT_ID_V2,
    defineDesktopRouteArtifactV2(
      DESKTOP_PROJECT_AGENT_ROUTE_ARTIFACT_ID_V2,
      PROJECT_AGENT_ROUTE_IDS_V2,
      createAppProjectAgentRouteRegistry,
    ),
  ],
  [
    DESKTOP_PROJECT_ADMINISTRATION_ROUTE_ARTIFACT_ID_V2,
    defineDesktopRouteArtifactV2(
      DESKTOP_PROJECT_ADMINISTRATION_ROUTE_ARTIFACT_ID_V2,
      PROJECT_ADMINISTRATION_ROUTE_IDS_V2,
      createAppProjectAdministrationRouteRegistry,
    ),
  ],
  [
    DESKTOP_RUNTIME_INFRASTRUCTURE_ROUTE_ARTIFACT_ID_V2,
    defineDesktopRouteArtifactV2(
      DESKTOP_RUNTIME_INFRASTRUCTURE_ROUTE_ARTIFACT_ID_V2,
      RUNTIME_INFRASTRUCTURE_ROUTE_IDS_V2,
      createAppRuntimeInfrastructureRouteRegistry,
    ),
  ],
  [
    DESKTOP_PROJECT_WORKSPACE_ROUTE_ARTIFACT_ID_V2,
    defineDesktopRouteArtifactV2(
      DESKTOP_PROJECT_WORKSPACE_ROUTE_ARTIFACT_ID_V2,
      PROJECT_WORKSPACE_ROUTE_IDS_V2,
      createAppProjectWorkspaceRouteRegistry,
    ),
  ],
  [
    DESKTOP_PROJECT_DISCOVERY_ROUTE_ARTIFACT_ID_V2,
    defineDesktopRouteArtifactV2(
      DESKTOP_PROJECT_DISCOVERY_ROUTE_ARTIFACT_ID_V2,
      PROJECT_DISCOVERY_ROUTE_IDS_V2,
      createAppProjectDiscoveryRouteRegistry,
    ),
  ],
  [
    DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2,
    defineDesktopRouteArtifactV2(
      DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2,
      TENANT_CORE_ROUTE_IDS_V2,
      createAppTenantCoreRouteRegistry,
    ),
  ],
  [
    DESKTOP_TENANT_AGENT_BUILDING_ROUTE_ARTIFACT_ID_V2,
    defineDesktopRouteArtifactV2(
      DESKTOP_TENANT_AGENT_BUILDING_ROUTE_ARTIFACT_ID_V2,
      TENANT_AGENT_BUILDING_ROUTE_IDS_V2,
      createAppTenantAgentBuildingRouteRegistry,
    ),
  ],
  [
    DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ARTIFACT_ID_V2,
    defineDesktopRouteArtifactV2(
      DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ARTIFACT_ID_V2,
      TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_IDS_V2,
      createAppTenantExtensionsIntegrationsRouteRegistry,
    ),
  ],
  [
    DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      discoveryRouteIds: DEFAULT_NAVIGATION_ROUTE_IDS_V2,
      id: DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
      routeIds: DEFAULT_NAVIGATION_ROUTE_IDS_V2,
    }),
  ],
  [
    DESKTOP_AUXILIARY_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      discoveryRouteIds: AUXILIARY_NAVIGATION_ROUTE_IDS_V2,
      id: DESKTOP_AUXILIARY_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
      routeIds: AUXILIARY_NAVIGATION_ROUTE_IDS_V2,
    }),
  ],
  [
    DESKTOP_PROJECT_KNOWLEDGE_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      discoveryRouteIds: PROJECT_KNOWLEDGE_NAVIGATION_ROUTE_IDS_V2,
      id: DESKTOP_PROJECT_KNOWLEDGE_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
      routeIds: PROJECT_KNOWLEDGE_NAVIGATION_ROUTE_IDS_V2,
    }),
  ],
  [
    DESKTOP_PROJECT_AGENT_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      discoveryRouteIds: PROJECT_AGENT_NAVIGATION_ROUTE_IDS_V2,
      id: DESKTOP_PROJECT_AGENT_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
      routeIds: PROJECT_AGENT_NAVIGATION_ROUTE_IDS_V2,
    }),
  ],
  [
    DESKTOP_PROJECT_ADMINISTRATION_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      discoveryRouteIds: PROJECT_ADMINISTRATION_NAVIGATION_ROUTE_IDS_V2,
      id: DESKTOP_PROJECT_ADMINISTRATION_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
      routeIds: PROJECT_ADMINISTRATION_NAVIGATION_ROUTE_IDS_V2,
    }),
  ],
  [
    DESKTOP_RUNTIME_INFRASTRUCTURE_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      discoveryRouteIds: RUNTIME_INFRASTRUCTURE_NAVIGATION_ROUTE_IDS_V2,
      id: DESKTOP_RUNTIME_INFRASTRUCTURE_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
      routeIds: RUNTIME_INFRASTRUCTURE_NAVIGATION_ROUTE_IDS_V2,
    }),
  ],
  [
    DESKTOP_PROJECT_WORKSPACE_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      discoveryRouteIds: PROJECT_WORKSPACE_NAVIGATION_ROUTE_IDS_V2,
      id: DESKTOP_PROJECT_WORKSPACE_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
      routeIds: PROJECT_WORKSPACE_NAVIGATION_ROUTE_IDS_V2,
    }),
  ],
  [
    DESKTOP_PROJECT_DISCOVERY_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      discoveryRouteIds: PROJECT_DISCOVERY_NAVIGATION_ROUTE_IDS_V2,
      id: DESKTOP_PROJECT_DISCOVERY_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
      routeIds: PROJECT_DISCOVERY_NAVIGATION_ROUTE_IDS_V2,
    }),
  ],
  [
    DESKTOP_TENANT_CORE_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      discoveryRouteIds: TENANT_CORE_NAVIGATION_ROUTE_IDS_V2,
      id: DESKTOP_TENANT_CORE_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
      routeIds: TENANT_CORE_NAVIGATION_ROUTE_IDS_V2,
    }),
  ],
  [
    DESKTOP_TENANT_AGENT_BUILDING_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      discoveryRouteIds: TENANT_AGENT_BUILDING_NAVIGATION_ROUTE_IDS_V2,
      id: DESKTOP_TENANT_AGENT_BUILDING_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
      routeIds: TENANT_AGENT_BUILDING_NAVIGATION_ROUTE_IDS_V2,
    }),
  ],
  [
    DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      discoveryRouteIds: TENANT_EXTENSIONS_INTEGRATIONS_NAVIGATION_ROUTE_IDS_V2,
      id: DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
      routeIds: TENANT_EXTENSIONS_INTEGRATIONS_NAVIGATION_ROUTE_IDS_V2,
    }),
  ],
  [
    DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2,
    defineDesktopUiSlotArtifactV2(
      DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2,
      DEFAULT_UI_SLOT_DEFINITIONS_V2,
    ),
  ],
]);

export function defineDesktopRouteArtifactV2(
  id: string,
  routeIds: readonly string[],
  createRegistry: (refs: AppRouteRegistryRefs) => DesktopRouteRegistry<DesktopRouteModule>,
): DesktopRouteArtifactV2 {
  if (!id.trim()) {
    throw artifactErrorV2('desktop_renderer_route_artifact_id_required', id);
  }
  if (routeIds.length === 0 || routeIds.some((routeId) => !routeId.trim())) {
    throw artifactErrorV2('desktop_renderer_route_artifact_routes_invalid', id);
  }
  if (new Set(routeIds).size !== routeIds.length) {
    throw artifactErrorV2('desktop_renderer_route_artifact_routes_duplicate', id);
  }
  return Object.freeze({
    createRegistry,
    id,
    kind: 'route',
    routeIds: Object.freeze([...routeIds]),
  });
}

export function defineDesktopUiSlotArtifactV2(
  id: string,
  slotDefinitions: readonly UiSlotDefinition[],
): DesktopUiSlotArtifactV2 {
  const owners = new Set<string>();
  const definitions = slotDefinitions.map((slot) => {
    const ownerKey = `${slot.pluginId}/${slot.id}`;
    if (owners.has(ownerKey)) {
      throw artifactErrorV2('desktop_renderer_ui_slot_conflict', ownerKey);
    }
    owners.add(ownerKey);
    if (!slot.moduleRef.startsWith('builtin:')) {
      throw artifactErrorV2('desktop_renderer_ui_slot_module_ref_invalid', ownerKey);
    }
    if (!slot.permission.startsWith('ui.')) {
      throw artifactErrorV2('desktop_renderer_ui_slot_permission_invalid', ownerKey);
    }
    if (!slot.sandbox) {
      throw artifactErrorV2('desktop_renderer_ui_slot_sandbox_required', ownerKey);
    }
    return Object.freeze({ ...slot });
  });
  return Object.freeze({
    id,
    kind: 'ui-slot',
    slotDefinitions: Object.freeze(definitions),
  });
}

export function validateDesktopRendererContributionsV2(
  contributions: readonly DesktopRendererContributionV2[],
): void {
  resolveDesktopRendererArtifactsV2(contributions);
}

export function resolveDesktopRendererArtifactsV2(
  contributions: readonly DesktopRendererContributionV2[],
): readonly DesktopRendererArtifactV2[] {
  const artifacts: DesktopRendererArtifactV2[] = [];
  const routeOwners = new Map<string, string>();
  const navigationOwners = new Map<string, string>();
  const uiSlotArtifactOwners = new Map<string, string>();
  const ordered = [...contributions].sort(
    (left, right) =>
      left.order - right.order ||
      `${left.kind}:${left.id}`.localeCompare(`${right.kind}:${right.id}`),
  );

  for (const contribution of ordered) {
    for (const artifactRef of artifactRefsV2(contribution)) {
      const artifact = DESKTOP_RENDERER_ARTIFACT_CATALOG_V2.get(artifactRef);
      if (!artifact) {
        throw artifactErrorV2('desktop_renderer_artifact_unknown', artifactRef);
      }
      if (artifact.kind !== contribution.kind) {
        throw artifactErrorV2(
          'desktop_renderer_artifact_kind_mismatch',
          `${artifactRef}:${contribution.kind}`,
        );
      }
      if (artifact.kind === 'route') {
        validateRouteOwnershipV2(routeOwners, artifact.routeIds, contribution);
      } else if (artifact.kind === 'navigation') {
        validateRouteOwnershipV2(navigationOwners, artifact.routeIds, contribution);
      } else {
        validateUiSlotArtifactOwnershipV2(uiSlotArtifactOwners, artifact, contribution);
      }
      artifacts.push(artifact);
    }
  }

  return Object.freeze(artifacts);
}

function artifactRefsV2(contribution: DesktopRendererContributionV2): readonly string[] {
  const payload = contribution.payload;
  const keys = Object.keys(payload).sort();
  const artifactRefs = payload.artifact_refs;
  if (
    keys.length !== 2 ||
    keys[0] !== 'artifact_refs' ||
    keys[1] !== 'schema_version' ||
    payload.schema_version !== 1 ||
    !Array.isArray(artifactRefs) ||
    artifactRefs.length === 0 ||
    artifactRefs.some((value) => typeof value !== 'string' || value.length === 0) ||
    new Set(artifactRefs).size !== artifactRefs.length
  ) {
    throw artifactErrorV2('desktop_renderer_artifact_payload_invalid', contribution.id);
  }
  return artifactRefs as readonly string[];
}

function validateRouteOwnershipV2(
  owners: Map<string, string>,
  routeIds: readonly string[],
  contribution: DesktopRendererContributionV2,
): void {
  for (const routeId of routeIds) {
    const existingOwner = owners.get(routeId);
    if (existingOwner !== undefined) {
      throw artifactErrorV2(
        'desktop_renderer_route_conflict',
        `${routeId}:${existingOwner}:${contribution.id}`,
      );
    }
    owners.set(routeId, contribution.id);
  }
}

function validateUiSlotArtifactOwnershipV2(
  owners: Map<string, string>,
  artifact: DesktopUiSlotArtifactV2,
  contribution: DesktopRendererContributionV2,
): void {
  const existingOwner = owners.get(artifact.id);
  if (existingOwner !== undefined) {
    throw artifactErrorV2(
      'desktop_renderer_ui_slot_artifact_conflict',
      `${artifact.id}:${existingOwner}:${contribution.id}`,
    );
  }
  owners.set(artifact.id, contribution.id);
}

function artifactErrorV2(code: string, detail: string): DesktopRendererArtifactErrorV2 {
  return new DesktopRendererArtifactErrorV2(code, `${code}:${detail}`);
}
