import { tenantSkillDefinitionsOperationsV2Fixture } from './tenantSkillOperationsV2Fixture.mjs';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

import { projectOverviewOperationsV2Fixture } from './projectOverviewOperationsV2Fixture.mjs';
import { projectAgentDashboardOperationsV2Fixture } from './projectAgentDashboardOperationsV2Fixture.mjs';
import { projectAgentLogsOperationsV2Fixture } from './projectAgentLogsOperationsV2Fixture.mjs';
import { projectAgentPatternsOperationsV2Fixture } from './projectAgentPatternsOperationsV2Fixture.mjs';
import { projectCommunitiesOperationsV2Fixture } from './projectCommunitiesOperationsV2Fixture.mjs';
import { projectMemoriesOperationsV2Fixture } from './projectMemoriesOperationsV2Fixture.mjs';
import { projectTeamOperationsV2Fixture } from './projectTeamOperationsV2Fixture.mjs';
import { projectSchemaOperationsV2Fixture } from './projectSchemaOperationsV2Fixture.mjs';
import { projectMaintenanceOperationsV2Fixture } from './projectMaintenanceOperationsV2Fixture.mjs';
import { projectSettingsOperationsV2Fixture } from './projectSettingsOperationsV2Fixture.mjs';
import { projectEntitiesOperationsV2Fixture } from './projectEntitiesOperationsV2Fixture.mjs';
import { projectGraphOperationsV2Fixture } from './projectGraphOperationsV2Fixture.mjs';
import { projectBlackboardOperationsV2Fixture } from './projectBlackboardOperationsV2Fixture.mjs';
import { projectWorkspaceOperationsV2Fixture } from './projectWorkspaceOperationsV2Fixture.mjs';
import { runtimePoolOperationsV2Fixture } from './runtimePoolOperationsV2Fixture.mjs';
import { runtimeClustersOperationsV2Fixture } from './runtimeClustersOperationsV2Fixture.mjs';
import { runtimeInstancesOperationsV2Fixture } from './runtimeInstancesOperationsV2Fixture.mjs';
import { runtimeDeploymentsOperationsV2Fixture } from './runtimeDeploymentsOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkbenchCapabilityClientProviderV2,
  DesktopWorkbenchCapabilityClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/runtime/' +
    'desktopWorkbenchCapabilityClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const providerSource = readFileSync(
  new URL('../src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts', import.meta.url),
  'utf8',
);

test('desktop workbench capability client provider fails closed before publication', () => {
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopWorkbenchCapabilityClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_workbench_capability_client_unpublished');
      assert.equal(error.message, 'desktop_workbench_capability_client_unpublished');
      return true;
    },
  );
});

test('each publication returns one frozen generation-pinned capability client binding', () => {
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();
  const local = provider.publish({
    automationApi: automationApi(),
    config: { ...DEFAULT_CONFIG, mode: 'local', projectId: 'project-local' },
    pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
    instanceTemplatesOperationsV2: {
      async probe({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'local_instance_template_authority_unavailable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: 'instance_templates_nested_deep_link_and_deploy_partial',
              allowedActions: ['view', 'list', 'create', 'delete', 'publish', 'clone'],
              authorityRevision: null,
            };
      },
    },
    deadLetterQueueOperationsV2: {
      async probe({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'cloud_message_bus_dlq_not_applicable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: null,
              allowedActions: ['view', 'list'],
              authorityRevision: null,
            };
      },
    },
    backendStoresOperationsV2: backendStoresOperationsV2(),
    projectChannelsOperationsV2: projectChannelsOperationsV2(),
    projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
    projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
    projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
    projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
    projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
    projectSettingsOperationsV2: projectSettingsOperationsV2Fixture(),
    projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
    projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
    projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
    projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
    projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
    runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
    runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
    runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
    runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
    ...projectWorkspaceOperationsV2Fixture(),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2(),
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2(),
    tenantSkillDefinitionsOperationsV2: tenantSkillDefinitionsOperationsV2Fixture(),
    tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2(),
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2(),
    tenantOverviewOperationsV2: tenantOverviewOperationsV2(),
    tenantProjectsOperationsV2: tenantProjectsOperationsV2(),
    tenantTasksOperationsV2: tenantTasksOperationsV2(),
  });
  const cloud = provider.publish({
    automationApi: automationApi(),
    config: { ...DEFAULT_CONFIG, mode: 'cloud', projectId: 'project-cloud' },
    pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
    instanceTemplatesOperationsV2: {
      async probe({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'local_instance_template_authority_unavailable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: 'instance_templates_nested_deep_link_and_deploy_partial',
              allowedActions: ['view', 'list', 'create', 'delete', 'publish', 'clone'],
              authorityRevision: null,
            };
      },
    },
    deadLetterQueueOperationsV2: {
      async probe({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'cloud_message_bus_dlq_not_applicable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: null,
              allowedActions: ['view', 'list'],
              authorityRevision: null,
            };
      },
    },
    backendStoresOperationsV2: backendStoresOperationsV2(),
    projectChannelsOperationsV2: projectChannelsOperationsV2(),
    projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
    projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
    projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
    projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
    projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
    projectSettingsOperationsV2: projectSettingsOperationsV2Fixture(),
    projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
    projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
    projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
    projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
    projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
    runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
    runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
    runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
    runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
    ...projectWorkspaceOperationsV2Fixture(),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2(),
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2(),
    tenantSkillDefinitionsOperationsV2: tenantSkillDefinitionsOperationsV2Fixture(),
    tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2(),
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2(),
    tenantOverviewOperationsV2: tenantOverviewOperationsV2(),
    tenantProjectsOperationsV2: tenantProjectsOperationsV2(),
    tenantTasksOperationsV2: tenantTasksOperationsV2(),
  });

  assert.equal(Object.isFrozen(local), true);
  assert.equal(Object.isFrozen(cloud), true);
  assert.equal(typeof local.client.loadSnapshot, 'function');
  assert.equal(typeof cloud.client.loadSnapshot, 'function');
  assert.notEqual(local, cloud);
  assert.notEqual(local.client, cloud.client);
  assert.equal(provider.resolve(), cloud);
});

test('failed capability client publication keeps the last-good binding', () => {
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();
  const lastGood = provider.publish({
    automationApi: automationApi(),
    config: DEFAULT_CONFIG,
    pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
    instanceTemplatesOperationsV2: {
      async probe({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'local_instance_template_authority_unavailable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: 'instance_templates_nested_deep_link_and_deploy_partial',
              allowedActions: ['view', 'list', 'create', 'delete', 'publish', 'clone'],
              authorityRevision: null,
            };
      },
    },
    deadLetterQueueOperationsV2: {
      async probe({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'cloud_message_bus_dlq_not_applicable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: null,
              allowedActions: ['view', 'list'],
              authorityRevision: null,
            };
      },
    },
    backendStoresOperationsV2: backendStoresOperationsV2(),
    projectChannelsOperationsV2: projectChannelsOperationsV2(),
    projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
    projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
    projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
    projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
    projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
    projectSettingsOperationsV2: projectSettingsOperationsV2Fixture(),
    projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
    projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
    projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
    projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
    projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
    runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
    runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
    runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
    runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
    ...projectWorkspaceOperationsV2Fixture(),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2(),
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2(),
    tenantSkillDefinitionsOperationsV2: tenantSkillDefinitionsOperationsV2Fixture(),
    tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2(),
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2(),
    tenantOverviewOperationsV2: tenantOverviewOperationsV2(),
    tenantProjectsOperationsV2: tenantProjectsOperationsV2(),
    tenantTasksOperationsV2: tenantTasksOperationsV2(),
  });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get projectId() {
      throw new Error('candidate_capability_config_invalid');
    },
  };

  assert.throws(
    () =>
      provider.publish({
        automationApi: automationApi(),
        config: poisonedConfig,
        pluginMarketplaceOperationsV2: pluginMarketplaceOperationsV2(),
        instanceTemplatesOperationsV2: {
          async probe({ config }) {
            return config.mode === 'local'
              ? {
                  availability: 'not_applicable',
                  reasonCode: 'local_instance_template_authority_unavailable',
                  allowedActions: [],
                  authorityRevision: null,
                }
              : {
                  availability: 'available',
                  reasonCode: 'instance_templates_nested_deep_link_and_deploy_partial',
                  allowedActions: ['view', 'list', 'create', 'delete', 'publish', 'clone'],
                  authorityRevision: null,
                };
          },
        },
        deadLetterQueueOperationsV2: {
          async probe({ config }) {
            return config.mode === 'local'
              ? {
                  availability: 'not_applicable',
                  reasonCode: 'cloud_message_bus_dlq_not_applicable',
                  allowedActions: [],
                  authorityRevision: null,
                }
              : {
                  availability: 'available',
                  reasonCode: null,
                  allowedActions: ['view', 'list'],
                  authorityRevision: null,
                };
          },
        },
        backendStoresOperationsV2: backendStoresOperationsV2(),
        projectChannelsOperationsV2: projectChannelsOperationsV2(),
        projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
        projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
        projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
        projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
        projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
        projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
        projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
        projectSettingsOperationsV2: projectSettingsOperationsV2Fixture(),
        projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
        projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
        projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
        projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
        projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
        runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
        runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
        runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
        runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
        ...projectWorkspaceOperationsV2Fixture(),
        tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2(),
        tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2(),
        tenantSkillDefinitionsOperationsV2: tenantSkillDefinitionsOperationsV2Fixture(),
        tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2(),
        tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2(),
        tenantOverviewOperationsV2: tenantOverviewOperationsV2(),
        tenantProjectsOperationsV2: tenantProjectsOperationsV2(),
        tenantTasksOperationsV2: tenantTasksOperationsV2(),
      }),
    /candidate_capability_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

test('App consumes the published V2 workbench capability client', () => {
  assert.match(appSource, /desktopWorkbenchCapabilityClientProviderV2\.publish\(\{/u);
  assert.match(appSource, /automationApi:\s*desktopAutomationApiV2/u);
  assert.match(appSource, /desktopWorkspaceCatalogOperationsV2,/u);
  assert.match(appSource, /desktopWorkspaceLifecycleOperationsV2,/u);
  assert.match(
    appSource,
    /projectAgentDashboardOperationsV2:\s*desktopProjectAgentDashboardOperationsV2/u,
  );
  assert.match(appSource, /projectAgentLogsOperationsV2:\s*desktopProjectAgentLogsOperationsV2/u);
  assert.match(
    appSource,
    /projectAgentPatternsOperationsV2:\s*desktopProjectAgentPatternsOperationsV2/u,
  );
  assert.match(
    appSource,
    /projectCommunitiesOperationsV2:\s*desktopProjectCommunitiesOperationsV2/u,
  );
  assert.match(appSource, /projectMemoriesOperationsV2:\s*desktopProjectMemoriesOperationsV2/u);
  assert.match(appSource, /projectTeamOperationsV2:\s*desktopProjectTeamOperationsV2/u);
  assert.match(appSource, /projectSchemaOperationsV2:\s*desktopProjectSchemaOperationsV2/u);
  assert.match(
    appSource,
    /projectMaintenanceOperationsV2:\s*desktopProjectMaintenanceOperationsV2/u,
  );
  assert.match(appSource, /projectEntitiesOperationsV2:\s*desktopProjectEntitiesOperationsV2/u);
  assert.match(appSource, /projectGraphOperationsV2:\s*desktopProjectGraphOperationsV2/u);
  assert.match(
    appSource,
    /useDesktopCapabilitySnapshot\(\s*desktopWorkbenchCapabilityClientV2\.client/u,
  );
  assert.doesNotMatch(appSource, /createDesktopWorkbenchCapabilityClient\(/u);
  assert.match(
    providerSource,
    /createDesktopWorkbenchCapabilityClient\(input\.automationApi, config, \{/u,
  );
  assert.match(
    providerSource,
    /pluginMarketplaceOperationsV2:\s*input\.pluginMarketplaceOperationsV2/u,
  );
  assert.match(
    providerSource,
    /projectAgentDashboardOperationsV2:\s*input\.projectAgentDashboardOperationsV2/u,
  );
  assert.match(
    providerSource,
    /projectAgentLogsOperationsV2:\s*input\.projectAgentLogsOperationsV2/u,
  );
  assert.match(
    providerSource,
    /projectAgentPatternsOperationsV2:\s*input\.projectAgentPatternsOperationsV2/u,
  );
  assert.match(
    providerSource,
    /projectCommunitiesOperationsV2:\s*input\.projectCommunitiesOperationsV2/u,
  );
  assert.match(
    providerSource,
    /projectMemoriesOperationsV2:\s*input\.projectMemoriesOperationsV2/u,
  );
  assert.match(providerSource, /projectTeamOperationsV2:\s*input\.projectTeamOperationsV2/u);
  assert.match(providerSource, /projectSchemaOperationsV2:\s*input\.projectSchemaOperationsV2/u);
  assert.match(
    providerSource,
    /projectMaintenanceOperationsV2:\s*input\.projectMaintenanceOperationsV2/u,
  );
  assert.match(
    providerSource,
    /projectEntitiesOperationsV2:\s*input\.projectEntitiesOperationsV2/u,
  );
  assert.match(providerSource, /projectGraphOperationsV2:\s*input\.projectGraphOperationsV2/u);
  assert.match(
    providerSource,
    /projectOverviewOperationsV2:\s*input\.projectOverviewOperationsV2/u,
  );
  assert.match(
    providerSource,
    /projectBlackboardOperationsV2:\s*input\.projectBlackboardOperationsV2/u,
  );
  assert.match(providerSource, /runtimePoolOperationsV2:\s*input\.runtimePoolOperationsV2/u);
  assert.match(
    providerSource,
    /runtimeClustersOperationsV2:\s*input\.runtimeClustersOperationsV2/u,
  );
  assert.match(providerSource, /createProjectWorkspacesV2Client\(config,\s*\{/u);
  assert.match(providerSource, /catalogOperations:\s*input\.desktopWorkspaceCatalogOperationsV2/u);
  assert.match(
    providerSource,
    /lifecycleOperations:\s*input\.desktopWorkspaceLifecycleOperationsV2/u,
  );
  assert.match(
    providerSource,
    /tenantAgentBindingsOperationsV2:\s*input\.tenantAgentBindingsOperationsV2/u,
  );
  assert.match(
    providerSource,
    /tenantAgentDashboardOperationsV2:\s*input\.tenantAgentDashboardOperationsV2/u,
  );
  assert.match(
    providerSource,
    /tenantAgentDefinitionsOperationsV2:\s*input\.tenantAgentDefinitionsOperationsV2/u,
  );
  assert.match(
    providerSource,
    /tenantAnalyticsOperationsV2:\s*input\.tenantAnalyticsOperationsV2/u,
  );
  assert.match(providerSource, /tenantOverviewOperationsV2:\s*input\.tenantOverviewOperationsV2/u);
  assert.match(providerSource, /tenantProjectsOperationsV2:\s*input\.tenantProjectsOperationsV2/u);
  assert.match(providerSource, /tenantTasksOperationsV2:\s*input\.tenantTasksOperationsV2/u);
});

function automationApi() {
  return {
    getAutomationCapabilities: async () => ({
      service_version: '0.1.0',
      contract_version: '1.0.0',
      revision: 1,
      supports: { run_now: true, cron_jobs: true },
    }),
  };
}

function pluginMarketplaceOperationsV2() {
  return {
    projectMarketplacePlugins: async (_config, _signal, project) => project([]),
  };
}

function backendStoresOperationsV2() {
  return Object.freeze({
    async probeBackendStores({ config }) {
      return config.mode === 'local'
        ? Object.freeze({
            availability: 'not_applicable',
            reasonCode: 'local_backend_stores_cloud_authority_unavailable',
            allowedActions: Object.freeze([]),
            authorityRevision: null,
          })
        : Object.freeze({
            availability: 'available',
            reasonCode: null,
            allowedActions: Object.freeze(['view', 'list', 'create', 'update', 'delete', 'test']),
            authorityRevision: 23,
          });
    },
  });
}

function projectChannelsOperationsV2() {
  return Object.freeze({
    loadProjectChannels: async () => {
      throw new Error('project_channels_not_exercised');
    },
    getProjectChannelSchema: async () => {
      throw new Error('project_channels_not_exercised');
    },
    createProjectChannelConfig: async () => {
      throw new Error('project_channels_not_exercised');
    },
    updateProjectChannelConfig: async () => {
      throw new Error('project_channels_not_exercised');
    },
    testProjectChannelConfig: async () => {
      throw new Error('project_channels_not_exercised');
    },
    removeProjectChannelConfig: async () => {
      throw new Error('project_channels_not_exercised');
    },
  });
}

function tenantAnalyticsOperationsV2() {
  return {
    loadTenantAnalytics: async () => {
      throw new Error('tenant_analytics_not_exercised');
    },
  };
}

function tenantAgentDashboardOperationsV2() {
  return {
    loadTenantAgentDashboard: async () => {
      throw new Error('tenant_agent_dashboard_not_exercised');
    },
  };
}

function tenantAgentDefinitionsOperationsV2() {
  return {
    loadTenantAgentDefinitions: async () => {
      throw new Error('tenant_agent_definitions_not_exercised');
    },
  };
}

function tenantAgentBindingsOperationsV2() {
  return {
    listTenantAgentBindings: async () => {
      throw new Error('tenant_agent_bindings_not_exercised');
    },
  };
}

function tenantOverviewOperationsV2() {
  return {
    loadTenantOverview: async () => {
      throw new Error('tenant_overview_not_exercised');
    },
  };
}

function tenantProjectsOperationsV2() {
  return {
    listTenantProjects: async () => {
      throw new Error('tenant_projects_not_exercised');
    },
  };
}

function tenantTasksOperationsV2() {
  return {
    loadTenantTasks: async () => {
      throw new Error('tenant_tasks_not_exercised');
    },
  };
}
