import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopPluginMarketplaceCatalogOperationsV2 } from '../../plugins/desktopPluginMarketplaceAuthorityModulesV2';
import type { DesktopProjectBlackboardOperationsV2 } from '../../plugins/desktopProjectBlackboardAuthorityModuleV2';
import type { DesktopProjectOverviewOperationsV2 } from '../../plugins/desktopProjectOverviewAuthorityModuleV2';
import type { DesktopProjectAgentDashboardOperationsV2 } from '../../plugins/desktopProjectAgentDashboardAuthorityModuleV2';
import type { DesktopProjectAgentLogsOperationsV2 } from '../../plugins/desktopProjectAgentLogsAuthorityModuleV2';
import type { DesktopProjectAgentPatternsOperationsV2 } from '../../plugins/desktopProjectAgentPatternsAuthorityModuleV2';
import type { DesktopProjectCommunitiesOperationsV2 } from '../../plugins/desktopProjectCommunitiesAuthorityModuleV2';
import type { DesktopProjectEntitiesOperationsV2 } from '../../plugins/desktopProjectEntitiesAuthorityModuleV2';
import type { DesktopProjectGraphOperationsV2 } from '../../plugins/desktopProjectGraphAuthorityModuleV2';
import type { DesktopProjectMemoriesOperationsV2 } from '../../plugins/desktopProjectMemoriesAuthorityModuleV2';
import type { DesktopProjectTeamOperationsV2 } from '../../plugins/desktopProjectTeamAuthorityModuleV2';
import type { DesktopProjectSchemaOperationsV2 } from '../../plugins/desktopProjectSchemaAuthorityModuleV2';
import type { DesktopProjectMaintenanceOperationsV2 } from '../../plugins/desktopProjectMaintenanceAuthorityModuleV2';
import type { DesktopProjectSettingsOperationsV2 } from '../../plugins/desktopProjectSettingsAuthorityModuleV2';
import type { DesktopRuntimePoolOperationsV2 } from '../../plugins/desktopRuntimePoolAuthorityModuleV2';
import type { DesktopRuntimeClustersOperationsV2 } from '../../plugins/desktopRuntimeClustersAuthorityModuleV2';
import type { DesktopRuntimeInstancesOperationsV2 } from '../../plugins/desktopRuntimeInstancesAuthorityModuleV2';
import type { DesktopRuntimeDeploymentsOperationsV2 } from '../../plugins/desktopRuntimeDeploymentsAuthorityModuleV2';
import type { DesktopBackendStoresOperationsV2 } from '../../plugins/desktopBackendStoresAuthorityModuleV2';
import type { DesktopDeadLetterQueueOperationsV2 } from '../../plugins/desktopDeadLetterQueueAuthorityModuleV2';
import type { DesktopInstanceTemplatesOperationsV2 } from '../../plugins/desktopInstanceTemplatesAuthorityModuleV2';
import type { DesktopTenantEventsOperationsV2 } from '../../plugins/desktopTenantEventsAuthorityModuleV2';
import type { DesktopTenantPatternsOperationsV2 } from '../../plugins/desktopTenantPatternsAuthorityModuleV2';
import type { DesktopTenantDecisionRecordsOperationsV2 } from '../../plugins/desktopTenantDecisionRecordsAuthorityModuleV2';
import type { DesktopTenantSettingsOperationsV2 } from '../../plugins/desktopTenantSettingsAuthorityModuleV2';
import type { DesktopTenantWebhooksOperationsV2 } from '../../plugins/desktopTenantWebhooksAuthorityModuleV2';
import type { DesktopTenantBillingOperationsV2 } from '../../plugins/desktopTenantBillingAuthorityModuleV2';
import type { DesktopUnifiedRuntimesOperationsV2 } from '../../plugins/desktopUnifiedRuntimesAuthorityModuleV2';
import type { DesktopTenantAnalyticsOperationsV2 } from '../../plugins/desktopTenantAnalyticsAuthorityModuleV2';
import type { DesktopTenantAgentBindingsOperationsV2 } from '../../plugins/desktopTenantAgentBindingsAuthorityModuleV2';
import type { DesktopTenantAgentDashboardOperationsV2 } from '../../plugins/desktopTenantAgentDashboardAuthorityModuleV2';
import type { DesktopTenantOverviewOperationsV2 } from '../../plugins/desktopTenantOverviewAuthorityModuleV2';
import type { DesktopTenantProjectsOperationsV2 } from '../../plugins/desktopTenantProjectsAuthorityModuleV2';
import type { DesktopTenantTasksOperationsV2 } from '../../plugins/desktopTenantTasksAuthorityModuleV2';
import type { DesktopWorkspaceCatalogOperationsV2 } from '../../plugins/desktopWorkspaceCatalogAuthorityModuleV2';
import type { DesktopWorkspaceLifecycleOperationsV2 } from '../../plugins/desktopWorkspaceLifecycleAuthorityModuleV2';
import { createProjectWorkspacesV2Client } from '../project-workspaces/projectWorkspacesV2Client';
import {
  createDesktopWorkbenchCapabilityClient,
  type DesktopWorkbenchCapabilityClient,
} from './workbenchCapabilityClient';

export type DesktopWorkbenchCapabilityClientProviderReasonCodeV2 =
  'desktop_workbench_capability_client_unpublished';

export class DesktopWorkbenchCapabilityClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkbenchCapabilityClientProviderReasonCodeV2;

  constructor(
    reasonCode: DesktopWorkbenchCapabilityClientProviderReasonCodeV2,
  ) {
    super(reasonCode);
    this.name = 'DesktopWorkbenchCapabilityClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopWorkbenchCapabilityClientProviderInputV2 = Readonly<{
  automationApi: Parameters<typeof createDesktopWorkbenchCapabilityClient>[0];
  config: DesktopRuntimeConfig;
  pluginMarketplaceOperationsV2: Pick<
    DesktopPluginMarketplaceCatalogOperationsV2,
    'projectMarketplacePlugins'
  >;
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
  projectTeamOperationsV2: Pick<
    DesktopProjectTeamOperationsV2,
    'loadProjectTeam'
  >;
  projectSchemaOperationsV2: Pick<
    DesktopProjectSchemaOperationsV2,
    'loadProjectSchema'
  >;
  projectMaintenanceOperationsV2: Pick<
    DesktopProjectMaintenanceOperationsV2,
    'loadProjectMaintenance'
  >;
  projectSettingsOperationsV2: Pick<
    DesktopProjectSettingsOperationsV2,
    'loadProjectSettings'
  >;
  projectEntitiesOperationsV2: Pick<
    DesktopProjectEntitiesOperationsV2,
    'loadProjectEntities' | 'loadProjectEntityRelationships'
  >;
  projectGraphOperationsV2: Pick<
    DesktopProjectGraphOperationsV2,
    'loadProjectGraph'
  >;
  projectBlackboardOperationsV2: Pick<
    DesktopProjectBlackboardOperationsV2,
    'probeProjectBlackboard' | 'probeWorkspaceCollaborationCapability'
  >;
  runtimePoolOperationsV2: Pick<
    DesktopRuntimePoolOperationsV2,
    'probeRuntimePool'
  >;
  runtimeClustersOperationsV2: Pick<
    DesktopRuntimeClustersOperationsV2,
    'probeRuntimeClusters'
  >;
  runtimeInstancesOperationsV2: Pick<
    DesktopRuntimeInstancesOperationsV2,
    'probeRuntimeInstances'
  >;
  runtimeDeploymentsOperationsV2: Pick<
    DesktopRuntimeDeploymentsOperationsV2,
    'probeRuntimeDeployments'
  >;
  backendStoresOperationsV2: Pick<
    DesktopBackendStoresOperationsV2,
    'probeBackendStores'
  >;
  deadLetterQueueOperationsV2: Pick<
    DesktopDeadLetterQueueOperationsV2,
    'probe'
  >;
  instanceTemplatesOperationsV2: Pick<
    DesktopInstanceTemplatesOperationsV2,
    'probe'
  >;
  unifiedRuntimesOperationsV2?: Pick<DesktopUnifiedRuntimesOperationsV2, 'probe'>;
  tenantEventsOperationsV2: DesktopTenantEventsOperationsV2;
  tenantPatternsOperationsV2: DesktopTenantPatternsOperationsV2;
  tenantDecisionRecordsOperationsV2: DesktopTenantDecisionRecordsOperationsV2;
  tenantSettingsOperationsV2: DesktopTenantSettingsOperationsV2;
  tenantWebhooksOperationsV2: DesktopTenantWebhooksOperationsV2;
  tenantBillingOperationsV2: DesktopTenantBillingOperationsV2;
  desktopWorkspaceCatalogOperationsV2: Pick<
    DesktopWorkspaceCatalogOperationsV2,
    'listWorkspacesForProject'
  >;
  desktopWorkspaceLifecycleOperationsV2: Pick<
    DesktopWorkspaceLifecycleOperationsV2,
    'createWorkspace'
  >;
  tenantAnalyticsOperationsV2: Pick<
    DesktopTenantAnalyticsOperationsV2,
    'loadTenantAnalytics'
  >;
  tenantAgentBindingsOperationsV2: Pick<
    DesktopTenantAgentBindingsOperationsV2,
    'listTenantAgentBindings'
  >;
  tenantAgentDashboardOperationsV2: Pick<
    DesktopTenantAgentDashboardOperationsV2,
    'loadTenantAgentDashboard'
  >;
  tenantOverviewOperationsV2: Pick<
    DesktopTenantOverviewOperationsV2,
    'loadTenantOverview'
  >;
  tenantProjectsOperationsV2: Pick<
    DesktopTenantProjectsOperationsV2,
    'listTenantProjects'
  >;
  tenantTasksOperationsV2: Pick<
    DesktopTenantTasksOperationsV2,
    'loadTenantTasks'
  >;
}>;

export type DesktopWorkbenchCapabilityClientBindingV2 = Readonly<{
  client: DesktopWorkbenchCapabilityClient;
}>;

export type DesktopWorkbenchCapabilityClientProviderV2 = Readonly<{
  publish: (
    input: DesktopWorkbenchCapabilityClientProviderInputV2,
  ) => DesktopWorkbenchCapabilityClientBindingV2;
  resolve: () => DesktopWorkbenchCapabilityClientBindingV2;
}>;

export function createDesktopWorkbenchCapabilityClientProviderV2(): DesktopWorkbenchCapabilityClientProviderV2 {
  let publication: DesktopWorkbenchCapabilityClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopWorkbenchCapabilityClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopWorkbenchCapabilityClientProviderErrorV2(
          'desktop_workbench_capability_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopWorkbenchCapabilityClientBindingV2(
  input: DesktopWorkbenchCapabilityClientProviderInputV2,
): DesktopWorkbenchCapabilityClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  const client = createDesktopWorkbenchCapabilityClient(input.automationApi, config, {
      pluginMarketplaceOperationsV2: input.pluginMarketplaceOperationsV2,
      projectBlackboardOperationsV2: input.projectBlackboardOperationsV2,
      projectAgentDashboardOperationsV2:
        input.projectAgentDashboardOperationsV2,
      projectAgentLogsOperationsV2: input.projectAgentLogsOperationsV2,
      projectAgentPatternsOperationsV2: input.projectAgentPatternsOperationsV2,
      projectCommunitiesOperationsV2: input.projectCommunitiesOperationsV2,
      projectMemoriesOperationsV2: input.projectMemoriesOperationsV2,
      projectTeamOperationsV2: input.projectTeamOperationsV2,
      projectSchemaOperationsV2: input.projectSchemaOperationsV2,
      projectMaintenanceOperationsV2: input.projectMaintenanceOperationsV2,
      projectSettingsOperationsV2: input.projectSettingsOperationsV2,
      projectEntitiesOperationsV2: input.projectEntitiesOperationsV2,
      projectGraphOperationsV2: input.projectGraphOperationsV2,
      projectOverviewOperationsV2: input.projectOverviewOperationsV2,
      runtimePoolOperationsV2: input.runtimePoolOperationsV2,
      runtimeClustersOperationsV2: input.runtimeClustersOperationsV2,
      runtimeInstancesOperationsV2: input.runtimeInstancesOperationsV2,
      runtimeDeploymentsOperationsV2: input.runtimeDeploymentsOperationsV2,
      backendStoresOperationsV2: input.backendStoresOperationsV2,
      deadLetterQueueOperationsV2: input.deadLetterQueueOperationsV2,
      instanceTemplatesOperationsV2: input.instanceTemplatesOperationsV2,
      unifiedRuntimesOperationsV2: input.unifiedRuntimesOperationsV2,
      tenantEventsOperationsV2: input.tenantEventsOperationsV2,
      tenantPatternsOperationsV2: input.tenantPatternsOperationsV2,
      tenantDecisionRecordsOperationsV2: input.tenantDecisionRecordsOperationsV2,
      tenantSettingsOperationsV2: input.tenantSettingsOperationsV2,
      tenantWebhooksOperationsV2: input.tenantWebhooksOperationsV2,
      tenantBillingOperationsV2: input.tenantBillingOperationsV2,
      projectWorkspacesClient: createProjectWorkspacesV2Client(config, {
        catalogOperations: input.desktopWorkspaceCatalogOperationsV2,
        lifecycleOperations: input.desktopWorkspaceLifecycleOperationsV2,
      }),
      tenantAgentBindingsOperationsV2: input.tenantAgentBindingsOperationsV2,
      tenantAgentDashboardOperationsV2: input.tenantAgentDashboardOperationsV2,
      tenantAnalyticsOperationsV2: input.tenantAnalyticsOperationsV2,
      tenantOverviewOperationsV2: input.tenantOverviewOperationsV2,
      tenantProjectsOperationsV2: input.tenantProjectsOperationsV2,
      tenantTasksOperationsV2: input.tenantTasksOperationsV2,
  });
  return Object.freeze({ client });
}
