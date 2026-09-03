import { RuntimeV2Error } from '@agistack/plugin-runtime';

import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import {
  desktopApiFetch,
  desktopVaultBoundCloudRequestBroker,
  type VaultBoundCloudRequestBroker,
} from '../../api/cloudRequestBroker';
import type { DesktopAutomationApi } from '../automations/automationClient';
import {
  automationActionAvailability,
  normalizeAutomationCapabilities,
} from '../automations/automationModel';
import {
  createAgentWorkspaceAuthorityClient,
  type AgentWorkspaceAuthorityClient,
  type AgentWorkspaceAuthorityObservation,
  type AgentWorkspaceAuthorityScope,
} from '../agent-workspace/agentWorkspaceAuthorityClient';
import {
  AGENT_WORKSPACE_JOURNEY_IDS,
  createAgentWorkspaceJourneyAuthorityClient,
  type AgentWorkspaceJourneyAuthorityClient,
  type AgentWorkspaceJourneyObservation,
  type AgentWorkspaceJourneySnapshot,
} from '../agent-workspace/agentWorkspaceJourneyAuthorityClient';
import { deviceApprovalCapability } from '../device-approval/deviceApprovalCapability';
import { tenantCreationCapability } from '../tenant-creation/tenantCreationCapability';
import { invitationAcceptanceCapability } from '../invitation-acceptance/invitationAcceptanceCapability';
import { deadLetterQueueCapability } from '../governance/deadLetterQueueCapability';
import { instanceTemplatesCapability } from '../instance-templates/instanceTemplatesCapability';
import { runtimeDeploymentsCapability } from '../runtime-deployments/runtimeDeploymentsCapability';
import { runtimeInstancesCapability } from '../runtime-instances/runtimeInstancesCapability';
import { createAgentDefinitionsRouteClient } from '../settings-routes/agentDefinitionsRouteClient';
import type { ChannelsRouteClient } from '../settings-routes/channelsRouteClient';
import type { EvolutionRouteClient } from '../settings-routes/evolutionRouteClient';
import {
  managementRouteObservation,
  managementRouteReasonPrefix,
  managementRouteScopeForRuntime,
  requireManagementRouteRuntimeScope,
  type ManagementRouteCapability,
  type ManagementRouteClient,
  type ManagementRouteObservation,
} from '../settings-routes/managementRouteTypes';
import { createMcpServersRouteClient } from '../settings-routes/mcpServersRouteClient';
import { createPluginsRouteClient } from '../settings-routes/pluginsRouteClient';
import {
  createP2ThirdBatchCapabilityClient,
  type P2ThirdBatchCapabilityClient,
  type P2ThirdBatchCapabilityProjection,
} from '../settings-routes/p2ThirdBatchCapabilityClient';
import type { ProfileRouteClient } from '../settings-routes/profileRouteClient';
import { createProviderRouteClient } from '../settings-routes/providerRouteClient';
import { createSkillsRouteClient } from '../settings-routes/skillsRouteClient';
import type { TemplatesRouteClient } from '../settings-routes/templatesRouteClient';
import { unifiedRuntimesCapability } from '../unified-runtimes/unifiedRuntimesCapability';
import type {
  ProjectBlackboardScope,
  ProjectBlackboardSnapshot,
} from '../project-blackboard/projectBlackboardClient';
import {
  createProjectKnowledgeCapabilityClients,
  loadProjectKnowledgeCapabilities,
  type ProjectKnowledgeCapabilityClientOverrides,
} from '../project-knowledge/projectKnowledgeCapabilityAuthority';
import {
  createProjectAgentCapabilityClients,
  loadProjectAgentCapabilities,
} from '../project-agent/projectAgentCapabilityAuthority';
import {
  createProjectAdministrationCapabilityClients,
  loadProjectAdministrationCapabilities,
  type ProjectAdministrationCapabilityClients,
} from '../project-administration/projectAdministrationCapabilityAuthority';
import type {
  ProjectWorkspacesClient,
  ProjectWorkspacesScope,
  ProjectWorkspacesSnapshot,
} from '../project-workspaces/projectWorkspacesClient';
import { projectSupportCapability } from '../project-support/projectSupportCapability';
import { loadTenantAnalyticsCapability } from '../tenant/tenantAnalyticsCapability';
import { loadTenantAgentDashboardCapability } from '../tenant/tenantAgentDashboardCapability';
import { loadTenantAgentBindingsCapability } from '../tenant/tenantAgentBindingsCapability';
import { loadTenantOverviewCapability } from '../tenant/tenantOverviewCapability';
import type { DesktopTenantAnalyticsOperationsV2 } from '../../plugins/desktopTenantAnalyticsAuthorityModuleV2';
import type { DesktopTenantAgentBindingsOperationsV2 } from '../../plugins/desktopTenantAgentBindingsAuthorityModuleV2';
import type { DesktopTenantAgentDashboardOperationsV2 } from '../../plugins/desktopTenantAgentDashboardAuthorityModuleV2';
import type { DesktopTenantOverviewOperationsV2 } from '../../plugins/desktopTenantOverviewAuthorityModuleV2';
import type { DesktopTenantProjectsOperationsV2 } from '../../plugins/desktopTenantProjectsAuthorityModuleV2';
import type { DesktopTenantTasksOperationsV2 } from '../../plugins/desktopTenantTasksAuthorityModuleV2';
import { loadTenantProjectsCapability } from '../tenant/tenantProjectsCapability';
import { loadTenantTasksCapability } from '../tenant/tenantTasksCapability';
import { tenantWorkspacesCapability } from '../tenant/tenantWorkspacesCapability';
import type { TenantAuditClient } from '../tenant-admin/tenantAuditClient';
import {
  createTenantAdminCapabilityClient,
  type TenantAdminCapabilityClient,
} from '../tenant-admin/tenantAdminCapabilityClient';
import type { TenantBillingClient } from '../tenant-admin/tenantBillingClient';
import type { TenantGovernanceClient } from '../tenant-admin/tenantGovernanceClient';
import { type TenantTrustClient } from '../tenant-admin/tenantTrustClient';
import {
  createTenantRemainingCapabilityClient,
  type TenantRemainingCapabilityClient,
} from '../tenant-admin/tenantRemainingCapabilityClient';
import type { DesktopRuntimeConfig } from '../../types';
import type { WorkspaceCollaborationCapabilityScope } from '../workspace/workspaceCollaborationCapabilityContract';
import {
  createDesktopPluginMarketplaceOperationsV2,
  type DesktopPluginMarketplaceCatalogOperationsV2,
} from '../../plugins/desktopPluginMarketplaceAuthorityModulesV2';
import type { DesktopProjectOverviewOperationsV2 } from '../../plugins/desktopProjectOverviewAuthorityModuleV2';
import {
  createDesktopProjectAgentDashboardClientV2,
  type DesktopProjectAgentDashboardOperationsV2,
} from '../../plugins/desktopProjectAgentDashboardAuthorityModuleV2';
import {
  createDesktopProjectAgentLogsClientV2,
  type DesktopProjectAgentLogsOperationsV2,
} from '../../plugins/desktopProjectAgentLogsAuthorityModuleV2';
import {
  createDesktopProjectAgentPatternsClientV2,
  type DesktopProjectAgentPatternsOperationsV2,
} from '../../plugins/desktopProjectAgentPatternsAuthorityModuleV2';
import {
  createDesktopProjectCommunitiesClientV2,
  type DesktopProjectCommunitiesOperationsV2,
} from '../../plugins/desktopProjectCommunitiesAuthorityModuleV2';
import {
  createDesktopProjectEntitiesClientV2,
  type DesktopProjectEntitiesOperationsV2,
} from '../../plugins/desktopProjectEntitiesAuthorityModuleV2';
import {
  createDesktopProjectGraphClientV2,
  type DesktopProjectGraphOperationsV2,
} from '../../plugins/desktopProjectGraphAuthorityModuleV2';
import {
  createDesktopProjectMemoriesClientV2,
  type DesktopProjectMemoriesOperationsV2,
} from '../../plugins/desktopProjectMemoriesAuthorityModuleV2';
import type { DesktopProjectBlackboardOperationsV2 } from '../../plugins/desktopProjectBlackboardAuthorityModuleV2';
import type { DesktopRuntimePoolOperationsV2 } from '../../plugins/desktopRuntimePoolAuthorityModuleV2';
import type { DesktopRuntimeClustersOperationsV2 } from '../../plugins/desktopRuntimeClustersAuthorityModuleV2';
import {
  DESKTOP_CAPABILITY_SNAPSHOT_VERSION,
  DESKTOP_MINIMUM_CONTRACT_VERSION,
  parseDesktopCapabilitySnapshot,
  type DesktopCapabilityAvailability,
  type DesktopCapabilityAuthoritySource,
  type DesktopCapabilityScope,
  type DesktopCapabilitySnapshot,
  type DesktopCapabilitySnapshotEntry,
} from './capabilitySnapshot';
import {
  negotiateCapabilityContract,
  type CapabilityContractNegotiation,
} from './capabilityVersion';

export type DesktopWorkbenchCapabilityClient = {
  loadSnapshot(signal?: AbortSignal): Promise<DesktopCapabilitySnapshot>;
};

export {
  normalizeWorkspaceCollaborationAuthorityContract,
  normalizeWorkspaceCollaborationCapabilityContract,
} from '../workspace/workspaceCollaborationCapabilityContract';

type AuxiliaryCloudCapabilities = Readonly<{
  backendStores: DesktopCapabilityAvailability;
  projectPlaybooks: DesktopCapabilityAvailability;
  cloudAuthorityObserved: boolean;
}>;

type ManagementRouteCapabilityClients = Readonly<
  Record<ManagementRouteCapability, ManagementRouteClient>
>;

export type DesktopWorkbenchCapabilityClientOptions = Readonly<{
  tenantAgentBindingsOperationsV2: Pick<
    DesktopTenantAgentBindingsOperationsV2,
    'listTenantAgentBindings'
  >;
  tenantAgentDashboardOperationsV2: Pick<
    DesktopTenantAgentDashboardOperationsV2,
    'loadTenantAgentDashboard'
  >;
  tenantAnalyticsOperationsV2: Pick<
    DesktopTenantAnalyticsOperationsV2,
    'loadTenantAnalytics'
  >;
  tenantOverviewOperationsV2: Pick<
    DesktopTenantOverviewOperationsV2,
    'loadTenantOverview'
  >;
  tenantProjectsOperationsV2: Pick<
    DesktopTenantProjectsOperationsV2,
    'listTenantProjects'
  >;
  tenantTasksOperationsV2: Pick<DesktopTenantTasksOperationsV2, 'loadTenantTasks'>;
  projectOverviewOperationsV2: Pick<
    DesktopProjectOverviewOperationsV2,
    'probeProjectOverview'
  >;
  projectAgentDashboardOperationsV2: Pick<
    DesktopProjectAgentDashboardOperationsV2,
    'loadProjectAgentDashboard'
  >;
  projectAgentLogsOperationsV2: Pick<
    DesktopProjectAgentLogsOperationsV2,
    'loadProjectAgentLogs'
  >;
  projectAgentPatternsOperationsV2: Pick<
    DesktopProjectAgentPatternsOperationsV2,
    'loadProjectAgentPatterns'
  >;
  projectCommunitiesOperationsV2: Pick<
    DesktopProjectCommunitiesOperationsV2,
    'loadProjectCommunities'
  >;
  projectMemoriesOperationsV2: Pick<
    DesktopProjectMemoriesOperationsV2,
    'loadProjectMemories'
  >;
  projectEntitiesOperationsV2: Pick<
    DesktopProjectEntitiesOperationsV2,
    'loadProjectEntities' | 'loadProjectEntityRelationships'
  >;
  projectGraphOperationsV2: Pick<DesktopProjectGraphOperationsV2, 'loadProjectGraph'>;
  runtimePoolOperationsV2: Pick<DesktopRuntimePoolOperationsV2, 'probeRuntimePool'>;
  runtimeClustersOperationsV2: Pick<
    DesktopRuntimeClustersOperationsV2,
    'probeRuntimeClusters'
  >;
  managementRouteClients?: ManagementRouteCapabilityClients;
  pluginMarketplaceOperationsV2?: Pick<
    DesktopPluginMarketplaceCatalogOperationsV2,
    'projectMarketplacePlugins'
  >;
  agentWorkspaceClient?: AgentWorkspaceAuthorityClient;
  agentWorkspaceJourneyClient?: AgentWorkspaceJourneyAuthorityClient;
  projectWorkspacesClient: Pick<ProjectWorkspacesClient, 'list'>;
  projectBlackboardOperationsV2: Pick<
    DesktopProjectBlackboardOperationsV2,
    'probeProjectBlackboard' | 'probeWorkspaceCollaborationCapability'
  >;
  projectKnowledgeClientOverrides?: ProjectKnowledgeCapabilityClientOverrides;
  projectAdministrationClients?: ProjectAdministrationCapabilityClients;
  tenantGovernanceClient?: Pick<TenantGovernanceClient, 'load'>;
  tenantBillingClient?: Pick<TenantBillingClient, 'load'>;
  tenantAuditClient?: Pick<TenantAuditClient, 'load'>;
  tenantTrustClient?: Pick<TenantTrustClient, 'load'>;
  tenantAdminCapabilityClient?: Pick<TenantAdminCapabilityClient, 'load'>;
  tenantRemainingCapabilityClient?: Pick<TenantRemainingCapabilityClient, 'load'>;
  evolutionRouteClient?: Pick<EvolutionRouteClient, 'observe'>;
  channelsRouteClient?: Pick<ChannelsRouteClient, 'observe'>;
  templatesRouteClient?: Pick<TemplatesRouteClient, 'observe'>;
  profileRouteClient?: Pick<ProfileRouteClient, 'observe'>;
  p2ThirdBatchCapabilityClient?: Pick<P2ThirdBatchCapabilityClient, 'load'>;
  cloudRequestBroker?: VaultBoundCloudRequestBroker | null;
}>;

type AutomationCapabilityAuthority = Pick<DesktopAutomationApi, 'getAutomationCapabilities'>;

type SearchCapabilityDeclaration = {
  endpoint: string;
  parameters?: Readonly<Record<string, string>>;
};

const LOCAL_SEARCH_SUPPORTED_TYPES = ['advanced', 'temporal', 'faceted'] as const;
const LOCAL_SEARCH_UNAVAILABLE_TYPES = ['graph_traversal', 'community'] as const;

const MANAGEMENT_ROUTE_CAPABILITY_NAMES = Object.freeze([
  'tenant-tenant-providers',
  'tenant-tenant-agent-definitions',
  'tenant-tenant-skills',
  'tenant-tenant-plugins',
  'tenant-tenant-mcp-servers',
] as const satisfies readonly ManagementRouteCapability[]);
const MANAGEMENT_ROUTE_SERVICE_VERSION = '0.1.0';
const MANAGEMENT_ROUTE_CONTRACT_VERSION = '4.0.0';
const UNAVAILABLE_PLUGIN_MARKETPLACE_OPERATIONS_V2 =
  createDesktopPluginMarketplaceOperationsV2(() => null);
const PROJECT_WORKSPACES_SERVICE_VERSION = '0.1.0';
const PROJECT_WORKSPACES_CONTRACT_VERSION = '4.0.0';
const PROJECT_BLACKBOARD_SERVICE_VERSION = '0.1.0';
const PROJECT_BLACKBOARD_CONTRACT_VERSION = '4.0.0';

const SEARCH_CONTRACT: Readonly<Record<string, SearchCapabilityDeclaration>> = {
  semantic: { endpoint: '/api/v1/memory/search' },
  advanced: {
    endpoint: '/api/v1/search-enhanced/advanced',
    parameters: {
      query: 'string (required)',
      strategy: 'string (optional)',
      focal_node_uuid: 'string (optional)',
      reranker: 'string (optional)',
      limit: 'integer (1-200)',
      tenant_id: 'string (optional)',
      project_id: 'string (optional)',
      since: 'ISO datetime string (optional)',
    },
  },
  graph_traversal: { endpoint: '/api/v1/search-enhanced/graph-traversal' },
  community: { endpoint: '/api/v1/search-enhanced/community' },
  temporal: { endpoint: '/api/v1/search-enhanced/temporal' },
  faceted: { endpoint: '/api/v1/search-enhanced/faceted' },
} as const;

export function createDesktopWorkbenchCapabilityClient(
  automationApi: AutomationCapabilityAuthority,
  config: DesktopRuntimeConfig,
  options: DesktopWorkbenchCapabilityClientOptions,
): DesktopWorkbenchCapabilityClient {
  const tenantAgentBindingsOperationsV2 = options?.tenantAgentBindingsOperationsV2;
  if (
    typeof tenantAgentBindingsOperationsV2?.listTenantAgentBindings !== 'function'
  ) {
    throw new Error('desktop_tenant_agent_bindings_authority_required');
  }
  const tenantAnalyticsOperationsV2 = options?.tenantAnalyticsOperationsV2;
  if (typeof tenantAnalyticsOperationsV2?.loadTenantAnalytics !== 'function') {
    throw new Error('desktop_tenant_analytics_authority_required');
  }
  const tenantAgentDashboardOperationsV2 = options?.tenantAgentDashboardOperationsV2;
  if (
    typeof tenantAgentDashboardOperationsV2?.loadTenantAgentDashboard !== 'function'
  ) {
    throw new Error('desktop_tenant_agent_dashboard_authority_required');
  }
  const tenantProjectsOperationsV2 = options?.tenantProjectsOperationsV2;
  if (typeof tenantProjectsOperationsV2?.listTenantProjects !== 'function') {
    throw new Error('desktop_tenant_projects_authority_required');
  }
  const tenantTasksOperationsV2 = options?.tenantTasksOperationsV2;
  if (typeof tenantTasksOperationsV2?.loadTenantTasks !== 'function') {
    throw new Error('desktop_tenant_tasks_authority_required');
  }
  const projectOverviewOperationsV2 = options?.projectOverviewOperationsV2;
  if (typeof projectOverviewOperationsV2?.probeProjectOverview !== 'function') {
    throw new Error('desktop_project_overview_authority_required');
  }
  const runtimePoolOperationsV2 = options?.runtimePoolOperationsV2;
  if (typeof runtimePoolOperationsV2?.probeRuntimePool !== 'function') {
    throw new Error('desktop_runtime_pool_authority_required');
  }
  const runtimeClustersOperationsV2 = options?.runtimeClustersOperationsV2;
  if (typeof runtimeClustersOperationsV2?.probeRuntimeClusters !== 'function') {
    throw new Error('desktop_runtime_clusters_authority_required');
  }
  const projectWorkspacesClient = options?.projectWorkspacesClient;
  if (typeof projectWorkspacesClient?.list !== 'function') {
    throw new Error('desktop_project_workspaces_authority_required');
  }
  const projectBlackboardOperationsV2 = options?.projectBlackboardOperationsV2;
  if (
    typeof projectBlackboardOperationsV2?.probeProjectBlackboard !== 'function' ||
    typeof projectBlackboardOperationsV2.probeWorkspaceCollaborationCapability !== 'function'
  ) {
    throw new Error('desktop_project_blackboard_authority_required');
  }
  const projectAgentDashboardOperationsV2 = options?.projectAgentDashboardOperationsV2;
  if (
    typeof projectAgentDashboardOperationsV2?.loadProjectAgentDashboard !== 'function'
  ) {
    throw new Error('desktop_project_agent_dashboard_authority_required');
  }
  const projectAgentLogsOperationsV2 = options?.projectAgentLogsOperationsV2;
  if (typeof projectAgentLogsOperationsV2?.loadProjectAgentLogs !== 'function') {
    throw new Error('desktop_project_agent_logs_authority_required');
  }
  const projectAgentPatternsOperationsV2 = options?.projectAgentPatternsOperationsV2;
  if (
    typeof projectAgentPatternsOperationsV2?.loadProjectAgentPatterns !== 'function'
  ) {
    throw new Error('desktop_project_agent_patterns_authority_required');
  }
  const projectCommunitiesOperationsV2 = options?.projectCommunitiesOperationsV2;
  if (
    typeof projectCommunitiesOperationsV2?.loadProjectCommunities !== 'function'
  ) {
    throw new Error('desktop_project_communities_authority_required');
  }
  const projectMemoriesOperationsV2 = options?.projectMemoriesOperationsV2;
  if (typeof projectMemoriesOperationsV2?.loadProjectMemories !== 'function') {
    throw new Error('desktop_project_memories_authority_required');
  }
  const projectEntitiesOperationsV2 = options?.projectEntitiesOperationsV2;
  if (
    typeof projectEntitiesOperationsV2?.loadProjectEntities !== 'function' ||
    typeof projectEntitiesOperationsV2.loadProjectEntityRelationships !== 'function'
  ) {
    throw new Error('desktop_project_entities_authority_required');
  }
  const projectGraphOperationsV2 = options?.projectGraphOperationsV2;
  if (typeof projectGraphOperationsV2?.loadProjectGraph !== 'function') {
    throw new Error('desktop_project_graph_authority_required');
  }
  options ??= {} as DesktopWorkbenchCapabilityClientOptions;
  const managementRouteClients =
    options.managementRouteClients ??
    createManagementRouteClients(
      config,
      options.pluginMarketplaceOperationsV2 ?? UNAVAILABLE_PLUGIN_MARKETPLACE_OPERATIONS_V2,
    );
  const injectedAgentWorkspaceClient = options.agentWorkspaceClient ?? null;
  const agentWorkspaceJourneyClient =
    options.agentWorkspaceJourneyClient ??
    (injectedAgentWorkspaceClient ? null : createAgentWorkspaceJourneyClient(config));
  const agentWorkspaceClient =
    injectedAgentWorkspaceClient ??
    (agentWorkspaceJourneyClient ? null : createAgentWorkspaceClient(config));
  const projectKnowledgeClients = createProjectKnowledgeCapabilityClients(
    config,
    createDesktopProjectMemoriesClientV2(projectMemoriesOperationsV2, config),
    createDesktopProjectEntitiesClientV2(projectEntitiesOperationsV2, config),
    createDesktopProjectCommunitiesClientV2(projectCommunitiesOperationsV2, config),
    createDesktopProjectGraphClientV2(projectGraphOperationsV2, config),
    options.projectKnowledgeClientOverrides,
  );
  const projectAgentClients = createProjectAgentCapabilityClients(
    createDesktopProjectAgentDashboardClientV2(projectAgentDashboardOperationsV2, config),
    createDesktopProjectAgentLogsClientV2(projectAgentLogsOperationsV2, config),
    createDesktopProjectAgentPatternsClientV2(projectAgentPatternsOperationsV2, config),
  );
  const projectAdministrationClients =
    options.projectAdministrationClients ?? createProjectAdministrationCapabilityClients(config);
  const tenantAdminCapabilityClient =
    options.tenantAdminCapabilityClient ??
    createTenantAdminCapabilityClient(config, {
      governance: options.tenantGovernanceClient,
      billing: options.tenantBillingClient,
      audit: options.tenantAuditClient,
      trust: options.tenantTrustClient,
    });
  const tenantRemainingCapabilityClient =
    options.tenantRemainingCapabilityClient ?? createTenantRemainingCapabilityClient(config);
  const p2ThirdBatchCapabilityClient =
    options.p2ThirdBatchCapabilityClient ??
    createP2ThirdBatchCapabilityClient(config, {
      evolution: options.evolutionRouteClient,
      channels: options.channelsRouteClient,
      templates: options.templatesRouteClient,
      profile: options.profileRouteClient,
    });
  const cloudRequestBroker =
    options.cloudRequestBroker === undefined
      ? desktopVaultBoundCloudRequestBroker()
      : options.cloudRequestBroker;
  return {
    async loadSnapshot(signal?: AbortSignal): Promise<DesktopCapabilitySnapshot> {
      const [
        search,
        automationCapabilities,
        workspaceCollaboration,
        projectOverview,
        runtimePool,
        runtimeClusters,
        tenantOverview,
        tenantAnalytics,
        tenantAgentDashboard,
        tenantAgentBindings,
        tenantProjects,
        tenantTasks,
        managementRouteCapabilities,
        projectWorkspaces,
        projectBlackboard,
        projectKnowledgeCapabilities,
        projectAgentCapabilities,
        projectAdministrationCapabilities,
        agentWorkspace,
        tenantAdminCapabilities,
        tenantRemainingCapabilities,
        p2ThirdBatchCapabilities,
        auxiliaryCloudCapabilities,
      ] = await Promise.all([
        loadSearchCapability(config, signal),
        loadAutomationCapabilities(automationApi, config.projectId, signal),
        loadWorkspaceCollaborationCapability(config, projectBlackboardOperationsV2, signal),
        loadProjectOverviewCapability(config, projectOverviewOperationsV2, signal),
        loadRuntimePoolCapability(config, runtimePoolOperationsV2, signal),
        loadRuntimeClustersCapability(config, runtimeClustersOperationsV2, signal),
        loadTenantOverviewCapability(
          config,
          options.tenantOverviewOperationsV2,
          signal,
        ),
        loadTenantAnalyticsCapability(
          config,
          tenantAnalyticsOperationsV2,
          signal,
        ),
        loadTenantAgentDashboardCapability(
          config,
          tenantAgentDashboardOperationsV2,
          signal,
        ),
        loadTenantAgentBindingsCapability(
          config,
          tenantAgentBindingsOperationsV2,
          signal,
        ),
        loadTenantProjectsCapability(config, tenantProjectsOperationsV2, signal),
        loadTenantTasksCapability(config, tenantTasksOperationsV2, signal),
        loadManagementRouteCapabilities(managementRouteClients, config, signal),
        loadProjectWorkspacesCapability(projectWorkspacesClient, config, signal),
        loadProjectBlackboardCapability(projectBlackboardOperationsV2, config, signal),
        loadProjectKnowledgeCapabilities(projectKnowledgeClients, config, signal),
        loadProjectAgentCapabilities(projectAgentClients, config, signal),
        loadProjectAdministrationCapabilities(projectAdministrationClients, config, signal),
        loadAgentWorkspaceCapability(
          agentWorkspaceJourneyClient,
          agentWorkspaceClient,
          config,
          signal,
        ),
        tenantAdminCapabilityClient.load(signal),
        tenantRemainingCapabilityClient.load(signal),
        p2ThirdBatchCapabilityClient.load(signal),
        loadAuxiliaryCloudCapabilities(config, cloudRequestBroker, signal),
      ]);
      const tenantScope = tenantCapabilityScope(config);
      const projectScope = projectCapabilityScope(config);
      const workspaceScope = workspaceCapabilityScope(config);
      const primaryAuthoritySource = observedPrimaryAuthorityForMode(config.mode);
      const observed = (
        capability: DesktopCapabilityAvailability,
      ): DesktopCapabilitySnapshotEntry =>
        withObservedAuthority(capability, primaryAuthoritySource, []);
      const observedCloudAuxiliary = (
        capability: DesktopCapabilityAvailability,
      ): DesktopCapabilitySnapshotEntry =>
        withObservedAuthority(
          capability,
          'cloud_service',
          capability.availability === 'available' || capability.availability === 'degraded'
            ? ['sidecar', 'electron']
            : [],
        );
      const declared = (
        capability: DesktopCapabilityAvailability,
      ): DesktopCapabilitySnapshotEntry => withDeclaredAuthority(capability);
      const auxiliaryAuthority =
        config.mode === 'cloud' || auxiliaryCloudCapabilities.cloudAuthorityObserved
          ? observedCloudAuxiliary
          : declared;
      const snapshotP2ThirdBatchCapability = (
        projection: P2ThirdBatchCapabilityProjection,
      ): DesktopCapabilitySnapshotEntry =>
        projection.provenance === 'observed'
          ? observed(projection.capability)
          : declared(projection.capability);
      const snapshotProjectedCapability = (
        capability: DesktopCapabilityAvailability,
      ): DesktopCapabilitySnapshotEntry =>
        capability.provenance === 'observed' ? observed(capability) : declared(capability);
      const rawSnapshot = {
        version: DESKTOP_CAPABILITY_SNAPSHOT_VERSION,
        runtime_state: runtimeStateForMode(
          config.mode,
          auxiliaryCloudCapabilities.cloudAuthorityObserved,
        ),
        capabilities: {
          automation_run: observed(withCapabilityScope(automationCapabilities.run, projectScope)),
          'project-project-cron-jobs': observed(
            withCapabilityScope(automationCapabilities.cronJobs, projectScope),
          ),
          search: observed(withCapabilityScope(search, projectScope)),
          workspace_collaboration: observed(
            withCapabilityScope(workspaceCollaboration, workspaceScope),
          ),
          sandbox_isolation: declared(
            config.mode === 'local'
              ? withCapabilityScope(notApplicable('local_isolation_not_applicable'), workspaceScope)
              : withCapabilityScope(
                  unavailable('sandbox_isolation_capability_not_declared'),
                  workspaceScope,
                ),
          ),
          'device-approval': declared(deviceApprovalCapability(config)),
          'tenant-creation': declared(tenantCreationCapability(config)),
          'invitation-acceptance': declared(invitationAcceptanceCapability(config)),
          'backend-stores': auxiliaryAuthority(
            withCapabilityScope(auxiliaryCloudCapabilities.backendStores, tenantScope),
          ),
          'project-playbooks': auxiliaryAuthority(
            withCapabilityScope(auxiliaryCloudCapabilities.projectPlaybooks, projectScope),
          ),
          'agent-workspace-tenant-agent-workspace': observed(agentWorkspace),
          'project-project-overview': observed(withCapabilityScope(projectOverview, projectScope)),
          'project-project-search': observed(withCapabilityScope(search, projectScope)),
          'project-project-workspaces': observed(projectWorkspaces),
          'project-blackboard-dynamic-project-blackboard': observed(projectBlackboard),
          'project-project-team': (config.mode === 'local' ? declared : observed)(
            projectKnowledgeCapabilities['project-project-team'],
          ),
          'project-project-memories': (config.mode === 'local' ? declared : observed)(
            projectKnowledgeCapabilities['project-project-memories'],
          ),
          'project-project-entities': (config.mode === 'local' ? declared : observed)(
            projectKnowledgeCapabilities['project-project-entities'],
          ),
          'project-project-communities': (config.mode === 'local' ? declared : observed)(
            projectKnowledgeCapabilities['project-project-communities'],
          ),
          'project-project-graph': (config.mode === 'local' ? declared : observed)(
            projectKnowledgeCapabilities['project-project-graph'],
          ),
          'project-agent-dashboard': (config.mode === 'local' ? declared : observed)(
            projectAgentCapabilities['project-agent-dashboard'],
          ),
          'project-agent-logs': (config.mode === 'local' ? declared : observed)(
            projectAgentCapabilities['project-agent-logs'],
          ),
          'project-agent-patterns': (config.mode === 'local' ? declared : observed)(
            projectAgentCapabilities['project-agent-patterns'],
          ),
          'project-project-schema': (config.mode === 'local' ? declared : observed)(
            projectAdministrationCapabilities['project-project-schema'],
          ),
          'project-project-maintenance': (config.mode === 'local' ? declared : observed)(
            projectAdministrationCapabilities['project-project-maintenance'],
          ),
          'project-project-settings': (config.mode === 'local' ? declared : observed)(
            projectAdministrationCapabilities['project-project-settings'],
          ),
          'project-support': declared(projectSupportCapability(config)),
          'tenant-tenant-overview': observed(tenantOverview),
          'tenant-tenant-analytics': observed(tenantAnalytics),
          'tenant-tenant-agent-configuration':
            config.mode === 'local'
              ? declared(tenantAgentDashboard)
              : observed(tenantAgentDashboard),
          'tenant-tenant-agent-bindings': observed(tenantAgentBindings),
          'tenant-tenant-agent-definitions': observed(
            managementRouteCapabilities['tenant-tenant-agent-definitions'],
          ),
          'tenant-tenant-skills': observed(managementRouteCapabilities['tenant-tenant-skills']),
          'tenant-tenant-evolution': snapshotP2ThirdBatchCapability(
            p2ThirdBatchCapabilities['tenant-tenant-evolution'],
          ),
          'tenant-tenant-plugins': observed(managementRouteCapabilities['tenant-tenant-plugins']),
          'tenant-tenant-mcp-servers': observed(
            managementRouteCapabilities['tenant-tenant-mcp-servers'],
          ),
          'tenant-tenant-templates': snapshotP2ThirdBatchCapability(
            p2ThirdBatchCapabilities['tenant-tenant-templates'],
          ),
          'tenant-tenant-providers': observed(
            managementRouteCapabilities['tenant-tenant-providers'],
          ),
          'tenant-tenant-projects': observed(tenantProjects),
          'tenant-tenant-patterns': snapshotProjectedCapability(
            tenantRemainingCapabilities['tenant-tenant-patterns'],
          ),
          'tenant-tenant-acp': snapshotProjectedCapability(
            tenantRemainingCapabilities['tenant-tenant-acp'],
          ),
          'tenant-tenant-webhooks': snapshotProjectedCapability(
            tenantRemainingCapabilities['tenant-tenant-webhooks'],
          ),
          'tenant-tenant-genes': snapshotProjectedCapability(
            tenantRemainingCapabilities['tenant-tenant-genes'],
          ),
          'tenant-tenant-events': snapshotProjectedCapability(
            tenantRemainingCapabilities['tenant-tenant-events'],
          ),
          'tenant-tenant-decision-records': snapshotProjectedCapability(
            tenantRemainingCapabilities['tenant-tenant-decision-records'],
          ),
          'tenant-tenant-org-settings': snapshotProjectedCapability(
            tenantRemainingCapabilities['tenant-tenant-org-settings'],
          ),
          'tenant-tenant-settings': snapshotProjectedCapability(
            tenantRemainingCapabilities['tenant-tenant-settings'],
          ),
          'tenant-tenant-users': (config.mode === 'local' ? declared : observed)(
            tenantAdminCapabilities['tenant-tenant-users'],
          ),
          'tenant-tenant-billing': (config.mode === 'local' ? declared : observed)(
            tenantAdminCapabilities['tenant-tenant-billing'],
          ),
          'tenant-tenant-audit-logs': (config.mode === 'local' ? declared : observed)(
            tenantAdminCapabilities['tenant-tenant-audit-logs'],
          ),
          'tenant-tenant-trust-policies': (config.mode === 'local' ? declared : observed)(
            tenantAdminCapabilities['tenant-tenant-trust-policies'],
          ),
          'tenant-tenant-workspaces': declared(tenantWorkspacesCapability(config)),
          'tenant-tenant-tasks': observed(tenantTasks),
          'tenant-tenant-runtimes': declared(unifiedRuntimesCapability(config)),
          'tenant-tenant-pool': (config.mode === 'local' ? declared : observed)(
            withCapabilityScope(runtimePool, tenantScope),
          ),
          'tenant-tenant-instances': declared(runtimeInstancesCapability(config)),
          'tenant-tenant-clusters': (config.mode === 'local' ? declared : observed)(
            withCapabilityScope(runtimeClusters, tenantScope),
          ),
          'tenant-tenant-deploy': declared(runtimeDeploymentsCapability(config)),
          'tenant-tenant-instance-templates': declared(instanceTemplatesCapability(config)),
          'tenant-tenant-dead-letter-queue': declared(deadLetterQueueCapability(config)),
          'project-project-channels': snapshotP2ThirdBatchCapability(
            p2ThirdBatchCapabilities['project-project-channels'],
          ),
          'user-profile': snapshotP2ThirdBatchCapability(p2ThirdBatchCapabilities['user-profile']),
        },
      };
      const snapshot = parseDesktopCapabilitySnapshot(rawSnapshot);
      if (!snapshot) throw new Error('desktop capability snapshot is invalid');
      return snapshot;
    },
  };
}

async function loadAuxiliaryCloudCapabilities(
  config: DesktopRuntimeConfig,
  broker: VaultBoundCloudRequestBroker | null,
  signal?: AbortSignal,
): Promise<AuxiliaryCloudCapabilities> {
  if (!broker) {
    if (config.mode === 'local') {
      return Object.freeze({
        backendStores: auxiliaryCloudUnavailable(
          'local_backend_stores_cloud_authority_unavailable',
        ),
        projectPlaybooks: auxiliaryCloudUnavailable(
          'local_project_playbooks_cloud_authority_unavailable',
        ),
        cloudAuthorityObserved: false,
      });
    }
    return Object.freeze({
      backendStores: unavailable('cloud_request_broker_missing'),
      projectPlaybooks: unavailable('cloud_request_broker_missing'),
      cloudAuthorityObserved: false,
    });
  }
  try {
    const payload = await broker.requestJson({
      path: '/api/v1/workspace-context',
      signal,
    });
    if (!isRecord(payload) || !isRecord(payload.context)) {
      throw new Error('workspace context is invalid');
    }
    const tenantId = scopeIdentifier(config.tenantId);
    const projectId = scopeIdentifier(config.projectId);
    const observedTenantId =
      typeof payload.context.tenant_id === 'string'
        ? scopeIdentifier(payload.context.tenant_id)
        : null;
    const observedProjectId =
      payload.context.project_id === null
        ? null
        : typeof payload.context.project_id === 'string'
          ? scopeIdentifier(payload.context.project_id)
          : null;
    const revision = payload.context.revision;
    const membershipRole = payload.membership_role;
    if (
      observedTenantId === null ||
      (payload.context.project_id !== null && observedProjectId === null) ||
      typeof revision !== 'number' ||
      !Number.isSafeInteger(revision) ||
      revision < 0 ||
      (membershipRole !== 'owner' &&
        membershipRole !== 'admin' &&
        membershipRole !== 'member' &&
        membershipRole !== 'editor' &&
        membershipRole !== 'viewer')
    ) {
      throw new Error('workspace context is invalid');
    }
    const backendActions =
      membershipRole === 'owner' || membershipRole === 'admin'
        ? ['view', 'list', 'create', 'update', 'delete', 'test']
        : ['view', 'list'];
    const tenantScopeMatches = tenantId !== null && observedTenantId === tenantId;
    const backendStores = tenantScopeMatches
      ? auxiliaryCloudAvailable(backendActions, revision)
      : auxiliaryCloudUnavailable(
          config.mode === 'local'
            ? 'local_backend_stores_cloud_scope_unavailable'
            : 'backend_stores_scope_unavailable',
        );
    const projectPlaybooks =
      tenantScopeMatches && projectId !== null && observedProjectId === projectId
        ? auxiliaryCloudAvailable(['view', 'list', 'refresh', 'review-verdicts'], revision)
        : auxiliaryCloudUnavailable(
            config.mode === 'local'
              ? 'local_project_playbooks_cloud_scope_unavailable'
              : 'project_playbooks_scope_unavailable',
          );
    return Object.freeze({
      backendStores,
      projectPlaybooks,
      cloudAuthorityObserved: true,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    if (config.mode === 'local') {
      return Object.freeze({
        backendStores: auxiliaryCloudUnavailable(
          'local_backend_stores_cloud_authority_unavailable',
        ),
        projectPlaybooks: auxiliaryCloudUnavailable(
          'local_project_playbooks_cloud_authority_unavailable',
        ),
        cloudAuthorityObserved: false,
      });
    }
    return Object.freeze({
      backendStores: auxiliaryCloudUnavailable('backend_stores_authority_unavailable'),
      projectPlaybooks: auxiliaryCloudUnavailable('project_playbooks_authority_unavailable'),
      cloudAuthorityObserved: false,
    });
  }
}

function auxiliaryCloudAvailable(
  allowedActions: readonly string[],
  authorityRevision: number,
): DesktopCapabilityAvailability {
  return {
    availability: 'available',
    reason_code: null,
    service_version: '0.1.0',
    contract_version: '4.0.0',
    allowed_actions: [...allowedActions],
    scope: emptyCapabilityScope(),
    authority_revision: authorityRevision,
    retryable: false,
  };
}

function auxiliaryCloudUnavailable(reasonCode: string): DesktopCapabilityAvailability {
  return {
    ...unavailable(reasonCode),
    retryable: true,
  };
}

function projectP2ThirdBatchCapability(
  projection: P2ThirdBatchCapabilityProjection,
  mode: DesktopRuntimeConfig['mode'],
): DesktopCapabilitySnapshotEntry {
  return projection.provenance === 'observed'
    ? withObservedAuthority(projection.capability, observedPrimaryAuthorityForMode(mode), [])
    : withDeclaredAuthority(projection.capability);
}

function createAgentWorkspaceClient(
  config: DesktopRuntimeConfig,
): AgentWorkspaceAuthorityClient | null {
  try {
    return createAgentWorkspaceAuthorityClient(config);
  } catch {
    return null;
  }
}

function createAgentWorkspaceJourneyClient(
  config: DesktopRuntimeConfig,
): AgentWorkspaceJourneyAuthorityClient | null {
  try {
    return createAgentWorkspaceJourneyAuthorityClient(config);
  } catch {
    return null;
  }
}

async function loadAgentWorkspaceCapability(
  journeyClient: AgentWorkspaceJourneyAuthorityClient | null,
  legacyClient: AgentWorkspaceAuthorityClient | null,
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const scope = agentWorkspaceScope(config);
  const capabilityScope = workspaceCapabilityScope(config);
  if (!scope) {
    return withCapabilityScope(unavailable('agent_workspace_scope_unavailable'), capabilityScope);
  }
  if (!journeyClient && !legacyClient) {
    return withCapabilityScope(
      unavailable('agent_workspace_authority_unavailable'),
      capabilityScope,
    );
  }
  try {
    if (journeyClient) {
      const observation = await journeyClient.probe(signal);
      return agentWorkspaceJourneyObservedCapability(observation, scope);
    }
    const observation = await legacyClient!.probe(signal);
    return agentWorkspaceObservedCapability(observation, scope);
  } catch (error) {
    if (signal?.aborted) throw error;
    const reasonCode =
      error instanceof DesktopApiError && error.status === 403
        ? 'agent_workspace_forbidden'
        : error instanceof DesktopApiError && error.status === 0
          ? 'agent_workspace_authority_contract_invalid'
          : 'agent_workspace_authority_unavailable';
    return withCapabilityScope(unavailable(reasonCode), capabilityScope);
  }
}

function agentWorkspaceJourneyObservedCapability(
  observation: AgentWorkspaceJourneySnapshot,
  scope: AgentWorkspaceAuthorityScope,
): DesktopCapabilityAvailability {
  const expectedAuthoritySource = scope.authority === 'local' ? 'sidecar' : 'cloud_service';
  const observations = AGENT_WORKSPACE_JOURNEY_IDS.map((journeyId) =>
    Object.hasOwn(observation.journeys, journeyId) ? observation.journeys[journeyId] : null,
  );
  if (
    observation.authority !== scope.authority ||
    observation.authoritySource !== expectedAuthoritySource ||
    observation.provenance !== 'observed' ||
    observation.scope.tenantId !== scope.tenantId ||
    observation.scope.projectId !== scope.projectId ||
    observation.scope.workspaceId !== scope.workspaceId ||
    observations.some((journey) => !isAgentWorkspaceJourneyObservation(journey))
  ) {
    return withCapabilityScope(
      unavailable('agent_workspace_authority_contract_invalid'),
      agentWorkspaceCapabilityScope(scope),
    );
  }
  if (
    observation.authorityRevision === null ||
    !Number.isSafeInteger(observation.authorityRevision) ||
    observation.authorityRevision < 0
  ) {
    return withCapabilityScope(
      unavailable('agent_workspace_authority_revision_unavailable'),
      agentWorkspaceCapabilityScope(scope),
    );
  }
  const allowedActions = [
    ...new Set(observations.flatMap((journey) => journey?.observedActions ?? [])),
  ].sort();
  if (allowedActions.length === 0) {
    return {
      availability: 'unavailable',
      reason_code: 'agent_workspace_journeys_unavailable',
      service_version: '0.1.0',
      contract_version: '4.0.0',
      allowed_actions: [],
      scope: agentWorkspaceCapabilityScope(scope),
      authority_revision: observation.authorityRevision,
    };
  }
  return {
    availability: 'degraded',
    reason_code: 'agent_workspace_journeys_partial',
    service_version: '0.1.0',
    contract_version: '4.0.0',
    allowed_actions: allowedActions,
    scope: agentWorkspaceCapabilityScope(scope),
    authority_revision: observation.authorityRevision,
  };
}

function isAgentWorkspaceJourneyObservation(
  input: AgentWorkspaceJourneyObservation | null,
): input is AgentWorkspaceJourneyObservation {
  return (
    input !== null &&
    (input.availability === 'degraded' || input.availability === 'unavailable') &&
    typeof input.reasonCode === 'string' &&
    input.reasonCode.length > 0 &&
    Array.isArray(input.observedActions) &&
    input.observedActions.every(
      (action) => typeof action === 'string' && action.trim() === action && action.length > 0,
    )
  );
}

function agentWorkspaceObservedCapability(
  observation: AgentWorkspaceAuthorityObservation,
  scope: AgentWorkspaceAuthorityScope,
): DesktopCapabilityAvailability {
  if (
    observation.authority !== scope.authority ||
    observation.scope.authority !== scope.authority ||
    observation.scope.tenantId !== scope.tenantId ||
    observation.scope.projectId !== scope.projectId ||
    observation.scope.workspaceId !== scope.workspaceId
  ) {
    return withCapabilityScope(
      unavailable('agent_workspace_authority_contract_invalid'),
      agentWorkspaceCapabilityScope(scope),
    );
  }
  return {
    availability: observation.availability,
    reason_code: observation.reasonCode,
    service_version: observation.serviceVersion,
    contract_version: observation.contractVersion,
    allowed_actions: [...observation.allowedActions],
    scope: agentWorkspaceCapabilityScope(scope),
    authority_revision: observation.authorityRevision,
  };
}

function agentWorkspaceScope(config: DesktopRuntimeConfig): AgentWorkspaceAuthorityScope | null {
  const tenantId = scopeIdentifier(config.tenantId);
  const projectId = scopeIdentifier(config.projectId);
  return tenantId && projectId
    ? Object.freeze({
        authority: config.mode,
        tenantId,
        projectId,
        workspaceId: scopeIdentifier(config.workspaceId),
      })
    : null;
}

function agentWorkspaceCapabilityScope(
  scope: AgentWorkspaceAuthorityScope,
): DesktopCapabilityScope {
  return {
    tenant_id: scope.tenantId,
    project_id: scope.projectId,
    workspace_id: scope.workspaceId,
    instance_id: null,
  };
}

async function loadProjectWorkspacesCapability(
  client: Pick<ProjectWorkspacesClient, 'list'> | null,
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const scope = projectWorkspacesScope(config);
  const capabilityScope = projectCapabilityScope(config);
  if (!scope) {
    return withCapabilityScope(
      unavailable('project_workspaces_scope_unavailable'),
      capabilityScope,
    );
  }
  if (!client) {
    return withCapabilityScope(
      unavailable('project_workspaces_authority_unavailable'),
      capabilityScope,
    );
  }
  try {
    const snapshot = await client.list(scope, { signal });
    return projectWorkspacesCapability(snapshot, scope);
  } catch (error) {
    if (signal?.aborted) throw error;
    return withCapabilityScope(
      unavailable('project_workspaces_authority_unavailable'),
      capabilityScope,
    );
  }
}

async function loadProjectBlackboardCapability(
  operations: Pick<DesktopProjectBlackboardOperationsV2, 'probeProjectBlackboard'>,
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const scope = projectBlackboardScope(config);
  const capabilityScope = workspaceCapabilityScope(config);
  if (!scope) {
    return withCapabilityScope(
      unavailable('project_blackboard_scope_unavailable'),
      capabilityScope,
    );
  }
  try {
    const snapshot = await operations.probeProjectBlackboard({
      config,
      scope,
      ...(signal === undefined ? {} : { signal }),
    });
    return projectBlackboardCapability(snapshot, scope);
  } catch (error) {
    if (signal?.aborted) throw error;
    return withCapabilityScope(
      unavailable('project_blackboard_authority_unavailable'),
      capabilityScope,
    );
  }
}

function projectWorkspacesCapability(
  snapshot: ProjectWorkspacesSnapshot,
  scope: ProjectWorkspacesScope,
): DesktopCapabilityAvailability {
  if (
    snapshot.authority !== scope.authority ||
    snapshot.scope.authority !== scope.authority ||
    snapshot.scope.tenantId !== scope.tenantId ||
    snapshot.scope.projectId !== scope.projectId
  ) {
    return withCapabilityScope(
      unavailable('project_workspaces_authority_contract_invalid'),
      projectScope(scope),
    );
  }
  return {
    availability: snapshot.availability,
    reason_code: snapshot.reasonCode,
    service_version: PROJECT_WORKSPACES_SERVICE_VERSION,
    contract_version: PROJECT_WORKSPACES_CONTRACT_VERSION,
    allowed_actions: [...snapshot.allowedActions],
    scope: projectScope(scope),
    authority_revision: snapshot.authorityRevision,
  };
}

function projectBlackboardCapability(
  snapshot: ProjectBlackboardSnapshot,
  scope: ProjectBlackboardScope,
): DesktopCapabilityAvailability {
  if (
    snapshot.authority !== scope.authority ||
    snapshot.scope.authority !== scope.authority ||
    snapshot.scope.tenantId !== scope.tenantId ||
    snapshot.scope.projectId !== scope.projectId ||
    snapshot.scope.workspaceId !== scope.workspaceId
  ) {
    return withCapabilityScope(
      unavailable('project_blackboard_authority_contract_invalid'),
      blackboardScope(scope),
    );
  }
  return {
    availability: snapshot.availability,
    reason_code: snapshot.reasonCode,
    service_version: PROJECT_BLACKBOARD_SERVICE_VERSION,
    contract_version: PROJECT_BLACKBOARD_CONTRACT_VERSION,
    allowed_actions: [...snapshot.allowedActions],
    scope: blackboardScope(scope),
    authority_revision: snapshot.authorityRevision,
  };
}

function projectWorkspacesScope(config: DesktopRuntimeConfig): ProjectWorkspacesScope | null {
  const tenantId = scopeIdentifier(config.tenantId);
  const projectId = scopeIdentifier(config.projectId);
  return tenantId && projectId
    ? Object.freeze({ authority: config.mode, tenantId, projectId })
    : null;
}

function projectBlackboardScope(config: DesktopRuntimeConfig): ProjectBlackboardScope | null {
  const scope = projectWorkspacesScope(config);
  const workspaceId = scopeIdentifier(config.workspaceId);
  return scope && workspaceId ? Object.freeze({ ...scope, workspaceId }) : null;
}

function projectScope(scope: ProjectWorkspacesScope): DesktopCapabilityScope {
  return {
    tenant_id: scope.tenantId,
    project_id: scope.projectId,
    workspace_id: null,
    instance_id: null,
  };
}

function blackboardScope(scope: ProjectBlackboardScope): DesktopCapabilityScope {
  return {
    ...projectScope(scope),
    workspace_id: scope.workspaceId,
  };
}

function createManagementRouteClients(
  config: DesktopRuntimeConfig,
  pluginMarketplaceOperationsV2: Pick<
    DesktopPluginMarketplaceCatalogOperationsV2,
    'projectMarketplacePlugins'
  >,
): ManagementRouteCapabilityClients {
  return Object.freeze({
    'tenant-tenant-providers': createProviderRouteClient(config),
    'tenant-tenant-agent-definitions': createAgentDefinitionsRouteClient(config),
    'tenant-tenant-skills': createSkillsRouteClient(config),
    'tenant-tenant-plugins': createPluginsRouteClient(
      config,
      pluginMarketplaceOperationsV2,
    ),
    'tenant-tenant-mcp-servers': createMcpServersRouteClient(config),
  });
}

async function loadManagementRouteCapabilities(
  clients: ManagementRouteCapabilityClients,
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<Record<ManagementRouteCapability, DesktopCapabilityAvailability>> {
  const entries = await Promise.all(
    MANAGEMENT_ROUTE_CAPABILITY_NAMES.map(
      async (capability) =>
        [
          capability,
          await loadManagementRouteCapability(capability, clients[capability], config, signal),
        ] as const,
    ),
  );
  return Object.fromEntries(entries) as Record<
    ManagementRouteCapability,
    DesktopCapabilityAvailability
  >;
}

async function loadManagementRouteCapability(
  capability: ManagementRouteCapability,
  client: ManagementRouteClient,
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  try {
    const scope = managementRouteScopeForRuntime(config, config.tenantId);
    const observation = normalizeManagementRouteObservation(
      config,
      scope,
      await client.observe(scope, { signal }),
    );
    return {
      availability: 'available',
      reason_code: null,
      service_version: MANAGEMENT_ROUTE_SERVICE_VERSION,
      contract_version: MANAGEMENT_ROUTE_CONTRACT_VERSION,
      allowed_actions: ['view', 'list'],
      scope: {
        tenant_id: observation.scope.tenantId,
        project_id: observation.scope.projectId,
        workspace_id: null,
        instance_id: null,
      },
      // The local sidecar exposes no per-collection revision; the observed item
      // count is the authoritative signal available for the revision closure.
      authority_revision: observation.itemCount,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    return withCapabilityScope(
      unavailable(`${managementRouteReasonPrefix(capability)}_authority_unavailable`),
      projectCapabilityScope(config),
    );
  }
}

function normalizeManagementRouteObservation(
  config: DesktopRuntimeConfig,
  expectedScope: ManagementRouteObservation['scope'],
  observation: ManagementRouteObservation,
): ManagementRouteObservation {
  const scope = requireManagementRouteRuntimeScope(config, observation.scope);
  if (
    scope.authority !== expectedScope.authority ||
    scope.tenantId !== expectedScope.tenantId ||
    scope.projectId !== expectedScope.projectId
  ) {
    throw new Error('management_route_observation_scope_mismatch');
  }
  return managementRouteObservation(scope, observation.itemCount);
}

export function normalizeSearchCapabilityContract(input: unknown): DesktopCapabilityAvailability {
  const negotiation = negotiateCapabilityContract(input, DESKTOP_MINIMUM_CONTRACT_VERSION);
  if (!negotiation.compatible) {
    return unavailable(
      negotiation.reason_code ?? 'capability_contract_version_invalid',
      negotiation,
    );
  }
  if (
    !isExactRecord(input, ['service_version', 'contract_version', 'search_types', 'filters']) ||
    !isExactRecord(input.search_types, Object.keys(SEARCH_CONTRACT)) ||
    !isExactRecord(input.filters, ['entity_types', 'relationship_types']) ||
    !isStringArray(input.filters.entity_types) ||
    !isStringArray(input.filters.relationship_types)
  ) {
    return unavailable('search_capability_contract_invalid', negotiation);
  }

  for (const [searchType, expected] of Object.entries(SEARCH_CONTRACT)) {
    const declaration = input.search_types[searchType];
    if (
      !isExactRecord(declaration, ['description', 'endpoint', 'parameters']) ||
      typeof declaration.description !== 'string' ||
      declaration.endpoint !== expected.endpoint ||
      !isRecord(declaration.parameters) ||
      (expected.parameters !== undefined &&
        !matchesExactStringRecord(declaration.parameters, expected.parameters))
    ) {
      return unavailable('search_capability_contract_invalid', negotiation);
    }
  }
  return available(negotiation, {
    allowedActions: Object.keys(SEARCH_CONTRACT),
  });
}

export function normalizeLocalSearchCapabilityContract(
  input: unknown,
  scope: { tenantId: string; projectId: string },
): DesktopCapabilityAvailability {
  const negotiation = negotiateCapabilityContract(input, DESKTOP_MINIMUM_CONTRACT_VERSION);
  if (!negotiation.compatible) {
    return unavailable(
      negotiation.reason_code ?? 'capability_contract_version_invalid',
      negotiation,
    );
  }
  if (
    !isExactRecord(input, [
      'service_version',
      'contract_version',
      'mode',
      'reason_code',
      'tenant_id',
      'project_id',
      'projection_revision',
      'backfill_cursor',
      'supported_search_types',
      'unavailable_search_types',
    ]) ||
    input.mode !== 'keyword_degraded' ||
    (input.reason_code !== 'local_embeddings_unavailable' &&
      input.reason_code !== 'local_search_backfill_in_progress') ||
    input.tenant_id !== scope.tenantId ||
    input.project_id !== scope.projectId ||
    typeof input.projection_revision !== 'number' ||
    !Number.isSafeInteger(input.projection_revision) ||
    input.projection_revision < 0 ||
    (input.backfill_cursor !== null &&
      (typeof input.backfill_cursor !== 'string' ||
        !/^timeline_rowid:[1-9][0-9]*$/.test(input.backfill_cursor))) ||
    !matchesExactStringArray(input.supported_search_types, LOCAL_SEARCH_SUPPORTED_TYPES) ||
    !matchesExactStringArray(input.unavailable_search_types, LOCAL_SEARCH_UNAVAILABLE_TYPES)
  ) {
    return unavailable('local_search_capability_contract_invalid', negotiation);
  }
  if (
    (input.reason_code === 'local_search_backfill_in_progress') !==
    (input.backfill_cursor !== null)
  ) {
    return unavailable('local_search_capability_contract_invalid', negotiation);
  }
  return degraded(input.reason_code, negotiation, {
    allowedActions: LOCAL_SEARCH_SUPPORTED_TYPES,
    authorityRevision: input.projection_revision,
  });
}

export function normalizeAutomationCapabilityContract(
  input: unknown,
): DesktopCapabilityAvailability {
  const negotiation = negotiateCapabilityContract(input, DESKTOP_MINIMUM_CONTRACT_VERSION);
  if (!negotiation.compatible) {
    return unavailable(
      negotiation.reason_code ?? 'capability_contract_version_invalid',
      negotiation,
    );
  }
  if (!isRecord(input)) {
    return unavailable('automation_capability_contract_invalid', negotiation);
  }
  const {
    service_version: _serviceVersion,
    contract_version: _contractVersion,
    ...capabilityPayload
  } = input;
  const capabilities = normalizeAutomationCapabilities(capabilityPayload);
  if (!capabilities) {
    return unavailable('automation_capability_contract_invalid', negotiation);
  }

  const runCapability = capabilities.run_now;
  if (!runCapability.allowed) {
    return unavailable(runCapability.reason_code!, negotiation);
  }
  if (
    !capabilities.read ||
    !capabilities.revision_guarded ||
    !capabilities.idempotency_guarded ||
    !capabilities.durable_execution
  ) {
    return unavailable('automation_capability_contract_invalid', negotiation);
  }
  return available(negotiation, { allowedActions: ['run_now'] });
}

export function normalizeProjectCronJobsCapabilityContract(
  input: unknown,
): DesktopCapabilityAvailability {
  const negotiation = negotiateCapabilityContract(input, DESKTOP_MINIMUM_CONTRACT_VERSION);
  if (!negotiation.compatible) {
    return unavailable(
      negotiation.reason_code ?? 'capability_contract_version_invalid',
      negotiation,
    );
  }
  if (!isRecord(input)) {
    return unavailable('automation_capability_contract_invalid', negotiation);
  }
  const {
    service_version: _serviceVersion,
    contract_version: _contractVersion,
    ...capabilityPayload
  } = input;
  const capabilities = normalizeAutomationCapabilities(capabilityPayload);
  if (!capabilities || !capabilities.read) {
    return unavailable('automation_capability_contract_invalid', negotiation);
  }

  const allowedActions = ['view', 'list', 'view-history', 'inspect-capabilities'];
  const actionContracts = [
    [
      'create',
      automationActionAvailability(capabilities, 'create', {
        handler_available: true,
        revision_required: false,
      }),
    ],
    [
      'update',
      automationActionAvailability(capabilities, 'edit', {
        handler_available: true,
        revision_required: true,
      }),
    ],
    [
      'toggle',
      automationActionAvailability(capabilities, 'toggle', {
        handler_available: true,
        revision_required: true,
      }),
    ],
    [
      'run-now',
      automationActionAvailability(capabilities, 'run_now', {
        handler_available: true,
        revision_required: true,
        durable_execution_required: true,
      }),
    ],
    [
      'delete',
      automationActionAvailability(capabilities, 'delete', {
        handler_available: true,
        revision_required: true,
      }),
    ],
  ] as const;
  for (const [action, capability] of actionContracts) {
    if (capability.allowed) allowedActions.push(action);
  }
  if (allowedActions.length === 9) {
    return available(negotiation, { allowedActions });
  }
  return degraded('automation_actions_restricted', negotiation, {
    allowedActions,
  });
}

async function loadSearchCapability(
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  try {
    const headers = new Headers({ Accept: 'application/json' });
    const credential = desktopApiCredential(config);
    if (credential) headers.set('Authorization', `Bearer ${credential}`);
    const launchCapability = desktopLaunchCapability(config);
    if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
    const response = await desktopApiFetch(
      config,
      '/api/v1/search-enhanced/capabilities',
      { headers, signal },
    );
    if (!response.ok) return unavailable('search_capability_contract_unavailable');
    const contentType = response.headers.get('content-type') ?? '';
    if (!contentType.includes('application/json')) {
      return unavailable('search_capability_contract_invalid');
    }
    const payload = await response.json().catch(() => null);
    if (config.mode === 'local') {
      return normalizeLocalSearchCapabilityContract(payload, {
        tenantId: config.tenantId,
        projectId: config.projectId,
      });
    }
    return normalizeSearchCapabilityContract(payload);
  } catch (error) {
    if (signal?.aborted) throw error;
    return unavailable('search_capability_contract_unavailable');
  }
}

async function loadAutomationCapabilities(
  automationApi: AutomationCapabilityAuthority,
  projectId: string,
  signal?: AbortSignal,
): Promise<
  Readonly<{
    run: DesktopCapabilityAvailability;
    cronJobs: DesktopCapabilityAvailability;
  }>
> {
  if (!projectId.trim()) {
    const capability = unavailable('automation_capability_scope_unavailable');
    return { run: capability, cronJobs: capability };
  }
  try {
    const payload = await automationApi.getAutomationCapabilities(projectId, signal);
    return {
      run: normalizeAutomationCapabilityContract(payload),
      cronJobs: normalizeProjectCronJobsCapabilityContract(payload),
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    const capability = unavailable('automation_capability_contract_unavailable');
    return { run: capability, cronJobs: capability };
  }
}

async function loadWorkspaceCollaborationCapability(
  config: DesktopRuntimeConfig,
  operations: Pick<
    DesktopProjectBlackboardOperationsV2,
    'probeWorkspaceCollaborationCapability'
  >,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  if (readWorkspaceCollaborationCapabilityScope(config) === null) {
    return unavailable('workspace_collaboration_capability_scope_unavailable');
  }
  try {
    return await operations.probeWorkspaceCollaborationCapability({
      config,
      ...(signal === undefined ? {} : { signal }),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    return unavailable('workspace_collaboration_capability_contract_unavailable');
  }
}

async function loadProjectOverviewCapability(
  config: DesktopRuntimeConfig,
  operations: Pick<DesktopProjectOverviewOperationsV2, 'probeProjectOverview'>,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const tenantId = scopeIdentifier(config.tenantId);
  const projectId = scopeIdentifier(config.projectId);
  if (!tenantId || !projectId) {
    return unavailable('project_overview_scope_unavailable');
  }

  try {
    return await operations.probeProjectOverview({
      config,
      scope: {
        authority: config.mode,
        tenantId,
        projectId,
      },
      ...(signal === undefined ? {} : { signal }),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof DesktopApiError && error.status === 403) {
      return unavailable('project_overview_forbidden');
    }
    if (error instanceof DesktopApiError && error.status === 0) {
      return unavailable('project_overview_contract_invalid');
    }
    return unavailable('project_overview_authority_unavailable');
  }
}

async function loadRuntimePoolCapability(
  config: DesktopRuntimeConfig,
  operations: Pick<DesktopRuntimePoolOperationsV2, 'probeRuntimePool'>,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const tenantId = scopeIdentifier(config.tenantId);
  if (!tenantId) return unavailable('runtime_pool_scope_unavailable');

  try {
    return await operations.probeRuntimePool({
      config,
      scope: { authority: config.mode, tenantId },
      ...(signal === undefined ? {} : { signal }),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof DesktopApiError && error.status === 403) {
      return unavailable('runtime_pool_forbidden');
    }
    if (
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_pool_service_contract_invalid'
    ) {
      return unavailable('runtime_pool_contract_invalid');
    }
    return unavailable('runtime_pool_authority_unavailable');
  }
}

async function loadRuntimeClustersCapability(
  config: DesktopRuntimeConfig,
  operations: Pick<DesktopRuntimeClustersOperationsV2, 'probeRuntimeClusters'>,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const tenantId = scopeIdentifier(config.tenantId);
  if (!tenantId) return unavailable('runtime_clusters_tenant_scope_unavailable');

  try {
    return await operations.probeRuntimeClusters({
      config,
      scope: { authority: config.mode, tenantId },
      ...(signal === undefined ? {} : { signal }),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof DesktopApiError && error.status === 403) {
      return unavailable('runtime_clusters_forbidden');
    }
    if (
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_clusters_service_contract_invalid'
    ) {
      return unavailable('runtime_clusters_contract_invalid');
    }
    return unavailable('runtime_clusters_authority_unavailable');
  }
}

function available(
  negotiation: CapabilityContractNegotiation,
  metadata: CapabilityAuthorityMetadata = {},
): DesktopCapabilityAvailability {
  return {
    availability: 'available',
    reason_code: null,
    service_version: negotiation.service_version,
    contract_version: negotiation.contract_version,
    allowed_actions: [...(metadata.allowedActions ?? [])],
    scope: emptyCapabilityScope(),
    authority_revision: metadata.authorityRevision ?? null,
  };
}

function degraded(
  reasonCode: string,
  negotiation: CapabilityContractNegotiation,
  metadata: CapabilityAuthorityMetadata = {},
): DesktopCapabilityAvailability {
  return {
    availability: 'degraded',
    reason_code: reasonCode,
    service_version: negotiation.service_version,
    contract_version: negotiation.contract_version,
    allowed_actions: [...(metadata.allowedActions ?? [])],
    scope: emptyCapabilityScope(),
    authority_revision: metadata.authorityRevision ?? null,
  };
}

function unavailable(
  reasonCode: string,
  negotiation?: CapabilityContractNegotiation,
): DesktopCapabilityAvailability {
  return {
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: negotiation?.service_version ?? null,
    contract_version: negotiation?.contract_version ?? null,
    allowed_actions: [],
    scope: emptyCapabilityScope(),
    authority_revision: null,
  };
}

function notApplicable(reasonCode: string): DesktopCapabilityAvailability {
  return {
    availability: 'not_applicable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    scope: emptyCapabilityScope(),
    authority_revision: null,
  };
}

type CapabilityAuthorityMetadata = {
  allowedActions?: readonly string[];
  authorityRevision?: number | null;
};

function withObservedAuthority(
  capability: DesktopCapabilityAvailability,
  primaryAuthoritySource: Exclude<DesktopCapabilityAuthoritySource, 'renderer' | 'electron'>,
  supportingAuthoritySources: readonly Exclude<DesktopCapabilityAuthoritySource, 'renderer'>[],
): DesktopCapabilitySnapshotEntry {
  const active = capability.availability === 'available' || capability.availability === 'degraded';
  const revisionBound =
    active && capability.authority_revision === null
      ? {
          ...capability,
          availability: 'unavailable' as const,
          reason_code: 'capability_authority_revision_unavailable',
          allowed_actions: [],
        }
      : capability;
  return {
    ...revisionBound,
    retryable: revisionBound.retryable ?? false,
    authority_source: primaryAuthoritySource,
    supporting_authority_sources: Object.freeze([...supportingAuthoritySources]),
    provenance: 'observed',
  };
}

function withDeclaredAuthority(
  capability: DesktopCapabilityAvailability,
): DesktopCapabilitySnapshotEntry {
  const active = capability.availability === 'available' || capability.availability === 'degraded';
  const closed: DesktopCapabilityAvailability = active
    ? {
        ...capability,
        availability: 'unavailable',
        reason_code: 'renderer_capability_authority_unobserved',
        allowed_actions: [],
        authority_revision: null,
      }
    : capability;
  return {
    ...closed,
    retryable: closed.retryable ?? false,
    authority_source: 'renderer',
    supporting_authority_sources: Object.freeze([]),
    provenance: 'declared',
  };
}

function observedPrimaryAuthorityForMode(
  mode: DesktopRuntimeConfig['mode'],
): 'cloud_service' | 'sidecar' {
  return mode === 'local' ? 'sidecar' : 'cloud_service';
}

function runtimeStateForMode(
  mode: DesktopRuntimeConfig['mode'],
  cloudAuthorityObserved: boolean,
): 'cloud' | 'local_online' | 'local_offline' {
  if (mode === 'cloud') return 'cloud';
  return cloudAuthorityObserved ? 'local_online' : 'local_offline';
}

function withCapabilityScope(
  capability: DesktopCapabilityAvailability,
  scope: DesktopCapabilityScope,
): DesktopCapabilityAvailability {
  return {
    ...capability,
    scope: { ...scope },
  };
}

function projectCapabilityScope(config: DesktopRuntimeConfig): DesktopCapabilityScope {
  return {
    tenant_id: scopeIdentifier(config.tenantId),
    project_id: scopeIdentifier(config.projectId),
    workspace_id: null,
    instance_id: null,
  };
}

function tenantCapabilityScope(config: DesktopRuntimeConfig): DesktopCapabilityScope {
  return {
    tenant_id: scopeIdentifier(config.tenantId),
    project_id: null,
    workspace_id: null,
    instance_id: null,
  };
}

function workspaceCapabilityScope(config: DesktopRuntimeConfig): DesktopCapabilityScope {
  return {
    ...projectCapabilityScope(config),
    workspace_id: scopeIdentifier(config.workspaceId),
  };
}

function emptyCapabilityScope(): DesktopCapabilityScope {
  return {
    tenant_id: null,
    project_id: null,
    workspace_id: null,
    instance_id: null,
  };
}

function scopeIdentifier(input: string): string | null {
  return input.length > 0 && input === input.trim() ? input : null;
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === 'object' && input !== null && !Array.isArray(input);
}

function isExactRecord(
  input: unknown,
  expectedKeys: readonly string[],
): input is Record<string, unknown> {
  if (!isRecord(input)) return false;
  const keys = Object.keys(input).sort();
  const expected = [...expectedKeys].sort();
  return keys.length === expected.length && keys.every((key, index) => key === expected[index]);
}

function isStringArray(input: unknown): input is string[] {
  return Array.isArray(input) && input.every((item) => typeof item === 'string');
}

function matchesExactStringRecord(
  input: unknown,
  expected: Readonly<Record<string, string>>,
): boolean {
  return (
    isExactRecord(input, Object.keys(expected)) &&
    Object.entries(expected).every(([key, value]) => input[key] === value)
  );
}

function matchesExactStringArray(input: unknown, expected: readonly string[]): boolean {
  return (
    Array.isArray(input) &&
    input.length === expected.length &&
    input.every((value, index) => value === expected[index])
  );
}

function readWorkspaceCollaborationCapabilityScope(
  config: DesktopRuntimeConfig,
): WorkspaceCollaborationCapabilityScope | null {
  const scope = {
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
  };
  return Object.values(scope).every((value) => value.length > 0 && value === value.trim())
    ? scope
    : null;
}
