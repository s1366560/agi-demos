import { type Dispatch, type RefObject, type SetStateAction, useEffect } from 'react';

import type { DesktopHashLocationPort } from './desktopHashRouteHost';
import type { AuthState, DesktopRuntimeConfig } from '../../types';
import { desktopVaultBoundCloudRequestBroker } from '../../api/cloudRequestBroker';
import {
  AGENT_WORKSPACE_ROUTE_ID,
  createAgentWorkspaceRouteModuleLoader,
} from '../agent-workspace/agentWorkspaceRouteModule';
import { createBackendStoresController } from '../backend-stores/backendStoresController';
import { createBackendStoresRouteModuleLoader } from '../backend-stores/backendStoresRouteModule';
import { isIdentityAuthenticated } from '../auth/authContextModel';
import { createDeviceApprovalClient } from '../device-approval/deviceApprovalClient';
import { readDeviceApprovalCodeFromHash } from '../device-approval/deviceApprovalModel';
import { createDeviceApprovalRouteModuleLoader } from '../device-approval/deviceApprovalRouteModule';
import { upsertCreatedTenant } from '../tenant-creation/tenantCreationModel';
import { createTenantCreationRouteModuleLoader } from '../tenant-creation/tenantCreationRouteModule';
import {
  createInvitationAcceptanceClient,
  type InvitationAcceptanceClient,
} from '../invitation-acceptance/invitationAcceptanceClient';
import { readInvitationTokenFromHash } from '../invitation-acceptance/invitationAcceptanceModel';
import { createInvitationAcceptanceRouteModuleLoader } from '../invitation-acceptance/invitationAcceptanceRouteModule';
import type {
  ProjectCronJobsRouteBindingProviderV2,
} from '../automations/projectCronJobsRouteBindingProviderV2';
import { createProjectCronJobsRouteModuleLoader } from '../automations/projectCronJobsRouteModule';
import {
  createDesktopProductionRouteRegistry,
  registerDesktopProductionRouteLoaders,
  DEVICE_APPROVAL_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
  TENANT_CREATION_ROUTE_ID,
  PROJECT_CRON_JOBS_ROUTE_ID,
  PROJECT_BLACKBOARD_ROUTE_ID,
  PROJECT_CHANNELS_ROUTE_ID,
  PROJECT_COMMUNITIES_ROUTE_ID,
  PROJECT_ENTITIES_ROUTE_ID,
  PROJECT_GRAPH_ROUTE_ID,
  PROJECT_AGENT_DASHBOARD_ROUTE_ID,
  PROJECT_AGENT_LOGS_ROUTE_ID,
  PROJECT_AGENT_PATTERNS_ROUTE_ID,
  PROJECT_SCHEMA_ROUTE_ID,
  PROJECT_MAINTENANCE_ROUTE_ID,
  PROJECT_SETTINGS_ROUTE_ID,
  PROJECT_MEMORIES_ROUTE_ID,
  PROJECT_OVERVIEW_ROUTE_ID,
  PROJECT_SEARCH_ROUTE_ID,
  PROJECT_SUPPORT_ROUTE_ID,
  PROJECT_PLAYBOOKS_ROUTE_ID,
  BACKEND_STORES_ROUTE_ID,
  PROJECT_TEAM_ROUTE_ID,
  PROJECT_WORKSPACES_ROUTE_ID,
  TENANT_OVERVIEW_ROUTE_ID,
  TENANT_ANALYTICS_ROUTE_ID,
  TENANT_AGENT_DASHBOARD_ROUTE_ID,
  TENANT_AGENT_BINDINGS_ROUTE_ID,
  TENANT_AGENT_DEFINITIONS_ROUTE_ID,
  TENANT_CLUSTERS_ROUTE_ID,
  TENANT_DEPLOY_ROUTE_ID,
  TENANT_INSTANCE_TEMPLATES_ROUTE_ID,
  TENANT_INSTANCES_ROUTE_ID,
  TENANT_POOL_ROUTE_ID,
  TENANT_PROVIDERS_ROUTE_ID,
  TENANT_PLUGINS_ROUTE_ID,
  TENANT_PROJECTS_ROUTE_ID,
  TENANT_RUNTIMES_ROUTE_ID,
  TENANT_SKILLS_ROUTE_ID,
  TENANT_EVOLUTION_ROUTE_ID,
  TENANT_TASKS_ROUTE_ID,
  TENANT_DEAD_LETTER_QUEUE_ROUTE_ID,
  TENANT_PATTERNS_ROUTE_ID,
  TENANT_ACP_ROUTE_ID,
  TENANT_WEBHOOKS_ROUTE_ID,
  TENANT_GENES_ROUTE_ID,
  TENANT_EVENTS_ROUTE_ID,
  TENANT_DECISION_RECORDS_ROUTE_ID,
  TENANT_ORGANIZATION_SETTINGS_ROUTE_ID,
  TENANT_SETTINGS_ROUTE_ID,
  TENANT_MCP_SERVERS_ROUTE_ID,
  TENANT_TEMPLATES_ROUTE_ID,
  TENANT_USERS_ROUTE_ID,
  TENANT_AUDIT_LOGS_ROUTE_ID,
  TENANT_TRUST_POLICIES_ROUTE_ID,
  TENANT_BILLING_ROUTE_ID,
  TENANT_WORKSPACES_ROUTE_ID,
} from './desktopProductionRouteRegistry';
import { createProjectPlaybooksController } from '../project-playbooks/projectPlaybooksController';
import { createProjectPlaybooksRouteModuleLoader } from '../project-playbooks/projectPlaybooksRouteModule';
import {
  createDeadLetterQueueRouteBindingForRuntime,
  createProjectOverviewRouteBindingForRuntime,
  createRuntimeClustersRouteBindingForRuntime,
  createRuntimeDeploymentsRouteBindingForRuntime,
  createInstanceTemplatesRouteBindingForRuntime,
  createRuntimeInstancesRouteBindingForRuntime,
  createRuntimePoolRouteBindingForRuntime,
  createUnifiedRuntimesRouteBindingForRuntime,
  createTenantOverviewRouteBindingForRuntime,
  createTenantAnalyticsRouteBindingForRuntime,
  createTenantAgentDashboardRouteBindingForRuntime,
  createTenantAgentBindingsRouteBindingForRuntime,
  createTenantProjectsRouteBindingForRuntime,
  createTenantTasksRouteBindingForRuntime,
  createTenantWorkspacesRouteBindingForRuntime,
} from './desktopProductionRouteRuntime';
import { createProjectOverviewRouteModuleLoader } from '../project/projectOverviewRouteModule';
import { createProjectAgentDashboardController } from '../project-agent/projectAgentDashboardController';
import { createProjectAgentDashboardRouteModuleLoader } from '../project-agent/projectAgentDashboardRouteModule';
import { createProjectAgentLogsController } from '../project-agent/projectAgentLogsController';
import { createProjectAgentLogsRouteModuleLoader } from '../project-agent/projectAgentLogsRouteModule';
import { createProjectAgentPatternsController } from '../project-agent/projectAgentPatternsController';
import { createProjectAgentPatternsRouteModuleLoader } from '../project-agent/projectAgentPatternsRouteModule';
import { createProjectMaintenanceController } from '../project-administration/projectMaintenanceController';
import { createProjectMaintenanceRouteModuleLoader } from '../project-administration/projectMaintenanceRouteModule';
import { createProjectSchemaController } from '../project-administration/projectSchemaController';
import { createProjectSchemaRouteModuleLoader } from '../project-administration/projectSchemaRouteModule';
import { createProjectSettingsController } from '../project-administration/projectSettingsController';
import { createProjectSettingsRouteModuleLoader } from '../project-administration/projectSettingsRouteModule';
import {
  buildProjectBlackboardCanonicalPath,
  createProjectBlackboardRouteModuleLoader,
} from '../project-blackboard/projectBlackboardRouteModule';
import { createProjectBlackboardV2Client } from '../project-blackboard/projectBlackboardClient';
import { createProjectBlackboardController } from '../project-blackboard/projectBlackboardController';
import { createProjectCommunitiesController } from '../project-knowledge/projectCommunitiesController';
import { createProjectCommunitiesRouteModuleLoader } from '../project-knowledge/projectCommunitiesRouteModule';
import { createProjectEntitiesController } from '../project-knowledge/projectEntitiesController';
import { createProjectEntitiesRouteModuleLoader } from '../project-knowledge/projectEntitiesRouteModule';
import { createProjectGraphController } from '../project-knowledge/projectGraphController';
import { createProjectGraphRouteModuleLoader } from '../project-knowledge/projectGraphRouteModule';
import { createProjectMemoriesController } from '../project-knowledge/projectMemoriesController';
import { createProjectMemoriesRouteModuleLoader } from '../project-knowledge/projectMemoriesRouteModule';
import { createProjectTeamController } from '../project-knowledge/projectTeamController';
import { createProjectTeamRouteModuleLoader } from '../project-knowledge/projectTeamRouteModule';
import { createProjectWorkspacesController } from '../project-workspaces/projectWorkspacesController';
import { createProjectWorkspacesV2Client } from '../project-workspaces/projectWorkspacesV2Client';
import { createProjectWorkspacesRouteModuleLoader } from '../project-workspaces/projectWorkspacesRouteModule';
import { createProjectSupportRouteModuleLoader } from '../project-support/projectSupportRouteModule';
import { createProjectSupportController } from '../project-support/projectSupportController';
import { createDeadLetterQueueRouteModuleLoader } from '../governance/deadLetterQueueRouteModule';
import { createInstanceTemplatesRouteModuleLoader } from '../instance-templates/instanceTemplatesRouteModule';
import { createRuntimeClustersRouteModuleLoader } from '../runtime-clusters/runtimeClustersRouteModule';
import { createRuntimeDeploymentsRouteModuleLoader } from '../runtime-deployments/runtimeDeploymentsRouteModule';
import { createRuntimeInstancesRouteModuleLoader } from '../runtime-instances/runtimeInstancesRouteModule';
import { createRuntimePoolRouteModuleLoader } from '../runtime-pool/runtimePoolRouteModule';
import { createUnifiedRuntimesRouteModuleLoader } from '../unified-runtimes/unifiedRuntimesRouteModule';
import { createTenantOverviewRouteModuleLoader } from '../tenant/tenantOverviewRouteModule';
import { createTenantAnalyticsRouteModuleLoader } from '../tenant/tenantAnalyticsRouteModule';
import { createTenantAgentDashboardRouteModuleLoader } from '../tenant/tenantAgentDashboardRouteModule';
import { createTenantAgentBindingsRouteModuleLoader } from '../tenant/tenantAgentBindingsRouteModule';
import { createTenantProjectsRouteModuleLoader } from '../tenant/tenantProjectsRouteModule';
import { createTenantTasksRouteModuleLoader } from '../tenant/tenantTasksRouteModule';
import { createTenantWorkspacesRouteModuleLoader } from '../tenant/tenantWorkspacesRouteModule';
import { createTenantGovernanceRouteModuleLoader } from '../tenant-admin/tenantGovernanceRouteModule';
import { createTenantBillingRouteModuleLoader } from '../tenant-admin/tenantBillingRouteModule';
import { createTenantAuditRouteModuleLoader } from '../tenant-admin/tenantAuditRouteModule';
import { createTenantTrustRouteModuleLoader } from '../tenant-admin/tenantTrustRouteModule';
import { createTenantAcpRouteModuleLoader } from '../tenant-admin/tenantAcpRouteModule';
import { createTenantDecisionRecordsRouteModuleLoader } from '../tenant-admin/tenantDecisionRecordsRouteModule';
import { readTenantDecisionRecordsRouteQuery } from '../tenant-admin/tenantDecisionRecordsRouteQuery';
import { createTenantEventsRouteModuleLoader } from '../tenant-admin/tenantEventsRouteModule';
import { createTenantGenesRouteModuleLoader } from '../tenant-admin/tenantGenesRouteModule';
import { createTenantOrganizationSettingsRouteModuleLoader } from '../tenant-admin/tenantOrganizationSettingsRouteModule';
import { createTenantPatternsRouteModuleLoader } from '../tenant-admin/tenantPatternsRouteModule';
import { createTenantSettingsRouteModuleLoader } from '../tenant-admin/tenantSettingsRouteModule';
import { createTenantWebhooksRouteModuleLoader } from '../tenant-admin/tenantWebhooksRouteModule';
import {
  createTenantAuditRouteBindingForRuntime,
  createTenantBillingRouteBindingForRuntime,
  createTenantGovernanceRouteBindingForRuntime,
  createTenantTrustRouteBindingForRuntime,
} from '../tenant-admin/tenantAdminRouteRuntime';
import {
  createTenantAcpRouteBindingForRuntime,
  createTenantDecisionRecordsRouteBindingForRuntime,
  createTenantEventsRouteBindingForRuntime,
  createTenantGenesRouteBindingForRuntime,
  createTenantOrganizationSettingsRouteBindingForRuntime,
  createTenantPatternsRouteBindingForRuntime,
  createTenantSettingsRouteBindingForRuntime,
  createTenantWebhooksRouteBindingForRuntime,
} from '../tenant-admin/tenantRemainingRouteRuntime';
import { createProjectSearchRouteModuleLoader } from '../search/projectSearchRouteModule';
import type { ProjectSearchRouteBindingProviderV2 } from '../search/projectSearchRouteBindingProviderV2';
import { type SettingsSection } from '../settings/SettingsWindow';
import type { DesktopRouteModule, DesktopRouteModuleLoader } from './desktopRouteModule';
import {
  createDesktopRouteRegistry,
  type DesktopRouteDefinition,
} from './desktopRouteRegistry';
import { createAgentDefinitionsRouteModuleLoader } from '../settings-routes/agentDefinitionsRouteModule';
import { createChannelsRouteModuleLoader } from '../settings-routes/channelsRouteModule';
import { createEvolutionRouteModuleLoader } from '../settings-routes/evolutionRouteModule';
import { createMcpServersRouteModuleLoader } from '../settings-routes/mcpServersRouteModule';
import { createPluginsRouteModuleLoader } from '../settings-routes/pluginsRouteModule';
import { createProvidersRouteModuleLoader } from '../settings-routes/providersRouteModule';
import { createProfileRouteModuleLoader } from '../settings-routes/profileRouteModule';
import { PROFILE_ROUTE_ID } from '../settings-routes/profileRoutePresentationModel';
import {
  createChannelsRouteBindingForRuntime,
  createEvolutionRouteBindingForRuntime,
  createProfileRouteBindingForRuntime,
  createTemplatesRouteBindingForRuntime,
} from '../settings-routes/p2ThirdBatchRouteRuntime';
import {
  createAgentDefinitionsRouteBindingForRuntime,
  createMcpServersRouteBindingForRuntime,
  createPluginsRouteBindingForRuntime,
  createProvidersRouteBindingForRuntime,
  createSkillsRouteBindingForRuntime,
} from '../settings-routes/settingsRouteRuntime';
import { createSkillsRouteModuleLoader } from '../settings-routes/skillsRouteModule';
import { createTemplatesRouteModuleLoader } from '../settings-routes/templatesRouteModule';
import type { DesktopPluginMarketplaceCatalogOperationsV2 } from '../../plugins/desktopPluginMarketplaceAuthorityModulesV2';
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
import {
  createDesktopProjectTeamClientV2,
  type DesktopProjectTeamOperationsV2,
} from '../../plugins/desktopProjectTeamAuthorityModuleV2';
import {
  createDesktopProjectSchemaClientV2,
  type DesktopProjectSchemaOperationsV2,
} from '../../plugins/desktopProjectSchemaAuthorityModuleV2';
import {
  createDesktopProjectMaintenanceClientV2,
  type DesktopProjectMaintenanceOperationsV2,
} from '../../plugins/desktopProjectMaintenanceAuthorityModuleV2';
import {
  createDesktopProjectSettingsClientV2,
  type DesktopProjectSettingsOperationsV2,
} from '../../plugins/desktopProjectSettingsAuthorityModuleV2';
import {
  createDesktopProjectSupportClientV2,
  type DesktopProjectSupportOperationsV2,
} from '../../plugins/desktopProjectSupportAuthorityModuleV2';
import {
  createDesktopProjectPlaybooksReadClientV2,
  type DesktopProjectPlaybooksReadOperationsV2,
} from '../../plugins/desktopProjectPlaybooksReadAuthorityModuleV2';
import {
  createDesktopProjectPlaybooksEventSourceV2,
  type DesktopProjectPlaybooksEventsOperationsV2,
} from '../../plugins/desktopProjectPlaybooksEventsAuthorityModuleV2';
import {
  createDesktopBackendStoresClientV2,
  type DesktopBackendStoresOperationsV2,
} from '../../plugins/desktopBackendStoresAuthorityModuleV2';
import {
  createDesktopWorkspaceCollaborationClientV2,
  type DesktopProjectBlackboardOperationsV2,
} from '../../plugins/desktopProjectBlackboardAuthorityModuleV2';
import type { DesktopRuntimePoolOperationsV2 } from '../../plugins/desktopRuntimePoolAuthorityModuleV2';
import type { DesktopRuntimeClustersOperationsV2 } from '../../plugins/desktopRuntimeClustersAuthorityModuleV2';
import type { DesktopRuntimeInstancesOperationsV2 } from '../../plugins/desktopRuntimeInstancesAuthorityModuleV2';
import type { DesktopRuntimeDeploymentsOperationsV2 } from '../../plugins/desktopRuntimeDeploymentsAuthorityModuleV2';
import type { DesktopDeadLetterQueueOperationsV2 } from '../../plugins/desktopDeadLetterQueueAuthorityModuleV2';
import type { DesktopInstanceTemplatesOperationsV2 } from '../../plugins/desktopInstanceTemplatesAuthorityModuleV2';
import type { DesktopTenantEventsOperationsV2 } from '../../plugins/desktopTenantEventsAuthorityModuleV2';
import type { DesktopTenantPatternsOperationsV2 } from '../../plugins/desktopTenantPatternsAuthorityModuleV2';
import type { DesktopUnifiedRuntimesOperationsV2 } from '../../plugins/desktopUnifiedRuntimesAuthorityModuleV2';
import type {
  DesktopProjectSearchClientV2,
} from '../../plugins/desktopProjectSearchAuthorityModuleV2';
import type { DesktopTenantAnalyticsOperationsV2 } from '../../plugins/desktopTenantAnalyticsAuthorityModuleV2';
import type { DesktopTenantAgentBindingsOperationsV2 } from '../../plugins/desktopTenantAgentBindingsAuthorityModuleV2';
import type { DesktopTenantAgentDashboardOperationsV2 } from '../../plugins/desktopTenantAgentDashboardAuthorityModuleV2';
import type { DesktopTenantCatalogOperationsV2 } from '../../plugins/desktopTenantCatalogAuthorityModuleV2';
import {
  createDesktopTenantCreationClientV2,
  type DesktopTenantCreationOperationsV2,
} from '../../plugins/desktopTenantCreationAuthorityModuleV2';
import type { DesktopTenantOverviewOperationsV2 } from '../../plugins/desktopTenantOverviewAuthorityModuleV2';
import type { DesktopTenantProjectsOperationsV2 } from '../../plugins/desktopTenantProjectsAuthorityModuleV2';
import type { DesktopTenantTasksOperationsV2 } from '../../plugins/desktopTenantTasksAuthorityModuleV2';
import type {
  DesktopWorkspaceCatalogOperationsV2,
} from '../../plugins/desktopWorkspaceCatalogAuthorityModuleV2';
import type {
  DesktopWorkspaceLifecycleOperationsV2,
} from '../../plugins/desktopWorkspaceLifecycleAuthorityModuleV2';

export type AppRouteRegistryRefs = {
  authRef: RefObject<AuthState>;
  configRef: RefObject<DesktopRuntimeConfig>;
  pluginMarketplaceOperationsV2: Pick<
    DesktopPluginMarketplaceCatalogOperationsV2,
    'projectMarketplacePlugins'
  >;
  tenantAnalyticsOperationsV2: DesktopTenantAnalyticsOperationsV2;
  tenantAgentBindingsOperationsV2: DesktopTenantAgentBindingsOperationsV2;
  tenantAgentDashboardOperationsV2: DesktopTenantAgentDashboardOperationsV2;
  tenantCatalogOperationsV2: DesktopTenantCatalogOperationsV2;
  tenantCreationOperationsV2: DesktopTenantCreationOperationsV2;
  tenantOverviewOperationsV2: DesktopTenantOverviewOperationsV2;
  tenantProjectsOperationsV2: DesktopTenantProjectsOperationsV2;
  tenantTasksOperationsV2: DesktopTenantTasksOperationsV2;
  desktopWorkspaceCatalogOperationsV2: DesktopWorkspaceCatalogOperationsV2;
  desktopWorkspaceLifecycleOperationsV2: DesktopWorkspaceLifecycleOperationsV2;
  desktopProductionRouteLocation: DesktopHashLocationPort;
  desktopProductionRouteNavigation: Readonly<{
    clearHash: () => void;
    openPath: (path: string) => void;
  }>;
  projectCronJobsRouteBindingProviderV2: ProjectCronJobsRouteBindingProviderV2;
  projectBlackboardOperationsV2: DesktopProjectBlackboardOperationsV2;
  projectOverviewOperationsV2: DesktopProjectOverviewOperationsV2;
  projectAgentDashboardOperationsV2: DesktopProjectAgentDashboardOperationsV2;
  projectAgentLogsOperationsV2: DesktopProjectAgentLogsOperationsV2;
  projectAgentPatternsOperationsV2: DesktopProjectAgentPatternsOperationsV2;
  projectCommunitiesOperationsV2: DesktopProjectCommunitiesOperationsV2;
  projectEntitiesOperationsV2: DesktopProjectEntitiesOperationsV2;
  projectGraphOperationsV2: DesktopProjectGraphOperationsV2;
  projectMemoriesOperationsV2: DesktopProjectMemoriesOperationsV2;
  projectTeamOperationsV2: DesktopProjectTeamOperationsV2;
  projectSchemaOperationsV2: DesktopProjectSchemaOperationsV2;
  projectMaintenanceOperationsV2: DesktopProjectMaintenanceOperationsV2;
  projectSettingsOperationsV2: DesktopProjectSettingsOperationsV2;
  projectSupportOperationsV2: DesktopProjectSupportOperationsV2;
  projectPlaybooksReadOperationsV2: DesktopProjectPlaybooksReadOperationsV2;
  projectPlaybooksEventsOperationsV2: DesktopProjectPlaybooksEventsOperationsV2;
  backendStoresOperationsV2: DesktopBackendStoresOperationsV2;
  runtimePoolOperationsV2: DesktopRuntimePoolOperationsV2;
  runtimeClustersOperationsV2: DesktopRuntimeClustersOperationsV2;
  runtimeInstancesOperationsV2: DesktopRuntimeInstancesOperationsV2;
  runtimeDeploymentsOperationsV2: DesktopRuntimeDeploymentsOperationsV2;
  deadLetterQueueOperationsV2: DesktopDeadLetterQueueOperationsV2;
  instanceTemplatesOperationsV2: DesktopInstanceTemplatesOperationsV2;
  tenantEventsOperationsV2: DesktopTenantEventsOperationsV2;
  tenantPatternsOperationsV2: DesktopTenantPatternsOperationsV2;
  tenantDecisionRecordsOperationsV2: import('../../plugins/desktopTenantDecisionRecordsAuthorityModuleV2').DesktopTenantDecisionRecordsOperationsV2;
  unifiedRuntimesOperationsV2: DesktopUnifiedRuntimesOperationsV2;
  projectSearchOperationsV2: DesktopProjectSearchClientV2;
  projectSearchRouteBindingProviderV2: ProjectSearchRouteBindingProviderV2;
  setAuth: Dispatch<SetStateAction<AuthState>>;
  setInvitationSignInRequested: Dispatch<SetStateAction<boolean>>;
  setSettingsInitialSection: Dispatch<SetStateAction<SettingsSection>>;
  setSettingsWindowOpen: Dispatch<SetStateAction<boolean>>;
  settingsRouteCloseNavigationRef: RefObject<(() => void) | null>;
  commitRuntimeConfig: (nextConfig: DesktopRuntimeConfig) => void;
};

export type AppAuxiliaryRouteRegistryRefs = Pick<
  AppRouteRegistryRefs,
  | 'configRef'
  | 'backendStoresOperationsV2'
  | 'projectPlaybooksReadOperationsV2'
  | 'projectPlaybooksEventsOperationsV2'
  | 'projectSupportOperationsV2'
  | 'setAuth'
>;
export type AppProjectKnowledgeRouteRegistryRefs = Pick<
  AppRouteRegistryRefs,
  | 'configRef'
  | 'projectCommunitiesOperationsV2'
  | 'projectEntitiesOperationsV2'
  | 'projectGraphOperationsV2'
  | 'projectMemoriesOperationsV2'
  | 'projectTeamOperationsV2'
>;
export type AppProjectAgentRouteRegistryRefs = Pick<
  AppRouteRegistryRefs,
  | 'configRef'
  | 'projectAgentDashboardOperationsV2'
  | 'projectAgentLogsOperationsV2'
  | 'projectAgentPatternsOperationsV2'
>;
export type AppProjectAdministrationRouteRegistryRefs = Pick<
  AppRouteRegistryRefs,
  | 'configRef'
  | 'projectCronJobsRouteBindingProviderV2'
  | 'projectMaintenanceOperationsV2'
  | 'projectSettingsOperationsV2'
  | 'projectSchemaOperationsV2'
>;
export type AppRuntimeInfrastructureRouteRegistryRefs = Pick<
  AppRouteRegistryRefs,
  | 'configRef'
  | 'runtimeClustersOperationsV2'
  | 'runtimeInstancesOperationsV2'
  | 'runtimeDeploymentsOperationsV2'
  | 'runtimePoolOperationsV2'
  | 'instanceTemplatesOperationsV2'
  | 'unifiedRuntimesOperationsV2'
>;
export type AppProjectWorkspaceRouteRegistryRefs = Pick<
  AppRouteRegistryRefs,
  | 'configRef'
  | 'desktopProductionRouteNavigation'
  | 'desktopWorkspaceCatalogOperationsV2'
  | 'desktopWorkspaceLifecycleOperationsV2'
  | 'projectBlackboardOperationsV2'
  | 'projectOverviewOperationsV2'
>;
export type AppProjectDiscoveryRouteRegistryRefs = Pick<
  AppRouteRegistryRefs,
  'projectSearchOperationsV2' | 'projectSearchRouteBindingProviderV2'
>;
export type AppTenantCoreRouteRegistryRefs = Pick<
  AppRouteRegistryRefs,
  | 'authRef'
  | 'configRef'
  | 'tenantAnalyticsOperationsV2'
  | 'tenantOverviewOperationsV2'
  | 'tenantProjectsOperationsV2'
  | 'tenantTasksOperationsV2'
  | 'desktopWorkspaceCatalogOperationsV2'
  | 'desktopWorkspaceLifecycleOperationsV2'
>;
type AppSettingsRouteContentRefs = Pick<
  AppRouteRegistryRefs,
  | 'desktopProductionRouteNavigation'
  | 'setSettingsInitialSection'
  | 'setSettingsWindowOpen'
  | 'settingsRouteCloseNavigationRef'
>;
export type AppTenantAgentBuildingRouteRegistryRefs = Pick<
  AppRouteRegistryRefs,
  | 'configRef'
  | 'tenantAgentBindingsOperationsV2'
  | 'tenantAgentDashboardOperationsV2'
  | 'tenantPatternsOperationsV2'
> &
  AppSettingsRouteContentRefs;
export type AppTenantExtensionsIntegrationsRouteRegistryRefs = Pick<
  AppRouteRegistryRefs,
  'configRef' | 'pluginMarketplaceOperationsV2'
> &
  AppSettingsRouteContentRefs;
export type AppTenantGovernanceRouteRegistryRefs = Pick<
  AppRouteRegistryRefs,
  | 'configRef'
  | 'deadLetterQueueOperationsV2'
  | 'tenantEventsOperationsV2'
  | 'tenantDecisionRecordsOperationsV2'
  | 'desktopProductionRouteLocation'
>;

function createSettingsRouteContent(
  section: SettingsSection,
  onOpen: () => void,
  onUnmount: () => void,
) {
  function NativeSettingsRouteContent() {
    useEffect(() => {
      onOpen();
      return onUnmount;
    }, [onOpen, onUnmount]);
    return null;
  }
  NativeSettingsRouteContent.displayName = `NativeSettingsRouteContent:${section}`;
  return NativeSettingsRouteContent;
}

function createSettingsRouteContentFactory(refs: AppSettingsRouteContentRefs) {
  const {
    desktopProductionRouteNavigation,
    setSettingsInitialSection,
    setSettingsWindowOpen,
    settingsRouteCloseNavigationRef,
  } = refs;
  return (section: SettingsSection) =>
    createSettingsRouteContent(
      section,
      () => {
        settingsRouteCloseNavigationRef.current = desktopProductionRouteNavigation.clearHash;
        setSettingsInitialSection(section);
        setSettingsWindowOpen(true);
      },
      () => {
        if (
          settingsRouteCloseNavigationRef.current === desktopProductionRouteNavigation.clearHash
        ) {
          settingsRouteCloseNavigationRef.current = null;
        }
        setSettingsWindowOpen(false);
      },
    );
}

function createDeviceApprovalRouteLoader(refs: AppRouteRegistryRefs): DesktopRouteModuleLoader {
  const { authRef, configRef, desktopProductionRouteLocation, desktopProductionRouteNavigation } =
    refs;
  return createDeviceApprovalRouteModuleLoader({
    createBinding: () => {
      const currentConfig = configRef.current;
      return Object.freeze({
        client: createDeviceApprovalClient(currentConfig),
        accountLabel: authRef.current.user?.email ?? '',
        initialCode: readDeviceApprovalCodeFromHash(desktopProductionRouteLocation.readHash()),
        onNavigateBack: desktopProductionRouteNavigation.clearHash,
      });
    },
  });
}

function createInvitationAcceptanceRouteLoader(
  refs: AppRouteRegistryRefs,
): DesktopRouteModuleLoader {
  const {
    authRef,
    configRef,
    desktopProductionRouteLocation,
    desktopProductionRouteNavigation,
    tenantCatalogOperationsV2,
    setAuth,
    setInvitationSignInRequested,
    commitRuntimeConfig,
  } = refs;
  return createInvitationAcceptanceRouteModuleLoader({
    createBinding: () => {
      return Object.freeze({
        client: Object.freeze<InvitationAcceptanceClient>({
          verify: (token, options) =>
            createInvitationAcceptanceClient(configRef.current).verify(token, options),
          accept: (token, options) =>
            createInvitationAcceptanceClient(configRef.current).accept(token, options),
        }),
        token: readInvitationTokenFromHash(desktopProductionRouteLocation.readHash()),
        authenticated: () => isIdentityAuthenticated(authRef.current),
        accountEmail: () => authRef.current.user?.email ?? '',
        onRequireSignIn: () => setInvitationSignInRequested(true),
        onAccepted: async (invitation, signal) => {
          try {
            const authoritativeTenants = await tenantCatalogOperationsV2.listTenants(
              configRef.current,
              signal,
            );
            if (signal.aborted) return;
            setAuth((current) => ({
              ...current,
              tenants: authoritativeTenants,
            }));
            if (authoritativeTenants.some((tenant) => tenant.id === invitation.tenant_id)) {
              commitRuntimeConfig({
                ...configRef.current,
                tenantId: invitation.tenant_id,
                projectId: '',
                workspaceId: '',
              });
            }
          } catch {
            // Acceptance remains authoritative even if catalog refresh is stale.
          }
        },
        onNavigateHome: desktopProductionRouteNavigation.clearHash,
      });
    },
  });
}

export function createAppAuthenticationRouteRegistry(refs: AppRouteRegistryRefs) {
  return createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [DEVICE_APPROVAL_ROUTE_ID]: createDeviceApprovalRouteLoader(refs),
      [INVITATION_ACCEPTANCE_ROUTE_ID]: createInvitationAcceptanceRouteLoader(refs),
    }),
  });
}

export function createAppAuxiliaryRouteRegistry(refs: AppAuxiliaryRouteRegistryRefs) {
  const { configRef, setAuth } = refs;
  const productionRegistry = createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [BACKEND_STORES_ROUTE_ID]: createBackendStoresRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: 'cloud',
            tenantId: context.tenantId,
          });
          return Object.freeze({
            controller: createBackendStoresController({
              client: createDesktopBackendStoresClientV2(
                refs.backendStoresOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
      [PROJECT_PLAYBOOKS_ROUTE_ID]: createProjectPlaybooksRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: 'cloud',
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectPlaybooksController({
              authority: 'cloud',
              client: createDesktopProjectPlaybooksReadClientV2(
                refs.projectPlaybooksReadOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            events: createDesktopProjectPlaybooksEventSourceV2(
              refs.projectPlaybooksEventsOperationsV2,
              currentConfig,
            ),
            scope,
          });
        },
      }),
      [PROJECT_SUPPORT_ROUTE_ID]: createProjectSupportRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          if (
            currentConfig.tenantId !== context.tenantId ||
            currentConfig.projectId !== context.projectId
          ) {
            throw new Error('project_support_runtime_scope_mismatch');
          }
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectSupportController({
              authority: currentConfig.mode,
              client: createDesktopProjectSupportClientV2(
                refs.projectSupportOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
    }),
  });
  const profileLoader = createProfileRouteModuleLoader({
    createBinding: () =>
      createProfileRouteBindingForRuntime(configRef.current, (user) =>
        setAuth((current) =>
          current.user?.user_id === user.user_id ? { ...current, user } : current,
        ),
      ),
  });
  const profileDefinition = {
    id: PROFILE_ROUTE_ID,
    path: '/tenant/profile',
    scope: ['global'],
    navGroup: 'identity-entry',
    capability: PROFILE_ROUTE_ID,
    requiredPermission: [['authenticated']],
    localPolicy: 'native_equivalent',
    structuralReadiness: { status: 'ready' },
    loader: profileLoader,
  } satisfies DesktopRouteDefinition<DesktopRouteModule>;
  return createDesktopRouteRegistry([
    ...productionRegistry.definitions,
    profileDefinition,
  ]);
}

export function createAppProjectKnowledgeRouteRegistry(refs: AppProjectKnowledgeRouteRegistryRefs) {
  const {
    configRef,
    projectCommunitiesOperationsV2,
    projectEntitiesOperationsV2,
    projectGraphOperationsV2,
    projectMemoriesOperationsV2,
    projectTeamOperationsV2,
  } = refs;
  return createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [PROJECT_TEAM_ROUTE_ID]: createProjectTeamRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectTeamController({
              authority: currentConfig.mode,
              client: createDesktopProjectTeamClientV2(projectTeamOperationsV2, currentConfig),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
      [PROJECT_MEMORIES_ROUTE_ID]: createProjectMemoriesRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectMemoriesController({
              authority: currentConfig.mode,
              client: createDesktopProjectMemoriesClientV2(
                projectMemoriesOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
      [PROJECT_ENTITIES_ROUTE_ID]: createProjectEntitiesRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectEntitiesController({
              authority: currentConfig.mode,
              client: createDesktopProjectEntitiesClientV2(
                projectEntitiesOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
      [PROJECT_COMMUNITIES_ROUTE_ID]: createProjectCommunitiesRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectCommunitiesController({
              authority: currentConfig.mode,
              client: createDesktopProjectCommunitiesClientV2(
                projectCommunitiesOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
      [PROJECT_GRAPH_ROUTE_ID]: createProjectGraphRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectGraphController({
              authority: currentConfig.mode,
              client: createDesktopProjectGraphClientV2(
                projectGraphOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
    }),
  });
}

export function createAppProjectAgentRouteRegistry(refs: AppProjectAgentRouteRegistryRefs) {
  const {
    configRef,
    projectAgentDashboardOperationsV2,
    projectAgentLogsOperationsV2,
    projectAgentPatternsOperationsV2,
  } = refs;
  return createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [PROJECT_AGENT_DASHBOARD_ROUTE_ID]: createProjectAgentDashboardRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectAgentDashboardController({
              authority: currentConfig.mode,
              client: createDesktopProjectAgentDashboardClientV2(
                projectAgentDashboardOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
      [PROJECT_AGENT_LOGS_ROUTE_ID]: createProjectAgentLogsRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectAgentLogsController({
              authority: currentConfig.mode,
              client: createDesktopProjectAgentLogsClientV2(
                projectAgentLogsOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
      [PROJECT_AGENT_PATTERNS_ROUTE_ID]: createProjectAgentPatternsRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectAgentPatternsController({
              authority: currentConfig.mode,
              client: createDesktopProjectAgentPatternsClientV2(
                projectAgentPatternsOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
    }),
  });
}

export function createAppProjectAdministrationRouteRegistry(
  refs: AppProjectAdministrationRouteRegistryRefs,
) {
  const {
    configRef,
    projectCronJobsRouteBindingProviderV2,
    projectMaintenanceOperationsV2,
    projectSettingsOperationsV2,
    projectSchemaOperationsV2,
  } = refs;
  return createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [PROJECT_SCHEMA_ROUTE_ID]: createProjectSchemaRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectSchemaController({
              client: createDesktopProjectSchemaClientV2(
                projectSchemaOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
      [PROJECT_CHANNELS_ROUTE_ID]: createChannelsRouteModuleLoader({
        createBinding: (context) =>
          createChannelsRouteBindingForRuntime(configRef.current, context),
      }),
      [PROJECT_MAINTENANCE_ROUTE_ID]: createProjectMaintenanceRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectMaintenanceController({
              client: createDesktopProjectMaintenanceClientV2(
                projectMaintenanceOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
      [PROJECT_CRON_JOBS_ROUTE_ID]: createProjectCronJobsRouteModuleLoader({
        createBinding: (context) => projectCronJobsRouteBindingProviderV2.resolve(context),
      }),
      [PROJECT_SETTINGS_ROUTE_ID]: createProjectSettingsRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          return Object.freeze({
            controller: createProjectSettingsController({
              client: createDesktopProjectSettingsClientV2(
                projectSettingsOperationsV2,
                currentConfig,
              ),
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
    }),
  });
}

export function createAppRuntimeInfrastructureRouteRegistry(
  refs: AppRuntimeInfrastructureRouteRegistryRefs,
) {
  const {
    configRef,
    runtimeClustersOperationsV2,
    runtimeInstancesOperationsV2,
    runtimeDeploymentsOperationsV2,
    runtimePoolOperationsV2,
    instanceTemplatesOperationsV2,
    unifiedRuntimesOperationsV2,
  } = refs;
  return createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [TENANT_POOL_ROUTE_ID]: createRuntimePoolRouteModuleLoader({
        createBinding: (context) =>
          createRuntimePoolRouteBindingForRuntime(
            configRef.current,
            context,
            runtimePoolOperationsV2,
          ),
      }),
      [TENANT_INSTANCES_ROUTE_ID]: createRuntimeInstancesRouteModuleLoader({
        createBinding: (context) =>
          createRuntimeInstancesRouteBindingForRuntime(
            configRef.current,
            context,
            runtimeInstancesOperationsV2,
          ),
      }),
      [TENANT_CLUSTERS_ROUTE_ID]: createRuntimeClustersRouteModuleLoader({
        createBinding: (context) =>
          createRuntimeClustersRouteBindingForRuntime(
            configRef.current,
            context,
            runtimeClustersOperationsV2,
          ),
      }),
      [TENANT_DEPLOY_ROUTE_ID]: createRuntimeDeploymentsRouteModuleLoader({
        createBinding: (context) =>
          createRuntimeDeploymentsRouteBindingForRuntime(
            configRef.current,
            context,
            runtimeDeploymentsOperationsV2,
          ),
      }),
      [TENANT_INSTANCE_TEMPLATES_ROUTE_ID]: createInstanceTemplatesRouteModuleLoader({
        createBinding: (context) =>
          createInstanceTemplatesRouteBindingForRuntime(
            configRef.current,
            context,
            instanceTemplatesOperationsV2,
          ),
      }),
      [TENANT_RUNTIMES_ROUTE_ID]: createUnifiedRuntimesRouteModuleLoader({
        createBinding: (context) =>
          createUnifiedRuntimesRouteBindingForRuntime(
            configRef.current,
            context,
            unifiedRuntimesOperationsV2,
          ),
      }),
      [TENANT_GENES_ROUTE_ID]: createTenantGenesRouteModuleLoader({
        createBinding: (context) =>
          createTenantGenesRouteBindingForRuntime(configRef.current, context),
      }),
    }),
  });
}

export function createAppProjectWorkspaceRouteRegistry(
  refs: AppProjectWorkspaceRouteRegistryRefs,
) {
  const {
    configRef,
    desktopProductionRouteNavigation,
    desktopWorkspaceCatalogOperationsV2,
    desktopWorkspaceLifecycleOperationsV2,
    projectBlackboardOperationsV2,
    projectOverviewOperationsV2,
  } = refs;
  const projectBlackboardCollaborationClientV2 = createDesktopWorkspaceCollaborationClientV2(
    projectBlackboardOperationsV2,
    () => configRef.current,
    'project-blackboard',
  );
  return createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [PROJECT_OVERVIEW_ROUTE_ID]: createProjectOverviewRouteModuleLoader({
        createBinding: (context) =>
          createProjectOverviewRouteBindingForRuntime(
            configRef.current,
            context,
            projectOverviewOperationsV2,
          ),
      }),
      [PROJECT_WORKSPACES_ROUTE_ID]: createProjectWorkspacesRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
          });
          const client = createProjectWorkspacesV2Client(currentConfig, {
            catalogOperations: desktopWorkspaceCatalogOperationsV2,
            lifecycleOperations: desktopWorkspaceLifecycleOperationsV2,
          });
          return Object.freeze({
            controller: createProjectWorkspacesController({
              authority: currentConfig.mode,
              client,
              initialScope: scope,
            }),
            scope,
            openBlackboard: (workspaceId: string) =>
              desktopProductionRouteNavigation.openPath(
                buildProjectBlackboardCanonicalPath({
                  tenantId: context.tenantId,
                  projectId: context.projectId,
                  workspaceId,
                }),
              ),
          });
        },
      }),
      [PROJECT_BLACKBOARD_ROUTE_ID]: createProjectBlackboardRouteModuleLoader({
        createBinding: (context) => {
          const currentConfig = configRef.current;
          const scope = Object.freeze({
            authority: currentConfig.mode,
            tenantId: context.tenantId,
            projectId: context.projectId,
            workspaceId: context.workspaceId,
          });
          const client = createProjectBlackboardV2Client(
            currentConfig,
            projectBlackboardOperationsV2,
          );
          return Object.freeze({
            controller: createProjectBlackboardController({
              authority: currentConfig.mode,
              client,
              collaborationClient: projectBlackboardCollaborationClientV2,
              initialScope: scope,
            }),
            scope,
          });
        },
      }),
    }),
  });
}

export function createAppProjectDiscoveryRouteRegistry(refs: AppProjectDiscoveryRouteRegistryRefs) {
  const { projectSearchOperationsV2, projectSearchRouteBindingProviderV2 } = refs;
  return createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [PROJECT_SEARCH_ROUTE_ID]: createProjectSearchRouteModuleLoader({
        createBinding: (context) => projectSearchRouteBindingProviderV2.resolve(context),
        projectSearchOperationsV2,
      }),
    }),
  });
}

export function createAppTenantCoreRouteRegistry(refs: AppTenantCoreRouteRegistryRefs) {
  const {
    authRef,
    configRef,
    tenantAnalyticsOperationsV2,
    tenantOverviewOperationsV2,
    tenantProjectsOperationsV2,
    tenantTasksOperationsV2,
    desktopWorkspaceCatalogOperationsV2,
    desktopWorkspaceLifecycleOperationsV2,
  } = refs;
  return createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [AGENT_WORKSPACE_ROUTE_ID]: createAgentWorkspaceRouteModuleLoader(),
      [TENANT_OVERVIEW_ROUTE_ID]: createTenantOverviewRouteModuleLoader({
        createBinding: (context) =>
          createTenantOverviewRouteBindingForRuntime(
            configRef.current,
            context,
            tenantOverviewOperationsV2,
          ),
      }),
      [TENANT_PROJECTS_ROUTE_ID]: createTenantProjectsRouteModuleLoader({
        createBinding: (context) =>
          createTenantProjectsRouteBindingForRuntime(
            configRef.current,
            context,
            tenantProjectsOperationsV2,
          ),
      }),
      [TENANT_WORKSPACES_ROUTE_ID]: createTenantWorkspacesRouteModuleLoader({
        createBinding: (context) =>
          createTenantWorkspacesRouteBindingForRuntime(configRef.current, context, {
            catalogOperations: desktopWorkspaceCatalogOperationsV2,
            lifecycleOperations: desktopWorkspaceLifecycleOperationsV2,
          }),
      }),
      [TENANT_TASKS_ROUTE_ID]: createTenantTasksRouteModuleLoader({
        createBinding: (context) =>
          createTenantTasksRouteBindingForRuntime(
            configRef.current,
            context,
            tenantTasksOperationsV2,
          ),
      }),
      [TENANT_ANALYTICS_ROUTE_ID]: createTenantAnalyticsRouteModuleLoader({
        createBinding: (context) =>
          createTenantAnalyticsRouteBindingForRuntime(
            configRef.current,
            context,
            authRef.current.tenants.find((tenant) => tenant.id === context.tenantId)?.plan ?? null,
            tenantAnalyticsOperationsV2,
          ),
      }),
    }),
  });
}

export function createAppTenantAgentBuildingRouteRegistry(
  refs: AppTenantAgentBuildingRouteRegistryRefs,
) {
  const {
    configRef,
    tenantAgentBindingsOperationsV2,
    tenantAgentDashboardOperationsV2,
  } = refs;
  const settingsRouteContent = createSettingsRouteContentFactory(refs);
  return createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [TENANT_AGENT_DASHBOARD_ROUTE_ID]: createTenantAgentDashboardRouteModuleLoader({
        createBinding: (context) =>
          createTenantAgentDashboardRouteBindingForRuntime(
            configRef.current,
            context,
            tenantAgentDashboardOperationsV2,
          ),
      }),
      [TENANT_AGENT_BINDINGS_ROUTE_ID]: createTenantAgentBindingsRouteModuleLoader({
        createBinding: (context) =>
          createTenantAgentBindingsRouteBindingForRuntime(
            configRef.current,
            context,
            tenantAgentBindingsOperationsV2,
          ),
      }),
      [TENANT_AGENT_DEFINITIONS_ROUTE_ID]: createAgentDefinitionsRouteModuleLoader({
        createBinding: (context) =>
          createAgentDefinitionsRouteBindingForRuntime(
            configRef.current,
            context,
            settingsRouteContent('agents'),
          ),
      }),
      [TENANT_SKILLS_ROUTE_ID]: createSkillsRouteModuleLoader({
        createBinding: (context) =>
          createSkillsRouteBindingForRuntime(
            configRef.current,
            context,
            settingsRouteContent('skills'),
          ),
      }),
      [TENANT_EVOLUTION_ROUTE_ID]: createEvolutionRouteModuleLoader({
        createBinding: (context) =>
          createEvolutionRouteBindingForRuntime(configRef.current, context),
      }),
      [TENANT_PATTERNS_ROUTE_ID]: createTenantPatternsRouteModuleLoader({
        createBinding: (context) =>
          createTenantPatternsRouteBindingForRuntime(
            configRef.current,
            context,
            refs.tenantPatternsOperationsV2,
          ),
      }),
    }),
  });
}

export function createAppTenantExtensionsIntegrationsRouteRegistry(
  refs: AppTenantExtensionsIntegrationsRouteRegistryRefs,
) {
  const { configRef, pluginMarketplaceOperationsV2 } = refs;
  const settingsRouteContent = createSettingsRouteContentFactory(refs);
  return createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [TENANT_ACP_ROUTE_ID]: createTenantAcpRouteModuleLoader({
        createBinding: (context) =>
          createTenantAcpRouteBindingForRuntime(configRef.current, context),
      }),
      [TENANT_WEBHOOKS_ROUTE_ID]: createTenantWebhooksRouteModuleLoader({
        createBinding: (context) =>
          createTenantWebhooksRouteBindingForRuntime(configRef.current, context),
      }),
      [TENANT_PROVIDERS_ROUTE_ID]: createProvidersRouteModuleLoader({
        createBinding: (context) =>
          createProvidersRouteBindingForRuntime(
            configRef.current,
            context,
            settingsRouteContent('models'),
          ),
      }),
      [TENANT_PLUGINS_ROUTE_ID]: createPluginsRouteModuleLoader({
        createBinding: (context) =>
          createPluginsRouteBindingForRuntime(
            configRef.current,
            context,
            settingsRouteContent('plugins'),
            pluginMarketplaceOperationsV2,
          ),
      }),
      [TENANT_MCP_SERVERS_ROUTE_ID]: createMcpServersRouteModuleLoader({
        createBinding: (context) =>
          createMcpServersRouteBindingForRuntime(
            configRef.current,
            context,
            settingsRouteContent('mcp'),
          ),
      }),
      [TENANT_TEMPLATES_ROUTE_ID]: createTemplatesRouteModuleLoader({
        createBinding: (context) =>
          createTemplatesRouteBindingForRuntime(configRef.current, context),
      }),
    }),
  });
}

export function createAppTenantGovernanceRouteRegistry(
  refs: AppTenantGovernanceRouteRegistryRefs,
) {
  const { configRef, desktopProductionRouteLocation, tenantEventsOperationsV2, tenantDecisionRecordsOperationsV2 } = refs;
  return createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [TENANT_USERS_ROUTE_ID]: createTenantGovernanceRouteModuleLoader({
        createBinding: (context) =>
          createTenantGovernanceRouteBindingForRuntime(configRef.current, context),
      }),
      [TENANT_AUDIT_LOGS_ROUTE_ID]: createTenantAuditRouteModuleLoader({
        createBinding: (context) =>
          createTenantAuditRouteBindingForRuntime(configRef.current, context),
      }),
      [TENANT_EVENTS_ROUTE_ID]: createTenantEventsRouteModuleLoader({
        createBinding: (context) =>
          createTenantEventsRouteBindingForRuntime(
            configRef.current,
            context,
            tenantEventsOperationsV2,
          ),
      }),
      [TENANT_DEAD_LETTER_QUEUE_ROUTE_ID]: createDeadLetterQueueRouteModuleLoader({
        createBinding: (context) =>
          createDeadLetterQueueRouteBindingForRuntime(
            configRef.current,
            context,
            refs.deadLetterQueueOperationsV2,
          ),
      }),
      [TENANT_TRUST_POLICIES_ROUTE_ID]: createTenantTrustRouteModuleLoader({
        createBinding: (context) =>
          createTenantTrustRouteBindingForRuntime(configRef.current, context),
      }),
      [TENANT_DECISION_RECORDS_ROUTE_ID]: createTenantDecisionRecordsRouteModuleLoader({
        createBinding: (context) => {
          const query = readTenantDecisionRecordsRouteQuery(
            desktopProductionRouteLocation.readHash(),
          );
          return createTenantDecisionRecordsRouteBindingForRuntime(
            {
              ...configRef.current,
              workspaceId: query.status === 'ready' ? query.workspaceId : '',
            },
            context,
            tenantDecisionRecordsOperationsV2,
          );
        },
      }),
      [TENANT_BILLING_ROUTE_ID]: createTenantBillingRouteModuleLoader({
        createBinding: (context) =>
          createTenantBillingRouteBindingForRuntime(configRef.current, context),
      }),
      [TENANT_ORGANIZATION_SETTINGS_ROUTE_ID]: createTenantOrganizationSettingsRouteModuleLoader({
        createBinding: (context) =>
          createTenantOrganizationSettingsRouteBindingForRuntime(configRef.current, context),
      }),
      [TENANT_SETTINGS_ROUTE_ID]: createTenantSettingsRouteModuleLoader({
        createBinding: (context) =>
          createTenantSettingsRouteBindingForRuntime(configRef.current, context),
      }),
    }),
  });
}

export function createAppTenantCreationRouteRegistry(refs: AppRouteRegistryRefs) {
  const {
    configRef,
    desktopProductionRouteNavigation,
    tenantCatalogOperationsV2,
    tenantCreationOperationsV2,
    setAuth,
  } = refs;
  return createDesktopProductionRouteRegistry({
    implementedLoaders: registerDesktopProductionRouteLoaders({
      [TENANT_CREATION_ROUTE_ID]: createTenantCreationRouteModuleLoader({
        createBinding: () => {
          const currentConfig = configRef.current;
          return Object.freeze({
            client: createDesktopTenantCreationClientV2(
              tenantCreationOperationsV2,
              currentConfig,
            ),
            onCreated: async (created, signal) => {
              setAuth((current) => ({
                ...current,
                tenants: [...upsertCreatedTenant(current.tenants, created)],
              }));
              try {
                const authoritativeTenants = await tenantCatalogOperationsV2.listTenants(
                  currentConfig,
                  signal,
                );
                if (signal.aborted) {
                  return Object.freeze({
                    catalogRefreshed: false,
                  });
                }
                setAuth((current) => ({
                  ...current,
                  tenants: authoritativeTenants,
                }));
                return Object.freeze({
                  catalogRefreshed: true,
                });
              } catch {
                return Object.freeze({
                  catalogRefreshed: false,
                });
              }
            },
            onNavigateBack: desktopProductionRouteNavigation.clearHash,
          });
        },
      }),
    }),
  });
}
