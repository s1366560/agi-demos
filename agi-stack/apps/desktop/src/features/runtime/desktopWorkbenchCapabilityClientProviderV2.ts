import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopPluginMarketplaceCatalogOperationsV2 } from '../../plugins/desktopPluginMarketplaceAuthorityModulesV2';
import type { DesktopProjectOverviewOperationsV2 } from '../../plugins/desktopProjectOverviewAuthorityModuleV2';
import type { DesktopTenantAnalyticsOperationsV2 } from '../../plugins/desktopTenantAnalyticsAuthorityModuleV2';
import type { DesktopTenantAgentBindingsOperationsV2 } from '../../plugins/desktopTenantAgentBindingsAuthorityModuleV2';
import type { DesktopTenantAgentDashboardOperationsV2 } from '../../plugins/desktopTenantAgentDashboardAuthorityModuleV2';
import type { DesktopTenantOverviewOperationsV2 } from '../../plugins/desktopTenantOverviewAuthorityModuleV2';
import type { DesktopTenantProjectsOperationsV2 } from '../../plugins/desktopTenantProjectsAuthorityModuleV2';
import type { DesktopTenantTasksOperationsV2 } from '../../plugins/desktopTenantTasksAuthorityModuleV2';
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
    projectOverviewOperationsV2: input.projectOverviewOperationsV2,
    tenantAgentBindingsOperationsV2: input.tenantAgentBindingsOperationsV2,
    tenantAgentDashboardOperationsV2: input.tenantAgentDashboardOperationsV2,
    tenantAnalyticsOperationsV2: input.tenantAnalyticsOperationsV2,
    tenantOverviewOperationsV2: input.tenantOverviewOperationsV2,
    tenantProjectsOperationsV2: input.tenantProjectsOperationsV2,
    tenantTasksOperationsV2: input.tenantTasksOperationsV2,
  });
  return Object.freeze({ client });
}
