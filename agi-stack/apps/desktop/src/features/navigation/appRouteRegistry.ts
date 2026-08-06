import {
  type Dispatch,
  type RefObject,
  type SetStateAction,
  useEffect,
} from 'react';

import type { DesktopHashLocationPort } from './desktopHashRouteHost';
import type {
  AuthState,
  DesktopRuntimeConfig,
  ProjectSummary,
} from '../../types';
import {
  DesktopApiClient,
} from '../../api/client';
import {
  AGENT_WORKSPACE_ROUTE_ID,
  createAgentWorkspaceRouteModuleLoader,
} from '../agent-workspace/agentWorkspaceRouteModule';
import {
  isIdentityAuthenticated,
} from '../auth/authContextModel';
import {
  createDeviceApprovalClient,
} from '../device-approval/deviceApprovalClient';
import {
  readDeviceApprovalCodeFromHash,
} from '../device-approval/deviceApprovalModel';
import {
  createDeviceApprovalRouteModuleLoader,
} from '../device-approval/deviceApprovalRouteModule';
import {
  createTenantCreationClient,
} from '../tenant-creation/tenantCreationClient';
import {
  upsertCreatedTenant,
} from '../tenant-creation/tenantCreationModel';
import {
  createTenantCreationRouteModuleLoader,
} from '../tenant-creation/tenantCreationRouteModule';
import {
  createInvitationAcceptanceClient,
  type InvitationAcceptanceClient,
} from '../invitation-acceptance/invitationAcceptanceClient';
import {
  readInvitationTokenFromHash,
} from '../invitation-acceptance/invitationAcceptanceModel';
import {
  createInvitationAcceptanceRouteModuleLoader,
} from '../invitation-acceptance/invitationAcceptanceRouteModule';
import {
  createDesktopAutomationApi,
  type DesktopAutomationApi,
} from '../automations/automationClient';
import {
  createProjectCronJobsRouteModuleLoader,
  type ProjectCronJobsRouteBinding,
} from '../automations/projectCronJobsRouteModule';
import {
  desktopCapability,
  type DesktopCapabilityView,
} from '../runtime/capabilitySnapshot';
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
import {
  createProjectOverviewRouteModuleLoader,
} from '../project/projectOverviewRouteModule';
import {
  createProjectAgentDashboardClient,
} from '../project-agent/projectAgentDashboardClient';
import {
  createProjectAgentDashboardController,
} from '../project-agent/projectAgentDashboardController';
import {
  createProjectAgentDashboardRouteModuleLoader,
} from '../project-agent/projectAgentDashboardRouteModule';
import {
  createProjectAgentLogsClient,
} from '../project-agent/projectAgentLogsClient';
import {
  createProjectAgentLogsController,
} from '../project-agent/projectAgentLogsController';
import {
  createProjectAgentLogsRouteModuleLoader,
} from '../project-agent/projectAgentLogsRouteModule';
import {
  createProjectAgentPatternsClient,
} from '../project-agent/projectAgentPatternsClient';
import {
  createProjectAgentPatternsController,
} from '../project-agent/projectAgentPatternsController';
import {
  createProjectAgentPatternsRouteModuleLoader,
} from '../project-agent/projectAgentPatternsRouteModule';
import {
  createProjectMaintenanceClient,
} from '../project-administration/projectMaintenanceClient';
import {
  createProjectMaintenanceController,
} from '../project-administration/projectMaintenanceController';
import {
  createProjectMaintenanceRouteModuleLoader,
} from '../project-administration/projectMaintenanceRouteModule';
import {
  createProjectSchemaClient,
} from '../project-administration/projectSchemaClient';
import {
  createProjectSchemaController,
} from '../project-administration/projectSchemaController';
import {
  createProjectSchemaRouteModuleLoader,
} from '../project-administration/projectSchemaRouteModule';
import {
  createProjectSettingsClient,
} from '../project-administration/projectSettingsClient';
import {
  createProjectSettingsController,
} from '../project-administration/projectSettingsController';
import {
  createProjectSettingsRouteModuleLoader,
} from '../project-administration/projectSettingsRouteModule';
import {
  buildProjectBlackboardCanonicalPath,
  createProjectBlackboardRouteModuleLoader,
} from '../project-blackboard/projectBlackboardRouteModule';
import {
  createProjectBlackboardCloudClient,
  createProjectBlackboardLocalClient,
} from '../project-blackboard/projectBlackboardClient';
import {
  createProjectBlackboardController,
} from '../project-blackboard/projectBlackboardController';
import {
  createProjectCommunitiesClient,
} from '../project-knowledge/projectCommunitiesClient';
import {
  createProjectCommunitiesController,
} from '../project-knowledge/projectCommunitiesController';
import {
  createProjectCommunitiesRouteModuleLoader,
} from '../project-knowledge/projectCommunitiesRouteModule';
import {
  createProjectEntitiesClient,
} from '../project-knowledge/projectEntitiesClient';
import {
  createProjectEntitiesController,
} from '../project-knowledge/projectEntitiesController';
import {
  createProjectEntitiesRouteModuleLoader,
} from '../project-knowledge/projectEntitiesRouteModule';
import {
  createProjectGraphClient,
} from '../project-knowledge/projectGraphClient';
import {
  createProjectGraphController,
} from '../project-knowledge/projectGraphController';
import {
  createProjectGraphRouteModuleLoader,
} from '../project-knowledge/projectGraphRouteModule';
import {
  createProjectMemoriesClient,
} from '../project-knowledge/projectMemoriesClient';
import {
  createProjectMemoriesController,
} from '../project-knowledge/projectMemoriesController';
import {
  createProjectMemoriesRouteModuleLoader,
} from '../project-knowledge/projectMemoriesRouteModule';
import {
  createProjectTeamClient,
} from '../project-knowledge/projectTeamClient';
import {
  createProjectTeamController,
} from '../project-knowledge/projectTeamController';
import {
  createProjectTeamRouteModuleLoader,
} from '../project-knowledge/projectTeamRouteModule';
import {
  createProjectWorkspacesController,
} from '../project-workspaces/projectWorkspacesController';
import {
  createProjectWorkspacesHttpClient,
} from '../project-workspaces/projectWorkspacesHttpClient';
import {
  createProjectWorkspacesRouteModuleLoader,
} from '../project-workspaces/projectWorkspacesRouteModule';
import {
  createProjectSupportRouteModuleLoader,
} from '../project-support/projectSupportRouteModule';
import {
  createProjectSupportRouteBindingForRuntime,
} from '../project-support/projectSupportRuntime';
import {
  createDeadLetterQueueRouteModuleLoader,
} from '../governance/deadLetterQueueRouteModule';
import {
  createInstanceTemplatesRouteModuleLoader,
} from '../instance-templates/instanceTemplatesRouteModule';
import {
  createRuntimeClustersRouteModuleLoader,
} from '../runtime-clusters/runtimeClustersRouteModule';
import {
  createRuntimeDeploymentsRouteModuleLoader,
} from '../runtime-deployments/runtimeDeploymentsRouteModule';
import {
  createRuntimeInstancesRouteModuleLoader,
} from '../runtime-instances/runtimeInstancesRouteModule';
import {
  createRuntimePoolRouteModuleLoader,
} from '../runtime-pool/runtimePoolRouteModule';
import {
  createUnifiedRuntimesRouteModuleLoader,
} from '../unified-runtimes/unifiedRuntimesRouteModule';
import {
  createTenantOverviewRouteModuleLoader,
} from '../tenant/tenantOverviewRouteModule';
import {
  createTenantAnalyticsRouteModuleLoader,
} from '../tenant/tenantAnalyticsRouteModule';
import {
  createTenantAgentDashboardRouteModuleLoader,
} from '../tenant/tenantAgentDashboardRouteModule';
import {
  createTenantAgentBindingsRouteModuleLoader,
} from '../tenant/tenantAgentBindingsRouteModule';
import {
  createTenantProjectsRouteModuleLoader,
} from '../tenant/tenantProjectsRouteModule';
import {
  createTenantTasksRouteModuleLoader,
} from '../tenant/tenantTasksRouteModule';
import {
  createTenantWorkspacesRouteModuleLoader,
} from '../tenant/tenantWorkspacesRouteModule';
import {
  createTenantGovernanceRouteModuleLoader,
} from '../tenant-admin/tenantGovernanceRouteModule';
import {
  createTenantBillingRouteModuleLoader,
} from '../tenant-admin/tenantBillingRouteModule';
import {
  createTenantAuditRouteModuleLoader,
} from '../tenant-admin/tenantAuditRouteModule';
import {
  createTenantTrustRouteModuleLoader,
} from '../tenant-admin/tenantTrustRouteModule';
import {
  createTenantAcpRouteModuleLoader,
} from '../tenant-admin/tenantAcpRouteModule';
import {
  createTenantDecisionRecordsRouteModuleLoader,
} from '../tenant-admin/tenantDecisionRecordsRouteModule';
import {
  readTenantDecisionRecordsRouteQuery,
} from '../tenant-admin/tenantDecisionRecordsRouteQuery';
import {
  createTenantEventsRouteModuleLoader,
} from '../tenant-admin/tenantEventsRouteModule';
import {
  createTenantGenesRouteModuleLoader,
} from '../tenant-admin/tenantGenesRouteModule';
import {
  createTenantOrganizationSettingsRouteModuleLoader,
} from '../tenant-admin/tenantOrganizationSettingsRouteModule';
import {
  createTenantPatternsRouteModuleLoader,
} from '../tenant-admin/tenantPatternsRouteModule';
import {
  createTenantSettingsRouteModuleLoader,
} from '../tenant-admin/tenantSettingsRouteModule';
import {
  createTenantWebhooksRouteModuleLoader,
} from '../tenant-admin/tenantWebhooksRouteModule';
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
import {
  createProjectSearchRouteModuleLoader,
  type ProjectSearchRouteBinding,
} from '../search/projectSearchRouteModule';
import {
  type SettingsSection,
} from '../settings/SettingsWindow';
import {
  createAgentDefinitionsRouteModuleLoader,
} from '../settings-routes/agentDefinitionsRouteModule';
import {
  createChannelsRouteModuleLoader,
} from '../settings-routes/channelsRouteModule';
import {
  createEvolutionRouteModuleLoader,
} from '../settings-routes/evolutionRouteModule';
import {
  createMcpServersRouteModuleLoader,
} from '../settings-routes/mcpServersRouteModule';
import {
  createPluginsRouteModuleLoader,
} from '../settings-routes/pluginsRouteModule';
import {
  createProvidersRouteModuleLoader,
} from '../settings-routes/providersRouteModule';
import {
  createChannelsRouteBindingForRuntime,
  createEvolutionRouteBindingForRuntime,
  createTemplatesRouteBindingForRuntime,
} from '../settings-routes/p2ThirdBatchRouteRuntime';
import {
  createAgentDefinitionsRouteBindingForRuntime,
  createMcpServersRouteBindingForRuntime,
  createPluginsRouteBindingForRuntime,
  createProvidersRouteBindingForRuntime,
  createSkillsRouteBindingForRuntime,
} from '../settings-routes/settingsRouteRuntime';
import {
  createSkillsRouteModuleLoader,
} from '../settings-routes/skillsRouteModule';
import {
  createTemplatesRouteModuleLoader,
} from '../settings-routes/templatesRouteModule';

export type AppRouteRegistryRefs = {
  api: DesktopApiClient;
  authRef: RefObject<AuthState>;
  configRef: RefObject<DesktopRuntimeConfig>;
  desktopProductionRouteLocation: DesktopHashLocationPort;
  desktopProductionRouteNavigation: Readonly<{
    clearHash: () => void;
    openPath: (path: string) => void;
  }>;
  projectCronJobsRouteBindingRef: RefObject<Readonly<{
    api: DesktopAutomationApi;
    config: DesktopRuntimeConfig;
    project: ProjectSummary | null;
    runCapability: DesktopCapabilityView;
    onOpenProjectSettings: () => void;
    onOpenConnection: () => void;
  }> | null>;
  projectSearchRouteBindingRef: RefObject<Readonly<{
    api: DesktopApiClient;
    config: DesktopRuntimeConfig;
    project: ProjectSummary | null;
    capability: DesktopCapabilityView;
    capabilityLoading: boolean;
    onRetryCapability: () => void;
  }> | null>;
  setAuth: Dispatch<SetStateAction<AuthState>>;
  setInvitationSignInRequested: Dispatch<SetStateAction<boolean>>;
  setSettingsInitialSection: Dispatch<SetStateAction<SettingsSection>>;
  setSettingsWindowOpen: Dispatch<SetStateAction<boolean>>;
  settingsRouteCloseNavigationRef: RefObject<(() => void) | null>;
  commitRuntimeConfig: (nextConfig: DesktopRuntimeConfig) => void;
};

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

export function createAppRouteRegistry(refs: AppRouteRegistryRefs) {
  const {
    api,
    authRef,
    configRef,
    desktopProductionRouteLocation,
    desktopProductionRouteNavigation,
    projectCronJobsRouteBindingRef,
    projectSearchRouteBindingRef,
    setAuth,
    setInvitationSignInRequested,
    setSettingsInitialSection,
    setSettingsWindowOpen,
    settingsRouteCloseNavigationRef,
    commitRuntimeConfig,
  } = refs;
      const settingsRouteContent = (section: SettingsSection) =>
        createSettingsRouteContent(
          section,
          () => {
            settingsRouteCloseNavigationRef.current =
              desktopProductionRouteNavigation.clearHash;
            setSettingsInitialSection(section);
            setSettingsWindowOpen(true);
          },
          () => {
            if (
              settingsRouteCloseNavigationRef.current ===
              desktopProductionRouteNavigation.clearHash
            ) {
              settingsRouteCloseNavigationRef.current = null;
            }
            setSettingsWindowOpen(false);
          },
        );
      return createDesktopProductionRouteRegistry({
        implementedLoaders: registerDesktopProductionRouteLoaders({
          [AGENT_WORKSPACE_ROUTE_ID]: createAgentWorkspaceRouteModuleLoader(),
          [DEVICE_APPROVAL_ROUTE_ID]: createDeviceApprovalRouteModuleLoader({
            createBinding: () => {
              const currentConfig = configRef.current;
              return Object.freeze({
                client: createDeviceApprovalClient(currentConfig),
                accountLabel: authRef.current.user?.email ?? '',
                initialCode: readDeviceApprovalCodeFromHash(
                  desktopProductionRouteLocation.readHash(),
                ),
                onNavigateBack: desktopProductionRouteNavigation.clearHash,
              });
            },
          }),
          [TENANT_CREATION_ROUTE_ID]: createTenantCreationRouteModuleLoader({
            createBinding: () => {
              const currentConfig = configRef.current;
              return Object.freeze({
                client: createTenantCreationClient(currentConfig),
                onCreated: async (created, signal) => {
                  setAuth((current) => ({
                    ...current,
                    tenants: [...upsertCreatedTenant(current.tenants, created)],
                  }));
                  try {
                    const authoritativeTenants = await new DesktopApiClient(
                      currentConfig,
                    ).listTenants(signal);
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
          [INVITATION_ACCEPTANCE_ROUTE_ID]:
            createInvitationAcceptanceRouteModuleLoader({
              createBinding: () => {
                return Object.freeze({
                  client: Object.freeze<InvitationAcceptanceClient>({
                    verify: (token, options) =>
                      createInvitationAcceptanceClient(
                        configRef.current,
                      ).verify(token, options),
                    accept: (token, options) =>
                      createInvitationAcceptanceClient(
                        configRef.current,
                      ).accept(token, options),
                  }),
                  token: readInvitationTokenFromHash(
                    desktopProductionRouteLocation.readHash(),
                  ),
                  authenticated: () => isIdentityAuthenticated(authRef.current),
                  accountEmail: () => authRef.current.user?.email ?? '',
                  onRequireSignIn: () => setInvitationSignInRequested(true),
                  onAccepted: async (invitation, signal) => {
                    try {
                      const authoritativeTenants = await new DesktopApiClient(
                        configRef.current,
                      ).listTenants(signal);
                      if (signal.aborted) return;
                      setAuth((current) => ({
                        ...current,
                        tenants: authoritativeTenants,
                      }));
                      if (
                        authoritativeTenants.some(
                          (tenant) => tenant.id === invitation.tenant_id,
                        )
                      ) {
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
            }),
          [TENANT_OVERVIEW_ROUTE_ID]: createTenantOverviewRouteModuleLoader({
            createBinding: (context) =>
              createTenantOverviewRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_ANALYTICS_ROUTE_ID]: createTenantAnalyticsRouteModuleLoader({
            createBinding: (context) =>
              createTenantAnalyticsRouteBindingForRuntime(
                configRef.current,
                context,
                authRef.current.tenants.find(
                  (tenant) => tenant.id === context.tenantId,
                )?.plan ?? null,
              ),
          }),
          [TENANT_AGENT_DASHBOARD_ROUTE_ID]:
            createTenantAgentDashboardRouteModuleLoader({
              createBinding: (context) =>
                createTenantAgentDashboardRouteBindingForRuntime(
                  configRef.current,
                  context,
                ),
            }),
          [TENANT_AGENT_BINDINGS_ROUTE_ID]:
            createTenantAgentBindingsRouteModuleLoader({
              createBinding: (context) =>
                createTenantAgentBindingsRouteBindingForRuntime(
                  configRef.current,
                  context,
                ),
            }),
          [TENANT_PATTERNS_ROUTE_ID]: createTenantPatternsRouteModuleLoader({
            createBinding: (context) =>
              createTenantPatternsRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_ACP_ROUTE_ID]: createTenantAcpRouteModuleLoader({
            createBinding: (context) =>
              createTenantAcpRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_WEBHOOKS_ROUTE_ID]: createTenantWebhooksRouteModuleLoader({
            createBinding: (context) =>
              createTenantWebhooksRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_GENES_ROUTE_ID]: createTenantGenesRouteModuleLoader({
            createBinding: (context) =>
              createTenantGenesRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_EVENTS_ROUTE_ID]: createTenantEventsRouteModuleLoader({
            createBinding: (context) =>
              createTenantEventsRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_DECISION_RECORDS_ROUTE_ID]:
            createTenantDecisionRecordsRouteModuleLoader({
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
                );
              },
            }),
          [TENANT_ORGANIZATION_SETTINGS_ROUTE_ID]:
            createTenantOrganizationSettingsRouteModuleLoader({
              createBinding: (context) =>
                createTenantOrganizationSettingsRouteBindingForRuntime(
                  configRef.current,
                  context,
                ),
            }),
          [TENANT_SETTINGS_ROUTE_ID]: createTenantSettingsRouteModuleLoader({
            createBinding: (context) =>
              createTenantSettingsRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_PROVIDERS_ROUTE_ID]: createProvidersRouteModuleLoader({
            createBinding: (context) =>
              createProvidersRouteBindingForRuntime(
                configRef.current,
                context,
                settingsRouteContent('models'),
              ),
          }),
          [TENANT_AGENT_DEFINITIONS_ROUTE_ID]:
            createAgentDefinitionsRouteModuleLoader({
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
              createEvolutionRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_PLUGINS_ROUTE_ID]: createPluginsRouteModuleLoader({
            createBinding: (context) =>
              createPluginsRouteBindingForRuntime(
                configRef.current,
                context,
                settingsRouteContent('plugins'),
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
              createTemplatesRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_PROJECTS_ROUTE_ID]: createTenantProjectsRouteModuleLoader({
            createBinding: (context) =>
              createTenantProjectsRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_WORKSPACES_ROUTE_ID]: createTenantWorkspacesRouteModuleLoader(
            {
              createBinding: (context) =>
                createTenantWorkspacesRouteBindingForRuntime(
                  configRef.current,
                  context,
                ),
            },
          ),
          [TENANT_TASKS_ROUTE_ID]: createTenantTasksRouteModuleLoader({
            createBinding: (context) =>
              createTenantTasksRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_DEAD_LETTER_QUEUE_ROUTE_ID]:
            createDeadLetterQueueRouteModuleLoader({
              createBinding: (context) =>
                createDeadLetterQueueRouteBindingForRuntime(
                  configRef.current,
                  context,
                ),
            }),
          [TENANT_USERS_ROUTE_ID]: createTenantGovernanceRouteModuleLoader({
            createBinding: (context) =>
              createTenantGovernanceRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_BILLING_ROUTE_ID]: createTenantBillingRouteModuleLoader({
            createBinding: (context) =>
              createTenantBillingRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_AUDIT_LOGS_ROUTE_ID]: createTenantAuditRouteModuleLoader({
            createBinding: (context) =>
              createTenantAuditRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_TRUST_POLICIES_ROUTE_ID]:
            createTenantTrustRouteModuleLoader({
              createBinding: (context) =>
                createTenantTrustRouteBindingForRuntime(
                  configRef.current,
                  context,
                ),
            }),
          [PROJECT_OVERVIEW_ROUTE_ID]: createProjectOverviewRouteModuleLoader({
            createBinding: (context) =>
              createProjectOverviewRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [PROJECT_WORKSPACES_ROUTE_ID]:
            createProjectWorkspacesRouteModuleLoader({
              createBinding: (context) => {
                const currentConfig = configRef.current;
                const scope = Object.freeze({
                  authority: currentConfig.mode,
                  tenantId: context.tenantId,
                  projectId: context.projectId,
                });
                const client = createProjectWorkspacesHttpClient(currentConfig);
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
          [PROJECT_BLACKBOARD_ROUTE_ID]:
            createProjectBlackboardRouteModuleLoader({
              createBinding: (context) => {
                const currentConfig = configRef.current;
                const scope = Object.freeze({
                  authority: currentConfig.mode,
                  tenantId: context.tenantId,
                  projectId: context.projectId,
                  workspaceId: context.workspaceId,
                });
                const client =
                  currentConfig.mode === 'local'
                    ? createProjectBlackboardLocalClient(currentConfig)
                    : createProjectBlackboardCloudClient(currentConfig);
                return Object.freeze({
                  controller: createProjectBlackboardController({
                    authority: currentConfig.mode,
                    client,
                    initialScope: scope,
                  }),
                  scope,
                });
              },
            }),
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
                  client: createProjectTeamClient(currentConfig),
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
                  client: createProjectMemoriesClient(currentConfig),
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
                  client: createProjectEntitiesClient(currentConfig),
                  initialScope: scope,
                }),
                scope,
              });
            },
          }),
          [PROJECT_COMMUNITIES_ROUTE_ID]:
            createProjectCommunitiesRouteModuleLoader({
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
                    client: createProjectCommunitiesClient(currentConfig),
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
                  client: createProjectGraphClient(currentConfig),
                  initialScope: scope,
                }),
                scope,
              });
            },
          }),
          [PROJECT_AGENT_DASHBOARD_ROUTE_ID]:
            createProjectAgentDashboardRouteModuleLoader({
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
                    client: createProjectAgentDashboardClient(currentConfig),
                    initialScope: scope,
                  }),
                  scope,
                });
              },
            }),
          [PROJECT_AGENT_LOGS_ROUTE_ID]:
            createProjectAgentLogsRouteModuleLoader({
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
                    client: createProjectAgentLogsClient(currentConfig),
                    initialScope: scope,
                  }),
                  scope,
                });
              },
            }),
          [PROJECT_AGENT_PATTERNS_ROUTE_ID]:
            createProjectAgentPatternsRouteModuleLoader({
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
                    client: createProjectAgentPatternsClient(currentConfig),
                    initialScope: scope,
                  }),
                  scope,
                });
              },
            }),
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
                  client: createProjectSchemaClient(currentConfig),
                  initialScope: scope,
                }),
                scope,
              });
            },
          }),
          [PROJECT_MAINTENANCE_ROUTE_ID]:
            createProjectMaintenanceRouteModuleLoader({
              createBinding: (context) => {
                const currentConfig = configRef.current;
                const scope = Object.freeze({
                  authority: currentConfig.mode,
                  tenantId: context.tenantId,
                  projectId: context.projectId,
                });
                return Object.freeze({
                  controller: createProjectMaintenanceController({
                    client: createProjectMaintenanceClient(currentConfig),
                    initialScope: scope,
                  }),
                  scope,
                });
              },
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
                  client: createProjectSettingsClient(currentConfig),
                  initialScope: scope,
                }),
                scope,
              });
            },
          }),
          [PROJECT_CHANNELS_ROUTE_ID]: createChannelsRouteModuleLoader({
            createBinding: (context) =>
              createChannelsRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [PROJECT_SUPPORT_ROUTE_ID]: createProjectSupportRouteModuleLoader({
            createBinding: (context) =>
              createProjectSupportRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_POOL_ROUTE_ID]: createRuntimePoolRouteModuleLoader({
            createBinding: (context) =>
              createRuntimePoolRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_INSTANCES_ROUTE_ID]: createRuntimeInstancesRouteModuleLoader({
            createBinding: (context) =>
              createRuntimeInstancesRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_CLUSTERS_ROUTE_ID]: createRuntimeClustersRouteModuleLoader({
            createBinding: (context) =>
              createRuntimeClustersRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_DEPLOY_ROUTE_ID]: createRuntimeDeploymentsRouteModuleLoader({
            createBinding: (context) =>
              createRuntimeDeploymentsRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [TENANT_INSTANCE_TEMPLATES_ROUTE_ID]:
            createInstanceTemplatesRouteModuleLoader({
              createBinding: (context) =>
                createInstanceTemplatesRouteBindingForRuntime(
                  configRef.current,
                  context,
                ),
            }),
          [TENANT_RUNTIMES_ROUTE_ID]: createUnifiedRuntimesRouteModuleLoader({
            createBinding: (context) =>
              createUnifiedRuntimesRouteBindingForRuntime(
                configRef.current,
                context,
              ),
          }),
          [PROJECT_SEARCH_ROUTE_ID]: createProjectSearchRouteModuleLoader({
            createBinding: (_context): ProjectSearchRouteBinding => {
              const current = projectSearchRouteBindingRef.current;
              const currentConfig = current?.config ?? configRef.current;
              return Object.freeze({
                api: current?.api ?? new DesktopApiClient(currentConfig),
                scope: Object.freeze({
                  tenantId: currentConfig.tenantId,
                  projectId: currentConfig.projectId,
                }),
                projectName:
                  current?.project?.name ?? current?.project?.id ?? null,
                capability:
                  current?.capability ??
                  desktopCapability(null, PROJECT_SEARCH_ROUTE_ID),
                capabilityLoading: current?.capabilityLoading ?? true,
                onRetryCapability: current?.onRetryCapability,
              });
            },
          }),
          [PROJECT_CRON_JOBS_ROUTE_ID]: createProjectCronJobsRouteModuleLoader({
            createBinding: (_context): ProjectCronJobsRouteBinding => {
              const current = projectCronJobsRouteBindingRef.current;
              const currentConfig = current?.config ?? configRef.current;
              return Object.freeze({
                api:
                  current?.api ??
                  createDesktopAutomationApi(
                    new DesktopApiClient(currentConfig),
                    currentConfig,
                  ),
                scope: Object.freeze({
                  tenantId: currentConfig.tenantId,
                  projectId: currentConfig.projectId,
                }),
                projectName:
                  current?.project?.name ?? current?.project?.id ?? null,
                runCapability:
                  current?.runCapability ??
                  desktopCapability(null, 'automation_run'),
                onOpenProjectSettings:
                  current?.onOpenProjectSettings ?? (() => undefined),
                onOpenConnection:
                  current?.onOpenConnection ?? (() => undefined),
              });
            },
          }),
        }),
      });
}
