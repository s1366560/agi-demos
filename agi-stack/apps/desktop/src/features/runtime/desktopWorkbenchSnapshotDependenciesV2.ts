import { createWorkbenchSnapshotJourneyV2 } from './desktopWorkbenchSnapshotJourneyV2';
import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopRendererGenerationActionsV2 } from '../../plugins/desktopRendererGenerationContextV2';
import { createDesktopAutomationOperationsV2 } from '../../plugins/desktopAutomationAuthorityModuleV2';
import { createProjectWorkspacesV2Client } from '../project-workspaces/projectWorkspacesV2Client';
import {
  createDesktopWorkbenchCapabilityClient,
  type DesktopWorkbenchCapabilityClient,
} from './workbenchCapabilityClient';
import {
  createWorkbenchSnapshotOperationTrackerV2,
  requireActiveWorkbenchSnapshotV2,
} from './desktopWorkbenchSnapshotSettlementV2';
import { createDesktopPluginMarketplaceOperationsV2 } from '../../plugins/desktopPluginMarketplaceAuthorityModulesV2';
import { createDesktopProjectBlackboardOperationsV2 } from '../../plugins/desktopProjectBlackboardAuthorityModuleV2';
import { createDesktopProjectAgentDashboardOperationsV2 } from '../../plugins/desktopProjectAgentDashboardAuthorityModuleV2';
import { createDesktopProjectAgentLogsOperationsV2 } from '../../plugins/desktopProjectAgentLogsAuthorityModuleV2';
import { createDesktopProjectAgentPatternsOperationsV2 } from '../../plugins/desktopProjectAgentPatternsAuthorityModuleV2';
import { createDesktopProjectCommunitiesOperationsV2 } from '../../plugins/desktopProjectCommunitiesAuthorityModuleV2';
import { createDesktopProjectMemoriesOperationsV2 } from '../../plugins/desktopProjectMemoriesAuthorityModuleV2';
import { createDesktopProjectTeamOperationsV2 } from '../../plugins/desktopProjectTeamAuthorityModuleV2';
import { createDesktopProjectSchemaOperationsV2 } from '../../plugins/desktopProjectSchemaAuthorityModuleV2';
import { createDesktopProjectMaintenanceOperationsV2 } from '../../plugins/desktopProjectMaintenanceAuthorityModuleV2';
import { createDesktopProjectSettingsOperationsV2 } from '../../plugins/desktopProjectSettingsAuthorityModuleV2';
import { createDesktopProjectChannelsOperationsV2 } from '../../plugins/desktopProjectChannelsAuthorityModuleV2';
import { createDesktopProjectEntitiesOperationsV2 } from '../../plugins/desktopProjectEntitiesAuthorityModuleV2';
import { createDesktopProjectGraphOperationsV2 } from '../../plugins/desktopProjectGraphAuthorityModuleV2';
import { createDesktopProjectOverviewOperationsV2 } from '../../plugins/desktopProjectOverviewAuthorityModuleV2';
import { createDesktopRuntimePoolOperationsV2 } from '../../plugins/desktopRuntimePoolAuthorityModuleV2';
import { createDesktopRuntimeClustersOperationsV2 } from '../../plugins/desktopRuntimeClustersAuthorityModuleV2';
import { createDesktopRuntimeInstancesOperationsV2 } from '../../plugins/desktopRuntimeInstancesAuthorityModuleV2';
import { createDesktopRuntimeDeploymentsOperationsV2 } from '../../plugins/desktopRuntimeDeploymentsAuthorityModuleV2';
import { createDesktopBackendStoresOperationsV2 } from '../../plugins/desktopBackendStoresAuthorityModuleV2';
import { createDesktopDeadLetterQueueOperationsV2 } from '../../plugins/desktopDeadLetterQueueAuthorityModuleV2';
import { createDesktopInstanceTemplatesOperationsV2 } from '../../plugins/desktopInstanceTemplatesAuthorityModuleV2';
import { createDesktopUnifiedRuntimesOperationsV2 } from '../../plugins/desktopUnifiedRuntimesAuthorityModuleV2';
import { createDesktopTenantEventsOperationsV2 } from '../../plugins/desktopTenantEventsAuthorityModuleV2';
import { createDesktopTenantPatternsOperationsV2 } from '../../plugins/desktopTenantPatternsAuthorityModuleV2';
import { createDesktopTenantEvolutionOperationsV2 } from '../../plugins/desktopTenantEvolutionAuthorityModuleV2';
import { createDesktopTenantTemplatesOperationsV2 } from '../../plugins/desktopTenantTemplatesAuthorityModuleV2';
import { createDesktopTenantGenesOperationsV2 } from '../../plugins/desktopTenantGenesAuthorityModuleV2';
import { createDesktopTenantOrganizationSettingsOperationsV2 } from '../../plugins/desktopTenantOrganizationSettingsAuthorityModuleV2';
import { createDesktopTenantAcpOperationsV2 } from '../../plugins/desktopTenantAcpAuthorityModuleV2';
import { createDesktopTenantDecisionRecordsOperationsV2 } from '../../plugins/desktopTenantDecisionRecordsAuthorityModuleV2';
import { createDesktopTenantSettingsOperationsV2 } from '../../plugins/desktopTenantSettingsAuthorityModuleV2';
import { createDesktopTenantWebhooksOperationsV2 } from '../../plugins/desktopTenantWebhooksAuthorityModuleV2';
import { createDesktopTenantBillingOperationsV2 } from '../../plugins/desktopTenantBillingAuthorityModuleV2';
import { createDesktopTenantAuditOperationsV2 } from '../../plugins/desktopTenantAuditAuthorityModuleV2';
import { createDesktopTenantGovernanceOperationsV2 } from '../../plugins/desktopTenantGovernanceAuthorityModuleV2';
import { createDesktopTenantTrustOperationsV2 } from '../../plugins/desktopTenantTrustAuthorityModuleV2';
import { createDesktopUserProfileOperationsV2 } from '../../plugins/desktopUserProfileAuthorityModuleV2';
import { createDesktopWorkspaceCatalogOperationsV2 } from '../../plugins/desktopWorkspaceCatalogAuthorityModuleV2';
import { createDesktopWorkspaceLifecycleOperationsV2 } from '../../plugins/desktopWorkspaceLifecycleAuthorityModuleV2';
import { createDesktopTenantAgentBindingsOperationsV2 } from '../../plugins/desktopTenantAgentBindingsAuthorityModuleV2';
import { createDesktopTenantAgentDashboardOperationsV2 } from '../../plugins/desktopTenantAgentDashboardAuthorityModuleV2';
import { createDesktopTenantAgentDefinitionsOperationsV2 } from '../../plugins/desktopTenantAgentDefinitionsAuthorityModuleV2';
import { createDesktopTenantSkillDefinitionsOperationsV2 } from '../../plugins/desktopTenantSkillDefinitionsAuthorityModuleV2';
import { createDesktopTenantProvidersOperationsV2 } from '../../plugins/desktopTenantProvidersAuthorityModuleV2';
import { createDesktopProjectMcpServersOperationsV2 } from '../../plugins/desktopProjectMcpServersAuthorityModuleV2';
import { createDesktopTenantAnalyticsOperationsV2 } from '../../plugins/desktopTenantAnalyticsAuthorityModuleV2';
import { createDesktopTenantOverviewOperationsV2 } from '../../plugins/desktopTenantOverviewAuthorityModuleV2';
import { createDesktopTenantProjectsOperationsV2 } from '../../plugins/desktopTenantProjectsAuthorityModuleV2';
import { createDesktopTenantTasksOperationsV2 } from '../../plugins/desktopTenantTasksAuthorityModuleV2';

export function createDesktopWorkbenchSnapshotDependenciesV2(
  inputConfig: DesktopRuntimeConfig,
  resolveParentActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopWorkbenchCapabilityClient {
  const config = Object.freeze({ ...inputConfig });
  const parentActions = resolveParentActions();
  if (!parentActions) throw new Error('desktop_workbench_snapshot_parent_actions_required');
  const resolveActions = () => parentActions;
  const tracker = createWorkbenchSnapshotOperationTrackerV2();
  const automationApi = tracker.wrap(
    createDesktopAutomationOperationsV2(resolveActions, () => config),
  );
  const pluginMarketplaceOperationsV2 = tracker.wrap(
    createDesktopPluginMarketplaceOperationsV2(resolveActions),
  );
  const projectBlackboardOperationsV2 = tracker.wrap(
    createDesktopProjectBlackboardOperationsV2(resolveActions),
  );
  const projectAgentDashboardOperationsV2 = tracker.wrap(
    createDesktopProjectAgentDashboardOperationsV2(resolveActions),
  );
  const projectAgentLogsOperationsV2 = tracker.wrap(
    createDesktopProjectAgentLogsOperationsV2(resolveActions),
  );
  const projectAgentPatternsOperationsV2 = tracker.wrap(
    createDesktopProjectAgentPatternsOperationsV2(resolveActions),
  );
  const projectCommunitiesOperationsV2 = tracker.wrap(
    createDesktopProjectCommunitiesOperationsV2(resolveActions),
  );
  const projectMemoriesOperationsV2 = tracker.wrap(
    createDesktopProjectMemoriesOperationsV2(resolveActions),
  );
  const projectTeamOperationsV2 = tracker.wrap(
    createDesktopProjectTeamOperationsV2(resolveActions),
  );
  const projectSchemaOperationsV2 = tracker.wrap(
    createDesktopProjectSchemaOperationsV2(resolveActions),
  );
  const projectMaintenanceOperationsV2 = tracker.wrap(
    createDesktopProjectMaintenanceOperationsV2(resolveActions),
  );
  const projectSettingsOperationsV2 = tracker.wrap(
    createDesktopProjectSettingsOperationsV2(resolveActions),
  );
  const projectChannelsOperationsV2 = tracker.wrap(
    createDesktopProjectChannelsOperationsV2(resolveActions),
  );
  const projectEntitiesOperationsV2 = tracker.wrap(
    createDesktopProjectEntitiesOperationsV2(resolveActions),
  );
  const projectGraphOperationsV2 = tracker.wrap(
    createDesktopProjectGraphOperationsV2(resolveActions),
  );
  const projectOverviewOperationsV2 = tracker.wrap(
    createDesktopProjectOverviewOperationsV2(resolveActions),
  );
  const runtimePoolOperationsV2 = tracker.wrap(
    createDesktopRuntimePoolOperationsV2(resolveActions),
  );
  const runtimeClustersOperationsV2 = tracker.wrap(
    createDesktopRuntimeClustersOperationsV2(resolveActions),
  );
  const runtimeInstancesOperationsV2 = tracker.wrap(
    createDesktopRuntimeInstancesOperationsV2(resolveActions),
  );
  const runtimeDeploymentsOperationsV2 = tracker.wrap(
    createDesktopRuntimeDeploymentsOperationsV2(resolveActions),
  );
  const backendStoresOperationsV2 = tracker.wrap(
    createDesktopBackendStoresOperationsV2(resolveActions),
  );
  const deadLetterQueueOperationsV2 = tracker.wrap(
    createDesktopDeadLetterQueueOperationsV2(resolveActions),
  );
  const instanceTemplatesOperationsV2 = tracker.wrap(
    createDesktopInstanceTemplatesOperationsV2(resolveActions),
  );
  const unifiedRuntimesOperationsV2 = tracker.wrap(
    createDesktopUnifiedRuntimesOperationsV2(resolveActions),
  );
  const tenantEventsOperationsV2 = tracker.wrap(
    createDesktopTenantEventsOperationsV2(resolveActions),
  );
  const tenantPatternsOperationsV2 = tracker.wrap(
    createDesktopTenantPatternsOperationsV2(resolveActions),
  );
  const tenantEvolutionOperationsV2 = tracker.wrap(
    createDesktopTenantEvolutionOperationsV2(resolveActions),
  );
  const tenantTemplatesOperationsV2 = tracker.wrap(
    createDesktopTenantTemplatesOperationsV2(resolveActions),
  );
  const tenantGenesOperationsV2 = tracker.wrap(
    createDesktopTenantGenesOperationsV2(resolveActions),
  );
  const tenantOrganizationSettingsOperationsV2 = tracker.wrap(
    createDesktopTenantOrganizationSettingsOperationsV2(resolveActions),
  );
  const tenantAcpOperationsV2 = tracker.wrap(createDesktopTenantAcpOperationsV2(resolveActions));
  const tenantDecisionRecordsOperationsV2 = tracker.wrap(
    createDesktopTenantDecisionRecordsOperationsV2(resolveActions),
  );
  const tenantSettingsOperationsV2 = tracker.wrap(
    createDesktopTenantSettingsOperationsV2(resolveActions),
  );
  const tenantWebhooksOperationsV2 = tracker.wrap(
    createDesktopTenantWebhooksOperationsV2(resolveActions),
  );
  const tenantBillingOperationsV2 = tracker.wrap(
    createDesktopTenantBillingOperationsV2(resolveActions),
  );
  const tenantAuditOperationsV2 = tracker.wrap(
    createDesktopTenantAuditOperationsV2(resolveActions),
  );
  const tenantGovernanceOperationsV2 = tracker.wrap(
    createDesktopTenantGovernanceOperationsV2(resolveActions),
  );
  const tenantTrustOperationsV2 = tracker.wrap(
    createDesktopTenantTrustOperationsV2(resolveActions),
  );
  const userProfileOperationsV2 = tracker.wrap(
    createDesktopUserProfileOperationsV2(resolveActions),
  );
  const desktopWorkspaceCatalogOperationsV2 = tracker.wrap(
    createDesktopWorkspaceCatalogOperationsV2(resolveActions),
  );
  const desktopWorkspaceLifecycleOperationsV2 = tracker.wrap(
    createDesktopWorkspaceLifecycleOperationsV2(resolveActions),
  );
  const tenantAgentBindingsOperationsV2 = tracker.wrap(
    createDesktopTenantAgentBindingsOperationsV2(resolveActions),
  );
  const tenantAgentDashboardOperationsV2 = tracker.wrap(
    createDesktopTenantAgentDashboardOperationsV2(resolveActions),
  );
  const tenantAgentDefinitionsOperationsV2 = tracker.wrap(
    createDesktopTenantAgentDefinitionsOperationsV2(resolveActions),
  );
  const tenantSkillDefinitionsOperationsV2 = tracker.wrap(
    createDesktopTenantSkillDefinitionsOperationsV2(resolveActions),
  );
  const tenantProvidersOperationsV2 = tracker.wrap(
    createDesktopTenantProvidersOperationsV2(resolveActions),
  );
  const projectMcpServersOperationsV2 = tracker.wrap(
    createDesktopProjectMcpServersOperationsV2(resolveActions),
  );
  const tenantAnalyticsOperationsV2 = tracker.wrap(
    createDesktopTenantAnalyticsOperationsV2(resolveActions),
  );
  const tenantOverviewOperationsV2 = tracker.wrap(
    createDesktopTenantOverviewOperationsV2(resolveActions),
  );
  const tenantProjectsOperationsV2 = tracker.wrap(
    createDesktopTenantProjectsOperationsV2(resolveActions),
  );
  const tenantTasksOperationsV2 = tracker.wrap(
    createDesktopTenantTasksOperationsV2(resolveActions),
  );
  const client = createDesktopWorkbenchCapabilityClient(automationApi, config, {
    agentWorkspaceJourneyClient: createWorkbenchSnapshotJourneyV2(config),
    pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2,
    projectBlackboardOperationsV2: projectBlackboardOperationsV2,
    projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2,
    projectAgentLogsOperationsV2: projectAgentLogsOperationsV2,
    projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2,
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2,
    projectMemoriesOperationsV2: projectMemoriesOperationsV2,
    projectTeamOperationsV2: projectTeamOperationsV2,
    projectSchemaOperationsV2: projectSchemaOperationsV2,
    projectMaintenanceOperationsV2: projectMaintenanceOperationsV2,
    projectSettingsOperationsV2: projectSettingsOperationsV2,
    projectChannelsOperationsV2: projectChannelsOperationsV2,
    projectEntitiesOperationsV2: projectEntitiesOperationsV2,
    projectGraphOperationsV2: projectGraphOperationsV2,
    projectOverviewOperationsV2: projectOverviewOperationsV2,
    runtimePoolOperationsV2: runtimePoolOperationsV2,
    runtimeClustersOperationsV2: runtimeClustersOperationsV2,
    runtimeInstancesOperationsV2: runtimeInstancesOperationsV2,
    runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2,
    backendStoresOperationsV2: backendStoresOperationsV2,
    deadLetterQueueOperationsV2: deadLetterQueueOperationsV2,
    instanceTemplatesOperationsV2: instanceTemplatesOperationsV2,
    unifiedRuntimesOperationsV2: unifiedRuntimesOperationsV2,
    tenantEventsOperationsV2: tenantEventsOperationsV2,
    tenantPatternsOperationsV2: tenantPatternsOperationsV2,
    tenantEvolutionOperationsV2: tenantEvolutionOperationsV2,
    tenantTemplatesOperationsV2: tenantTemplatesOperationsV2,
    tenantGenesOperationsV2: tenantGenesOperationsV2,
    tenantOrganizationSettingsOperationsV2: tenantOrganizationSettingsOperationsV2,
    tenantAcpOperationsV2: tenantAcpOperationsV2,
    tenantDecisionRecordsOperationsV2: tenantDecisionRecordsOperationsV2,
    tenantSettingsOperationsV2: tenantSettingsOperationsV2,
    tenantWebhooksOperationsV2: tenantWebhooksOperationsV2,
    tenantBillingOperationsV2: tenantBillingOperationsV2,
    tenantAuditOperationsV2: tenantAuditOperationsV2,
    tenantGovernanceOperationsV2: tenantGovernanceOperationsV2,
    tenantTrustOperationsV2: tenantTrustOperationsV2,
    userProfileOperationsV2: userProfileOperationsV2,
    projectWorkspacesClient: createProjectWorkspacesV2Client(config, {
      catalogOperations: desktopWorkspaceCatalogOperationsV2,
      lifecycleOperations: desktopWorkspaceLifecycleOperationsV2,
    }),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2,
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2,
    tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2,
    tenantSkillDefinitionsOperationsV2: tenantSkillDefinitionsOperationsV2,
    tenantProvidersOperationsV2: tenantProvidersOperationsV2,
    projectMcpServersOperationsV2: projectMcpServersOperationsV2,
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2,
    tenantOverviewOperationsV2: tenantOverviewOperationsV2,
    tenantProjectsOperationsV2: tenantProjectsOperationsV2,
    tenantTasksOperationsV2: tenantTasksOperationsV2,
  });

  return Object.freeze({
    async loadSnapshot(signal?: AbortSignal) {
      tracker.begin(signal);
      try {
        return await client.loadSnapshot(signal);
      } finally {
        await tracker.drain();
        requireActiveWorkbenchSnapshotV2(signal);
      }
    },
  });
}
