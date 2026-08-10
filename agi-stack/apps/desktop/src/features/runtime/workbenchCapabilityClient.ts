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
import { runtimeClustersCapability } from '../runtime-clusters/runtimeClustersCapability';
import { runtimeDeploymentsCapability } from '../runtime-deployments/runtimeDeploymentsCapability';
import { runtimeInstancesCapability } from '../runtime-instances/runtimeInstancesCapability';
import { runtimePoolCapability } from '../runtime-pool/runtimePoolCapability';
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
import { createCloudProjectOverviewClient } from '../project/projectOverviewCloudClient';
import { createLocalProjectOverviewClient } from '../project/projectOverviewLocalClient';
import {
  createProjectBlackboardCloudClient,
  createProjectBlackboardLocalClient,
  type ProjectBlackboardClient,
  type ProjectBlackboardScope,
  type ProjectBlackboardSnapshot,
} from '../project-blackboard/projectBlackboardClient';
import {
  createProjectKnowledgeCapabilityClients,
  loadProjectKnowledgeCapabilities,
  type ProjectKnowledgeCapabilityClients,
} from '../project-knowledge/projectKnowledgeCapabilityAuthority';
import {
  createProjectAgentCapabilityClients,
  loadProjectAgentCapabilities,
  type ProjectAgentCapabilityClients,
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
import { createProjectWorkspacesHttpClient } from '../project-workspaces/projectWorkspacesHttpClient';
import { projectSupportCapability } from '../project-support/projectSupportCapability';
import { loadTenantAnalyticsCapability } from '../tenant/tenantAnalyticsCapability';
import { loadTenantAgentDashboardCapability } from '../tenant/tenantAgentDashboardCapability';
import { loadTenantAgentBindingsCapability } from '../tenant/tenantAgentBindingsCapability';
import { loadTenantOverviewCapability } from '../tenant/tenantOverviewCapability';
import { loadTenantProjectsCapability } from '../tenant/tenantProjectsCapability';
import { tenantTasksCapability } from '../tenant/tenantTasksCapability';
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
import { WORKSPACE_HTTP_MUTATION_ACTIONS } from '../workspace/workspaceCollaborationHttpMutations';
import type { DesktopRuntimeConfig } from '../../types';
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

type AuxiliaryCloudCapabilities = Readonly<{
  backendStores: DesktopCapabilityAvailability;
  projectPlaybooks: DesktopCapabilityAvailability;
  cloudAuthorityObserved: boolean;
}>;

type ManagementRouteCapabilityClients = Readonly<
  Record<ManagementRouteCapability, ManagementRouteClient>
>;

export type DesktopWorkbenchCapabilityClientOptions = Readonly<{
  managementRouteClients?: ManagementRouteCapabilityClients;
  agentWorkspaceClient?: AgentWorkspaceAuthorityClient;
  agentWorkspaceJourneyClient?: AgentWorkspaceJourneyAuthorityClient;
  projectWorkspacesClient?: Pick<ProjectWorkspacesClient, 'list'>;
  projectBlackboardClient?: ProjectBlackboardClient;
  projectKnowledgeClients?: ProjectKnowledgeCapabilityClients;
  projectAgentClients?: ProjectAgentCapabilityClients;
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

type WorkspaceCollaborationCapabilityScope = {
  tenantId: string;
  projectId: string;
  workspaceId: string;
};

const WORKSPACE_COLLABORATION_DEGRADED_REASON =
  'workspace_collaboration_mutation_guards_unavailable';
const PROJECT_OVERVIEW_SERVICE_VERSION = '0.1.0';
const PROJECT_OVERVIEW_CONTRACT_VERSION = '3.0.0';
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
const PROJECT_WORKSPACES_SERVICE_VERSION = '0.1.0';
const PROJECT_WORKSPACES_CONTRACT_VERSION = '4.0.0';
const PROJECT_BLACKBOARD_SERVICE_VERSION = '0.1.0';
const PROJECT_BLACKBOARD_CONTRACT_VERSION = '4.0.0';

const WORKSPACE_COLLABORATION_READ_SURFACES = [
  'goals',
  'discussion',
  'status',
  'collaboration',
  'members',
  'genes',
  'files',
  'notes',
  'topology',
  'settings',
] as const;

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
  options: DesktopWorkbenchCapabilityClientOptions = {},
): DesktopWorkbenchCapabilityClient {
  const managementRouteClients =
    options.managementRouteClients ?? createManagementRouteClients(config);
  const injectedAgentWorkspaceClient = options.agentWorkspaceClient ?? null;
  const agentWorkspaceJourneyClient =
    options.agentWorkspaceJourneyClient ??
    (injectedAgentWorkspaceClient ? null : createAgentWorkspaceJourneyClient(config));
  const agentWorkspaceClient =
    injectedAgentWorkspaceClient ??
    (agentWorkspaceJourneyClient ? null : createAgentWorkspaceClient(config));
  const projectWorkspacesClient =
    options.projectWorkspacesClient ?? createProjectWorkspacesClient(config);
  const projectBlackboardClient =
    options.projectBlackboardClient ?? createProjectBlackboardClient(config);
  const projectKnowledgeClients =
    options.projectKnowledgeClients ?? createProjectKnowledgeCapabilityClients(config);
  const projectAgentClients =
    options.projectAgentClients ?? createProjectAgentCapabilityClients(config);
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
        tenantOverview,
        tenantAnalytics,
        tenantAgentDashboard,
        tenantAgentBindings,
        tenantProjects,
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
        loadWorkspaceCollaborationCapability(config, signal),
        loadProjectOverviewCapability(config, signal),
        loadTenantOverviewCapability(config, signal),
        loadTenantAnalyticsCapability(config, signal),
        loadTenantAgentDashboardCapability(config, signal),
        loadTenantAgentBindingsCapability(config, signal),
        loadTenantProjectsCapability(config, signal),
        loadManagementRouteCapabilities(managementRouteClients, config, signal),
        loadProjectWorkspacesCapability(projectWorkspacesClient, config, signal),
        loadProjectBlackboardCapability(projectBlackboardClient, config, signal),
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
          workspace_collaboration: (config.mode === 'local' ? declared : observed)(
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
          'tenant-tenant-tasks': declared(tenantTasksCapability(config)),
          'tenant-tenant-runtimes': declared(unifiedRuntimesCapability(config)),
          'tenant-tenant-pool': declared(runtimePoolCapability(config)),
          'tenant-tenant-instances': declared(runtimeInstancesCapability(config)),
          'tenant-tenant-clusters': declared(runtimeClustersCapability(config)),
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

function createProjectWorkspacesClient(
  config: DesktopRuntimeConfig,
): Pick<ProjectWorkspacesClient, 'list'> | null {
  try {
    return createProjectWorkspacesHttpClient(config);
  } catch {
    return null;
  }
}

function createProjectBlackboardClient(
  config: DesktopRuntimeConfig,
): ProjectBlackboardClient | null {
  try {
    return config.mode === 'local'
      ? createProjectBlackboardLocalClient(config)
      : createProjectBlackboardCloudClient(config);
  } catch {
    return null;
  }
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
  client: ProjectBlackboardClient | null,
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
  if (!client) {
    return withCapabilityScope(
      unavailable('project_blackboard_authority_unavailable'),
      capabilityScope,
    );
  }
  try {
    const snapshot = await client.probe(scope, signal);
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
    authority_revision: null,
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
): ManagementRouteCapabilityClients {
  return Object.freeze({
    'tenant-tenant-providers': createProviderRouteClient(config),
    'tenant-tenant-agent-definitions': createAgentDefinitionsRouteClient(config),
    'tenant-tenant-skills': createSkillsRouteClient(config),
    'tenant-tenant-plugins': createPluginsRouteClient(config),
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
      authority_revision: null,
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

export function normalizeWorkspaceCollaborationCapabilityContract(
  input: unknown,
  scope: WorkspaceCollaborationCapabilityScope,
): DesktopCapabilityAvailability {
  const negotiation = negotiateCapabilityContract(input, DESKTOP_MINIMUM_CONTRACT_VERSION);
  if (!negotiation.compatible) {
    return unavailable(
      negotiation.reason_code ?? 'capability_contract_version_invalid',
      negotiation,
    );
  }
  if (!isRecord(input)) {
    return unavailable('workspace_collaboration_capability_contract_invalid', negotiation);
  }
  if (
    input.authority !== 'cloud' ||
    input.canonical_read !== true ||
    !matchesExactStringArray(input.read_surfaces, WORKSPACE_COLLABORATION_READ_SURFACES) ||
    input.tenant_id !== scope.tenantId ||
    input.project_id !== scope.projectId ||
    input.workspace_id !== scope.workspaceId
  ) {
    return unavailable(
      input.tenant_id !== scope.tenantId ||
        input.project_id !== scope.projectId ||
        input.workspace_id !== scope.workspaceId
        ? 'workspace_collaboration_capability_scope_mismatch'
        : 'workspace_collaboration_capability_contract_invalid',
      negotiation,
    );
  }
  const capabilityKeys = [
    'service_version',
    'contract_version',
    'authority',
    'tenant_id',
    'project_id',
    'workspace_id',
    'status',
    'reason_code',
    'canonical_read',
    'read_surfaces',
    'mutations',
    'allowed_actions',
  ];
  if (
    input.status === 'available' &&
    isExactRecord(input, capabilityKeys) &&
    input.reason_code === null &&
    isExactRecord(input.mutations, [
      'allowed',
      'revision_guarded',
      'idempotency_guarded',
      'actions',
    ]) &&
    input.mutations.allowed === true &&
    input.mutations.revision_guarded === true &&
    input.mutations.idempotency_guarded === true &&
    matchesWorkspaceMutationActions(input.mutations.actions) &&
    JSON.stringify(input.allowed_actions) === JSON.stringify(input.mutations.actions)
  ) {
    return available(negotiation, {
      allowedActions: mergeWorkspaceActions(
        workspaceReadActions(),
        flattenWorkspaceMutationActions(input.mutations.actions),
      ),
    });
  }
  if (
    !isExactRecord(input, capabilityKeys) ||
    input.status !== 'degraded' ||
    input.reason_code !== WORKSPACE_COLLABORATION_DEGRADED_REASON ||
    !isExactRecord(input.mutations, ['allowed', 'revision_guarded', 'idempotency_guarded']) ||
    input.mutations.allowed !== false ||
    input.mutations.revision_guarded !== false ||
    input.mutations.idempotency_guarded !== false
  ) {
    return unavailable('workspace_collaboration_capability_contract_invalid', negotiation);
  }
  return degraded(WORKSPACE_COLLABORATION_DEGRADED_REASON, negotiation, {
    allowedActions: workspaceReadActions(),
  });
}

export function normalizeWorkspaceCollaborationAuthorityContract(
  input: unknown,
  scope: WorkspaceCollaborationCapabilityScope,
): number | null {
  if (
    !isExactRecord(input, [
      'contract_version',
      'tenant_id',
      'project_id',
      'workspace_id',
      'revision',
      'cursor',
    ]) ||
    input.contract_version !== '2.0.0' ||
    input.tenant_id !== scope.tenantId ||
    input.project_id !== scope.projectId ||
    input.workspace_id !== scope.workspaceId ||
    !Number.isSafeInteger(input.revision) ||
    Number(input.revision) < 0 ||
    typeof input.cursor !== 'string' ||
    input.cursor.length === 0 ||
    input.cursor !== input.cursor.trim()
  ) {
    return null;
  }
  return Number(input.revision);
}

function workspaceReadActions(): string[] {
  return WORKSPACE_COLLABORATION_READ_SURFACES.map((surface) => `${surface}:view`);
}

function mergeWorkspaceActions(...actionGroups: readonly string[][]): string[] {
  return [...new Set(actionGroups.flat())];
}

function matchesWorkspaceMutationActions(input: unknown): boolean {
  const surfaces = Object.keys(WORKSPACE_HTTP_MUTATION_ACTIONS);
  if (!isExactRecord(input, surfaces)) return false;
  return surfaces.every((surface) =>
    matchesExactStringArray(
      input[surface],
      WORKSPACE_HTTP_MUTATION_ACTIONS[surface as keyof typeof WORKSPACE_HTTP_MUTATION_ACTIONS],
    ),
  );
}

function flattenWorkspaceMutationActions(input: unknown): string[] {
  if (!isRecord(input) || !matchesWorkspaceMutationActions(input)) return [];
  return Object.keys(WORKSPACE_HTTP_MUTATION_ACTIONS).flatMap((surface) =>
    (input[surface] as string[]).map((action) => `${surface}:${action}`),
  );
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
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  if (config.mode === 'local') {
    return unavailable('local_workspace_collaboration_unavailable');
  }
  const scope = readWorkspaceCollaborationCapabilityScope(config);
  if (!scope) {
    return unavailable('workspace_collaboration_capability_scope_unavailable');
  }

  try {
    const headers = new Headers({ Accept: 'application/json' });
    const credential = desktopApiCredential(config);
    if (credential) headers.set('Authorization', `Bearer ${credential}`);
    const launchCapability = desktopLaunchCapability(config);
    if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
    const scopedPath =
      `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}/projects/` +
      `${encodeURIComponent(scope.projectId)}/workspaces/` +
      `${encodeURIComponent(scope.workspaceId)}/collaboration`;
    const response = await desktopApiFetch(config, `${scopedPath}/capabilities`, {
      headers,
      signal,
    });
    if (!response.ok) {
      return unavailable('workspace_collaboration_capability_contract_unavailable');
    }
    const contentType = response.headers.get('content-type') ?? '';
    if (!contentType.includes('application/json')) {
      return unavailable('workspace_collaboration_capability_contract_invalid');
    }
    const payload = await response.json().catch(() => null);
    const capability = normalizeWorkspaceCollaborationCapabilityContract(payload, scope);
    if (capability.availability !== 'available' && capability.availability !== 'degraded') {
      return capability;
    }

    const authorityResponse = await desktopApiFetch(
      config,
      `${scopedPath}/authority`,
      {
        headers,
        signal,
      },
    );
    if (!authorityResponse.ok) {
      return closeCapabilityAuthority(
        capability,
        'workspace_collaboration_authority_contract_unavailable',
      );
    }
    const authorityContentType = authorityResponse.headers.get('content-type') ?? '';
    if (!authorityContentType.includes('application/json')) {
      return closeCapabilityAuthority(
        capability,
        'workspace_collaboration_authority_contract_invalid',
      );
    }
    const authorityPayload = await authorityResponse.json().catch(() => null);
    const authorityRevision = normalizeWorkspaceCollaborationAuthorityContract(
      authorityPayload,
      scope,
    );
    if (authorityRevision === null) {
      return closeCapabilityAuthority(
        capability,
        'workspace_collaboration_authority_contract_invalid',
      );
    }
    return { ...capability, authority_revision: authorityRevision };
  } catch (error) {
    if (signal?.aborted) throw error;
    return unavailable('workspace_collaboration_capability_contract_unavailable');
  }
}

function closeCapabilityAuthority(
  capability: DesktopCapabilityAvailability,
  reasonCode: string,
): DesktopCapabilityAvailability {
  return {
    ...capability,
    availability: 'unavailable',
    reason_code: reasonCode,
    allowed_actions: [],
    authority_revision: null,
  };
}

async function loadProjectOverviewCapability(
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const tenantId = scopeIdentifier(config.tenantId);
  const projectId = scopeIdentifier(config.projectId);
  if (!tenantId || !projectId) {
    return unavailable('project_overview_scope_unavailable');
  }

  try {
    if (config.mode === 'local') {
      const snapshot = await createLocalProjectOverviewClient(config).load(
        {
          authority: 'local',
          tenantId,
          projectId,
        },
        { signal },
      );
      return {
        availability: snapshot.capability.availability,
        reason_code: snapshot.capability.reasonCode,
        service_version: snapshot.capability.serviceVersion,
        contract_version: snapshot.capability.contractVersion,
        allowed_actions: [...snapshot.capability.allowedActions],
        scope: {
          tenant_id: snapshot.capability.scope.tenantId,
          project_id: snapshot.capability.scope.projectId,
          workspace_id: snapshot.capability.scope.workspaceId,
          instance_id: snapshot.capability.scope.instanceId,
        },
        authority_revision: snapshot.capability.authorityRevision,
      };
    }

    const cloudClient = createCloudProjectOverviewClient(config);
    const scope = {
      authority: 'cloud' as const,
      tenantId,
      projectId,
    };
    await cloudClient.getProject(scope, { signal });
    await cloudClient.getProjectStats(scope, { signal });
    return {
      availability: 'available',
      reason_code: null,
      service_version: PROJECT_OVERVIEW_SERVICE_VERSION,
      contract_version: PROJECT_OVERVIEW_CONTRACT_VERSION,
      allowed_actions: ['view', 'inspect-stats'],
      scope: emptyCapabilityScope(),
      authority_revision: null,
    };
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
