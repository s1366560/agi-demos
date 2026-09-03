import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopPluginMarketplaceCatalogOperationsV2 } from '../../plugins/desktopPluginMarketplaceAuthorityModulesV2';
import type { DesktopProjectBlackboardOperationsV2 } from '../../plugins/desktopProjectBlackboardAuthorityModuleV2';
import type { DesktopProjectOverviewOperationsV2 } from '../../plugins/desktopProjectOverviewAuthorityModuleV2';
import type { DesktopProjectAgentDashboardOperationsV2 } from '../../plugins/desktopProjectAgentDashboardAuthorityModuleV2';
import type { DesktopProjectAgentLogsOperationsV2 } from '../../plugins/desktopProjectAgentLogsAuthorityModuleV2';
import type { DesktopProjectAgentPatternsOperationsV2 } from '../../plugins/desktopProjectAgentPatternsAuthorityModuleV2';
import type { DesktopRuntimePoolOperationsV2 } from '../../plugins/desktopRuntimePoolAuthorityModuleV2';
import type { DesktopTenantAnalyticsOperationsV2 } from '../../plugins/desktopTenantAnalyticsAuthorityModuleV2';
import type { DesktopTenantAgentBindingsOperationsV2 } from '../../plugins/desktopTenantAgentBindingsAuthorityModuleV2';
import type { DesktopTenantAgentDashboardOperationsV2 } from '../../plugins/desktopTenantAgentDashboardAuthorityModuleV2';
import type { DesktopTenantOverviewOperationsV2 } from '../../plugins/desktopTenantOverviewAuthorityModuleV2';
import type { DesktopTenantProjectsOperationsV2 } from '../../plugins/desktopTenantProjectsAuthorityModuleV2';
import type { DesktopTenantTasksOperationsV2 } from '../../plugins/desktopTenantTasksAuthorityModuleV2';
import type {
  DesktopWorkspaceCatalogOperationsV2,
} from '../../plugins/desktopWorkspaceCatalogAuthorityModuleV2';
import type {
  DesktopWorkspaceLifecycleOperationsV2,
} from '../../plugins/desktopWorkspaceLifecycleAuthorityModuleV2';
import { createProjectWorkspacesV2Client } from '../project-workspaces/projectWorkspacesV2Client';
import {
  createDesktopWorkbenchCapabilityClient,
  type DesktopWorkbenchCapabilityClient,
} from './workbenchCapabilityClient';

export type DesktopWorkbenchCapabilityClientProviderReasonCodeV2 =
  'desktop_workbench_capability_client_unpublished';

export class DesktopWorkbenchCapabilityClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkbenchCapabilityClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopWorkbenchCapabilityClientProviderReasonCodeV2) {
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
  projectBlackboardOperationsV2: Pick<
    DesktopProjectBlackboardOperationsV2,
    'probeProjectBlackboard' | 'probeWorkspaceCollaborationCapability'
  >;
  runtimePoolOperationsV2: Pick<DesktopRuntimePoolOperationsV2, 'probeRuntimePool'>;
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
  tenantTasksOperationsV2: Pick<DesktopTenantTasksOperationsV2, 'loadTenantTasks'>;
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

export function createDesktopWorkbenchCapabilityClientProviderV2():
  DesktopWorkbenchCapabilityClientProviderV2 {
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
    projectAgentDashboardOperationsV2: input.projectAgentDashboardOperationsV2,
    projectAgentLogsOperationsV2: input.projectAgentLogsOperationsV2,
    projectAgentPatternsOperationsV2: input.projectAgentPatternsOperationsV2,
    projectOverviewOperationsV2: input.projectOverviewOperationsV2,
    runtimePoolOperationsV2: input.runtimePoolOperationsV2,
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
