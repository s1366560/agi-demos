import assert from 'node:assert/strict';
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
import { projectWorkspacesClientV2Fixture } from './projectWorkspacesClientV2Fixture.mjs';
import { runtimePoolOperationsV2Fixture } from './runtimePoolOperationsV2Fixture.mjs';
import { runtimeClustersOperationsV2Fixture } from './runtimeClustersOperationsV2Fixture.mjs';
import { runtimeInstancesOperationsV2Fixture } from './runtimeInstancesOperationsV2Fixture.mjs';
import { runtimeDeploymentsOperationsV2Fixture } from './runtimeDeploymentsOperationsV2Fixture.mjs';
import { tenantAnalyticsOperationsV2Fixture } from './tenantAnalyticsOperationsV2Fixture.mjs';
import { tenantAgentBindingsOperationsV2Fixture } from './tenantAgentBindingsOperationsV2Fixture.mjs';
import { tenantProjectsOperationsV2Fixture } from './tenantProjectsOperationsV2Fixture.mjs';
import { tenantTasksOperationsV2Fixture } from './tenantTasksOperationsV2Fixture.mjs';
import { tenantAgentDashboardOperationsV2Fixture } from './tenantAgentDashboardOperationsV2Fixture.mjs';
import { tenantAgentDefinitionsOperationsV2Fixture } from './tenantAgentDefinitionsOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
const {
  createDesktopWorkbenchCapabilityClient: createDesktopWorkbenchCapabilityClientRaw,
  normalizeAutomationCapabilityContract,
  normalizeLocalSearchCapabilityContract,
  normalizeSearchCapabilityContract,
  normalizeWorkspaceCollaborationAuthorityContract,
  normalizeWorkspaceCollaborationCapabilityContract,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

function createDesktopWorkbenchCapabilityClient(automationApi, config, options) {
  return createDesktopWorkbenchCapabilityClientRaw(automationApi, config, {
    ...options,
    tenantAgentDefinitionsOperationsV2:
      options?.tenantAgentDefinitionsOperationsV2 ?? tenantAgentDefinitionsOperationsV2Fixture(),
  });
}

const searchContract = {
  service_version: '0.1.0',
  contract_version: '2.0.0',
  search_types: {
    semantic: {
      description: 'Semantic search',
      endpoint: '/api/v1/memory/search',
      parameters: {},
    },
    advanced: {
      description: 'Advanced semantic search',
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
    graph_traversal: {
      description: 'Graph traversal',
      endpoint: '/api/v1/search-enhanced/graph-traversal',
      parameters: {},
    },
    community: {
      description: 'Community search',
      endpoint: '/api/v1/search-enhanced/community',
      parameters: {},
    },
    temporal: {
      description: 'Temporal search',
      endpoint: '/api/v1/search-enhanced/temporal',
      parameters: {},
    },
    faceted: {
      description: 'Faceted search',
      endpoint: '/api/v1/search-enhanced/faceted',
      parameters: {},
    },
  },
  filters: {
    entity_types: [],
    relationship_types: [],
  },
};

const automationContract = {
  service_version: '0.1.0',
  contract_version: '2.0.0',
  schema_version: 1,
  read: true,
  revision_guarded: true,
  idempotency_guarded: true,
  durable_execution: true,
  supported_read_trigger_kinds: ['manual', 'schedule', 'event'],
  create: { allowed: true },
  edit: { allowed: true },
  toggle: { allowed: true },
  run_now: { allowed: true },
  delete: { allowed: true },
};

test('workbench capability client requires the Tenant Agent Bindings V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        undefined,
      ),
    /desktop_tenant_agent_bindings_authority_required/u,
  );
});

test('workbench capability client requires the Tenant Analytics V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        { tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture() },
      ),
    /desktop_tenant_analytics_authority_required/u,
  );
});

test('workbench capability client requires the Tenant Agent Dashboard V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        {
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
        },
      ),
    /desktop_tenant_agent_dashboard_authority_required/u,
  );
});

test('workbench capability client requires the Tenant Agent Definitions V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClientRaw(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        {
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
        },
      ),
    /desktop_tenant_agent_definitions_authority_required/u,
  );
});

test('workbench capability client requires the Tenant Projects V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        {
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
        },
      ),
    /desktop_tenant_projects_authority_required/u,
  );
});

test('workbench capability client requires the Tenant Tasks V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        {
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
        },
      ),
    /desktop_tenant_tasks_authority_required/u,
  );
});

test('workbench capability client requires the Project Overview V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        {
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
          tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        },
      ),
    /desktop_project_overview_authority_required/u,
  );
});

test('workbench capability client requires the Runtime Pool V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        {
          projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
          tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        },
      ),
    /desktop_runtime_pool_authority_required/u,
  );
});

test('workbench capability client requires the Runtime Clusters V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        {
          projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
          runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
          tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        },
      ),
    /desktop_runtime_clusters_authority_required/u,
  );
});

test('workbench capability client requires an injected Project Workspaces V2 client', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        {
          projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
          runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
          runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
          runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
          runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
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
          backendStoresOperationsV2: {
            async probeBackendStores() {
              throw new Error('backend_stores_not_exercised');
            },
          },
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
          tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        },
      ),
    /desktop_project_workspaces_authority_required/u,
  );
});

test('workbench capability client requires the Project Blackboard V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        {
          projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
          runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
          runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
          runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
          runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
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
          backendStoresOperationsV2: {
            async probeBackendStores({ config }) {
              return config.mode === 'local'
                ? {
                    availability: 'not_applicable',
                    reasonCode: 'local_backend_stores_cloud_authority_unavailable',
                    allowedActions: [],
                    authorityRevision: null,
                  }
                : {
                    availability: 'available',
                    reasonCode: null,
                    allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
                    authorityRevision: 23,
                  };
            },
          },
          projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
          tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        },
      ),
    /desktop_project_blackboard_authority_required/u,
  );
});

test('workbench capability client requires the Project Agent Dashboard V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        {
          projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
          runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
          runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
          runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
          runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
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
          backendStoresOperationsV2: {
            async probeBackendStores({ config }) {
              return config.mode === 'local'
                ? {
                    availability: 'not_applicable',
                    reasonCode: 'local_backend_stores_cloud_authority_unavailable',
                    allowedActions: [],
                    authorityRevision: null,
                  }
                : {
                    availability: 'available',
                    reasonCode: null,
                    allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
                    authorityRevision: 23,
                  };
            },
          },
          projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
          projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
          tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        },
      ),
    /desktop_project_agent_dashboard_authority_required/u,
  );
});

test('workbench capability client requires the Project Agent Logs V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        {
          projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
          runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
          runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
          runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
          runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
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
          backendStoresOperationsV2: {
            async probeBackendStores({ config }) {
              return config.mode === 'local'
                ? {
                    availability: 'not_applicable',
                    reasonCode: 'local_backend_stores_cloud_authority_unavailable',
                    allowedActions: [],
                    authorityRevision: null,
                  }
                : {
                    availability: 'available',
                    reasonCode: null,
                    allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
                    authorityRevision: 23,
                  };
            },
          },
          projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
          projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
          projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
          tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        },
      ),
    /desktop_project_agent_logs_authority_required/u,
  );
});

test('workbench capability client requires the Project Agent Patterns V2 authority', () => {
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        {
          projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
          runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
          runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
          runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
          runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
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
          backendStoresOperationsV2: {
            async probeBackendStores({ config }) {
              return config.mode === 'local'
                ? {
                    availability: 'not_applicable',
                    reasonCode: 'local_backend_stores_cloud_authority_unavailable',
                    allowedActions: [],
                    authorityRevision: null,
                  }
                : {
                    availability: 'available',
                    reasonCode: null,
                    allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
                    authorityRevision: 23,
                  };
            },
          },
          projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
          projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
          projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
          projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
          tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
          tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
          tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
          tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
          tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
        },
      ),
    /desktop_project_agent_patterns_authority_required/u,
  );
});

test('workbench capability client requires the Project Communities V2 authority', () => {
  const requiredOptions = {
    projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
    projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
    projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
    projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
    projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
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
    backendStoresOperationsV2: {
      async probeBackendStores({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'local_backend_stores_cloud_authority_unavailable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: null,
              allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
              authorityRevision: 23,
            };
      },
    },
    projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
    runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
    runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
    runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
    runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
    tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
    tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
  };

  for (const projectCommunitiesOperationsV2 of [undefined, {}]) {
    assert.throws(
      () =>
        createDesktopWorkbenchCapabilityClient(
          { getAutomationCapabilities: async () => automationContract },
          DEFAULT_CONFIG,
          { ...requiredOptions, projectCommunitiesOperationsV2 },
        ),
      /desktop_project_communities_authority_required/u,
    );
  }
});

test('workbench capability client requires the Project Memories V2 authority', () => {
  const requiredOptions = {
    projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
    projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
    projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
    projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
    projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
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
    backendStoresOperationsV2: {
      async probeBackendStores({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'local_backend_stores_cloud_authority_unavailable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: null,
              allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
              authorityRevision: 23,
            };
      },
    },
    projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
    runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
    runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
    runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
    runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
    tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
    tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
  };

  for (const projectMemoriesOperationsV2 of [undefined, {}]) {
    assert.throws(
      () =>
        createDesktopWorkbenchCapabilityClient(
          { getAutomationCapabilities: async () => automationContract },
          DEFAULT_CONFIG,
          { ...requiredOptions, projectMemoriesOperationsV2 },
        ),
      /desktop_project_memories_authority_required/u,
    );
  }
});

test('workbench capability client requires the Project Team V2 authority', () => {
  const requiredOptions = {
    projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
    projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
    projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
    projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
    projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
    projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
    projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
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
    backendStoresOperationsV2: {
      async probeBackendStores({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'local_backend_stores_cloud_authority_unavailable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: null,
              allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
              authorityRevision: 23,
            };
      },
    },
    projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
    runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
    runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
    runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
    runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
    tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
    tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
  };

  for (const projectTeamOperationsV2 of [undefined, {}]) {
    assert.throws(
      () =>
        createDesktopWorkbenchCapabilityClient(
          { getAutomationCapabilities: async () => automationContract },
          DEFAULT_CONFIG,
          { ...requiredOptions, projectTeamOperationsV2 },
        ),
      /desktop_project_team_authority_required/u,
    );
  }
});

test('workbench capability client requires the Project Schema V2 authority', () => {
  const requiredOptions = {
    projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
    projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
    projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
    projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
    projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
    projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
    projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
    projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
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
    backendStoresOperationsV2: {
      async probeBackendStores({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'local_backend_stores_cloud_authority_unavailable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: null,
              allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
              authorityRevision: 23,
            };
      },
    },
    projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
    runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
    runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
    runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
    runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
    tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
    tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
  };

  for (const projectSchemaOperationsV2 of [undefined, {}]) {
    assert.throws(
      () =>
        createDesktopWorkbenchCapabilityClient(
          { getAutomationCapabilities: async () => automationContract },
          DEFAULT_CONFIG,
          { ...requiredOptions, projectSchemaOperationsV2 },
        ),
      /desktop_project_schema_authority_required/u,
    );
  }
});

test('workbench capability client requires the Project Maintenance V2 authority', () => {
  const requiredOptions = {
    projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
    projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
    projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
    projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
    projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
    projectSettingsOperationsV2: projectSettingsOperationsV2Fixture(),
    projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
    projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
    projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
    projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
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
    backendStoresOperationsV2: {
      async probeBackendStores({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'local_backend_stores_cloud_authority_unavailable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: null,
              allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
              authorityRevision: 23,
            };
      },
    },
    projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
    runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
    runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
    runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
    runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
    tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
    tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
  };

  for (const projectMaintenanceOperationsV2 of [undefined, {}]) {
    assert.throws(
      () =>
        createDesktopWorkbenchCapabilityClient(
          { getAutomationCapabilities: async () => automationContract },
          DEFAULT_CONFIG,
          { ...requiredOptions, projectMaintenanceOperationsV2 },
        ),
      /desktop_project_maintenance_authority_required/u,
    );
  }
});

test('workbench capability client requires the Project Settings V2 authority', () => {
  const requiredOptions = {
    projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
    projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
    projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
    projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
    projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
    projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
    projectEntitiesOperationsV2: projectEntitiesOperationsV2Fixture(),
    projectGraphOperationsV2: projectGraphOperationsV2Fixture(),
    projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
    projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
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
    backendStoresOperationsV2: {
      async probeBackendStores({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'local_backend_stores_cloud_authority_unavailable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: null,
              allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
              authorityRevision: 23,
            };
      },
    },
    projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
    runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
    runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
    runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
    runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
    tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
    tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
  };

  for (const projectSettingsOperationsV2 of [undefined, {}]) {
    assert.throws(
      () =>
        createDesktopWorkbenchCapabilityClient(
          { getAutomationCapabilities: async () => automationContract },
          DEFAULT_CONFIG,
          { ...requiredOptions, projectSettingsOperationsV2 },
        ),
      /desktop_project_settings_authority_required/u,
    );
  }
});

test('workbench capability client requires the Project Graph V2 authority', () => {
  const requiredOptions = {
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
    projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
    projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
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
    backendStoresOperationsV2: {
      async probeBackendStores({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'local_backend_stores_cloud_authority_unavailable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: null,
              allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
              authorityRevision: 23,
            };
      },
    },
    projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
    runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
    runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
    runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
    runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
    tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
    tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
  };

  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        requiredOptions,
      ),
    /desktop_project_graph_authority_required/u,
  );
  assert.throws(
    () =>
      createDesktopWorkbenchCapabilityClient(
        { getAutomationCapabilities: async () => automationContract },
        DEFAULT_CONFIG,
        { ...requiredOptions, projectGraphOperationsV2: {} },
      ),
    /desktop_project_graph_authority_required/u,
  );
});

test('workbench capability client requires both Project Entities V2 operations', () => {
  const requiredOptions = {
    projectAgentDashboardOperationsV2: projectAgentDashboardOperationsV2Fixture(),
    projectAgentLogsOperationsV2: projectAgentLogsOperationsV2Fixture(),
    projectAgentPatternsOperationsV2: projectAgentPatternsOperationsV2Fixture(),
    projectCommunitiesOperationsV2: projectCommunitiesOperationsV2Fixture(),
    projectTeamOperationsV2: projectTeamOperationsV2Fixture(),
    projectSchemaOperationsV2: projectSchemaOperationsV2Fixture(),
    projectMaintenanceOperationsV2: projectMaintenanceOperationsV2Fixture(),
    projectSettingsOperationsV2: projectSettingsOperationsV2Fixture(),
    projectMemoriesOperationsV2: projectMemoriesOperationsV2Fixture(),
    projectOverviewOperationsV2: projectOverviewOperationsV2Fixture(),
    projectBlackboardOperationsV2: projectBlackboardOperationsV2Fixture(),
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
    backendStoresOperationsV2: {
      async probeBackendStores({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'local_backend_stores_cloud_authority_unavailable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: null,
              allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
              authorityRevision: 23,
            };
      },
    },
    projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
    runtimePoolOperationsV2: runtimePoolOperationsV2Fixture(),
    runtimeClustersOperationsV2: runtimeClustersOperationsV2Fixture(),
    runtimeInstancesOperationsV2: runtimeInstancesOperationsV2Fixture(),
    runtimeDeploymentsOperationsV2: runtimeDeploymentsOperationsV2Fixture(),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
    tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
    tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
  };

  for (const projectEntitiesOperationsV2 of [
    undefined,
    {},
    { loadProjectEntities: async () => ({}) },
  ]) {
    assert.throws(
      () =>
        createDesktopWorkbenchCapabilityClient(
          { getAutomationCapabilities: async () => automationContract },
          DEFAULT_CONFIG,
          { ...requiredOptions, projectEntitiesOperationsV2 },
        ),
      /desktop_project_entities_authority_required/u,
    );
  }
});

const workspaceCollaborationContract = {
  service_version: '0.1.0',
  contract_version: '2.0.0',
  authority: 'cloud',
  tenant_id: 'tenant / 1',
  project_id: 'project / 1',
  workspace_id: 'workspace / 1',
  status: 'degraded',
  reason_code: 'workspace_collaboration_mutation_guards_unavailable',
  canonical_read: true,
  read_surfaces: [
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
  ],
  mutations: {
    allowed: false,
    revision_guarded: false,
    idempotency_guarded: false,
  },
  allowed_actions: {},
};

const workspaceReadActions = workspaceCollaborationContract.read_surfaces.map(
  (surface) => `${surface}:view`,
);
const workspaceCollaborationAuthority = {
  contract_version: '2.0.0',
  tenant_id: 'tenant / 1',
  project_id: 'project / 1',
  workspace_id: 'workspace / 1',
  revision: 7,
  cursor: 'workspace:workspace / 1:revision:7',
};

const emptyScope = {
  tenant_id: null,
  project_id: null,
  workspace_id: null,
  instance_id: null,
};

const managementRouteCapabilityIds = [
  'tenant-tenant-providers',
  'tenant-tenant-agent-definitions',
  'tenant-tenant-skills',
  'tenant-tenant-plugins',
  'tenant-tenant-mcp-servers',
];

function managementRouteClients(observe) {
  return Object.fromEntries(
    managementRouteCapabilityIds.map((capability) => [capability, Object.freeze({ observe })]),
  );
}

function availableCapability(allowedActions = []) {
  return {
    availability: 'available',
    reason_code: null,
    service_version: '0.1.0',
    contract_version: '2.0.0',
    allowed_actions: allowedActions,
    scope: emptyScope,
    authority_revision: null,
  };
}

function degradedCapability(reasonCode, allowedActions = [], authorityRevision = null) {
  return {
    availability: 'degraded',
    reason_code: reasonCode,
    service_version: '0.1.0',
    contract_version: '2.0.0',
    allowed_actions: allowedActions,
    scope: emptyScope,
    authority_revision: authorityRevision,
  };
}

function unavailableCapability(
  reasonCode,
  versioned = false,
  serviceVersion = versioned ? '0.1.0' : null,
  contractVersion = versioned ? '2.0.0' : null,
) {
  return {
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: serviceVersion,
    contract_version: contractVersion,
    allowed_actions: [],
    scope: emptyScope,
    authority_revision: null,
  };
}

function notApplicableCapability(reasonCode) {
  return {
    availability: 'not_applicable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    scope: emptyScope,
    authority_revision: null,
  };
}

function withScope(capability, scope) {
  return { ...capability, scope };
}

function withObservedAuthority(capability, authoritySource) {
  return {
    ...capability,
    retryable: false,
    authority_source: authoritySource,
    supporting_authority_sources: [],
    provenance: 'observed',
  };
}

function withObservedCompoundCloudAuthority(capability) {
  return {
    ...withObservedAuthority(capability, 'cloud_service'),
    supporting_authority_sources: ['sidecar', 'electron'],
  };
}

function withDeclaredAuthority(capability) {
  const active = capability.availability === 'available' || capability.availability === 'degraded';
  return {
    ...(active
      ? {
          ...capability,
          availability: 'unavailable',
          reason_code: 'renderer_capability_authority_unobserved',
          allowed_actions: [],
          authority_revision: null,
        }
      : capability),
    retryable: capability.retryable ?? false,
    authority_source: 'renderer',
    supporting_authority_sources: [],
    provenance: 'declared',
  };
}

function withoutAuthorityRevision(capability) {
  return {
    ...capability,
    availability: 'unavailable',
    reason_code: 'capability_authority_revision_unavailable',
    allowed_actions: [],
  };
}

test('cloud client validates structured Search and Automation authorities', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return new Response(JSON.stringify(searchContract), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = createWorkbenchCapabilityClient(
      {
        getAutomationCapabilities: async () => automationContract,
      },
      {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'https://api.memstack.test',
        apiKey: 'session-credential',
        mode: 'cloud',
        projectId: 'project/1',
      },
      {
        cloudRequestBroker: {
          async requestJson(request) {
            assert.equal(request.path, '/api/v1/workspace-context');
            return {
              context: {
                tenant_id: 'default',
                project_id: 'project/1',
                revision: 23,
              },
              membership_role: 'admin',
            };
          },
          async requestNoContent() {},
        },
      },
    );
    const snapshot = await client.loadSnapshot();

    const scope = {
      tenant_id: 'default',
      project_id: 'project/1',
      workspace_id: null,
      instance_id: null,
    };
    assert.deepEqual(
      snapshot.capabilities.search,
      withObservedAuthority(
        withScope(
          withoutAuthorityRevision(
            availableCapability([
              'semantic',
              'advanced',
              'graph_traversal',
              'community',
              'temporal',
              'faceted',
            ]),
          ),
          scope,
        ),
        'cloud_service',
      ),
    );
    assert.deepEqual(snapshot.capabilities['project-project-search'], snapshot.capabilities.search);
    assert.deepEqual(
      snapshot.capabilities.automation_run,
      withObservedAuthority(
        withScope(withoutAuthorityRevision(availableCapability(['run_now'])), scope),
        'cloud_service',
      ),
    );
    assert.deepEqual(
      snapshot.capabilities['project-project-cron-jobs'],
      withObservedAuthority(
        withScope(
          withoutAuthorityRevision(
            availableCapability([
              'view',
              'list',
              'view-history',
              'inspect-capabilities',
              'create',
              'update',
              'toggle',
              'run-now',
              'delete',
            ]),
          ),
          scope,
        ),
        'cloud_service',
      ),
    );
    assert.deepEqual(
      snapshot.capabilities['tenant-tenant-tasks'],
      withObservedAuthority(
        {
          availability: 'unavailable',
          reason_code: 'capability_authority_revision_unavailable',
          service_version: '0.1.0',
          contract_version: '3.0.0',
          allowed_actions: [],
          scope: {
            tenant_id: 'default',
            project_id: null,
            workspace_id: null,
            instance_id: null,
          },
          authority_revision: null,
        },
        'cloud_service',
      ),
    );
    assert.deepEqual(
      snapshot.capabilities['tenant-tenant-pool'],
      withObservedAuthority(
        {
          availability: 'unavailable',
          reason_code: 'capability_authority_revision_unavailable',
          service_version: '0.1.0',
          contract_version: '3.0.0',
          allowed_actions: [],
          scope: {
            tenant_id: 'default',
            project_id: null,
            workspace_id: null,
            instance_id: null,
          },
          authority_revision: null,
        },
        'cloud_service',
      ),
    );
    assert.deepEqual(
      snapshot.capabilities['tenant-tenant-instances'],
      withObservedAuthority(
        {
          availability: 'unavailable',
          reason_code: 'capability_authority_revision_unavailable',
          service_version: '0.1.0',
          contract_version: '3.0.0',
          allowed_actions: [],
          scope: {
            tenant_id: 'default',
            project_id: null,
            workspace_id: null,
            instance_id: null,
          },
          authority_revision: null,
        },
        'cloud_service',
      ),
    );
    assert.deepEqual(
      snapshot.capabilities['tenant-tenant-clusters'],
      withObservedAuthority(
        {
          availability: 'unavailable',
          reason_code: 'capability_authority_revision_unavailable',
          service_version: '0.1.0',
          contract_version: '3.0.0',
          allowed_actions: [],
          scope: {
            tenant_id: 'default',
            project_id: null,
            workspace_id: null,
            instance_id: null,
          },
          authority_revision: null,
        },
        'cloud_service',
      ),
    );
    assert.deepEqual(
      snapshot.capabilities['tenant-tenant-deploy'],
      withObservedAuthority(
        withoutAuthorityRevision({
          availability: 'degraded',
          reason_code: 'runtime_deployments_mutations_and_instance_discovery_partial',
          service_version: '0.1.0',
          contract_version: '3.0.0',
          allowed_actions: [
            'view',
            'list',
            'refresh',
            'paginate',
            'inspect-progress',
            'reconnect-progress',
          ],
          scope: {
            tenant_id: 'default',
            project_id: null,
            workspace_id: null,
            instance_id: null,
          },
          authority_revision: null,
        }),
        'cloud_service',
      ),
    );
    assert.deepEqual(
      snapshot.capabilities['tenant-tenant-dead-letter-queue'],
      withObservedAuthority(
        {
          availability: 'unavailable',
          reason_code: 'capability_authority_revision_unavailable',
          service_version: '1.0.0',
          contract_version: '4.0.0',
          allowed_actions: [],
          scope: {
            tenant_id: 'default',
            project_id: null,
            workspace_id: null,
            instance_id: null,
          },
          authority_revision: null,
        },
        'cloud_service',
      ),
    );
    assert.deepEqual(
      snapshot.capabilities['project-support'],
      withDeclaredAuthority({
        availability: 'available',
        reason_code: null,
        service_version: '0.1.0',
        contract_version: '3.0.0',
        allowed_actions: ['view', 'list', 'create', 'close', 'retry'],
        scope: {
          tenant_id: 'default',
          project_id: 'project/1',
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: null,
      }),
    );
    assert.deepEqual(
      snapshot.capabilities['backend-stores'],
      withObservedCompoundCloudAuthority(
        withScope(
          {
            availability: 'available',
            reason_code: null,
            service_version: '1.0.0',
            contract_version: '4.0.0',
            allowed_actions: ['view', 'list', 'create', 'update', 'delete', 'test'],
            scope: emptyScope,
            authority_revision: 23,
            retryable: false,
          },
          {
            tenant_id: 'default',
            project_id: null,
            workspace_id: null,
            instance_id: null,
          },
        ),
      ),
    );
    assert.deepEqual(
      snapshot.capabilities['project-playbooks'],
      withObservedCompoundCloudAuthority(
        withScope(
          {
            availability: 'available',
            reason_code: null,
            service_version: '0.1.0',
            contract_version: '4.0.0',
            allowed_actions: ['view', 'list', 'refresh', 'review-verdicts'],
            scope: emptyScope,
            authority_revision: 23,
            retryable: false,
          },
          scope,
        ),
      ),
    );
    assert.equal(calls[0]?.input, 'https://api.memstack.test/api/v1/search-enhanced/capabilities');
    assert.equal(calls[0]?.init?.headers.get('Authorization'), 'Bearer session-credential');
    assert.equal(calls[0]?.init?.headers.has('X-Agistack-Launch'), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('management routes become observed only after their typed clients read current authority', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify(searchContract), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });

  try {
    for (const [mode, authoritySource] of [
      ['cloud', 'cloud_service'],
      ['local', 'sidecar'],
    ]) {
      const config = {
        ...DEFAULT_CONFIG,
        mode,
        tenantId: mode === 'local' ? 'local' : 'tenant-1',
        projectId: mode === 'local' ? 'local-project' : 'project-1',
        localApiToken: 'launch-capability',
      };
      const client = createWorkbenchCapabilityClient(
        {
          getAutomationCapabilities: async () => automationContract,
        },
        config,
        {
          tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2Fixture({
            loadTenantAgentDefinitions: async () => [{ id: 'agent-1' }, { id: 'agent-2' }],
          }),
          managementRouteClients: managementRouteClients(async (scope) => ({
            scope,
            itemCount: 2,
          })),
        },
      );
      const snapshot = await client.loadSnapshot();

      for (const capability of managementRouteCapabilityIds) {
        assert.deepEqual(snapshot.capabilities[capability], {
          availability: 'available',
          reason_code: null,
          service_version: '0.1.0',
          contract_version: '4.0.0',
          allowed_actions: ['view', 'list'],
          scope: {
            tenant_id: config.tenantId,
            project_id: config.projectId,
            workspace_id: null,
            instance_id: null,
          },
          authority_revision: 2,
          retryable: false,
          authority_source: authoritySource,
          supporting_authority_sources: [],
          provenance: 'observed',
        });
      }
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('management route observation failures stay unavailable and never promote renderer authority', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify(searchContract), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });

  try {
    const client = createWorkbenchCapabilityClient(
      {
        getAutomationCapabilities: async () => automationContract,
      },
      {
        ...DEFAULT_CONFIG,
        mode: 'cloud',
        tenantId: 'tenant-1',
        projectId: 'project-1',
      },
      {
        tenantAgentDefinitionsOperationsV2: tenantAgentDefinitionsOperationsV2Fixture({
          loadTenantAgentDefinitions: async () => {
            throw new Error('authority unavailable');
          },
        }),
        managementRouteClients: managementRouteClients(async () => {
          throw new Error('authority unavailable');
        }),
      },
    );
    const snapshot = await client.loadSnapshot();

    for (const capability of managementRouteCapabilityIds) {
      assert.deepEqual(snapshot.capabilities[capability], {
        availability: 'unavailable',
        reason_code: `${capability.replaceAll('-', '_')}_authority_unavailable`,
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: null,
        retryable: false,
        authority_source: 'cloud_service',
        supporting_authority_sources: [],
        provenance: 'observed',
      });
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('local workbench capability client consumes the scoped degraded Search contract', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return new Response(
      JSON.stringify({
        service_version: '0.1.0',
        contract_version: '2.0.0',
        mode: 'keyword_degraded',
        reason_code: 'local_embeddings_unavailable',
        tenant_id: 'local',
        project_id: 'local-project',
        projection_revision: 7,
        backfill_cursor: null,
        supported_search_types: ['advanced', 'temporal', 'faceted'],
        unavailable_search_types: ['graph_traversal', 'community'],
      }),
      {
        status: 200,
        headers: { 'content-type': 'application/json' },
      },
    );
  };

  try {
    const client = createWorkbenchCapabilityClient(
      {
        getAutomationCapabilities: async () => ({
          ...automationContract,
          durable_execution: false,
          run_now: {
            allowed: false,
            reason_code: 'durable_automation_execution_unavailable',
          },
        }),
      },
      {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'http://127.0.0.1:4123',
        localApiToken: 'launch-capability',
        mode: 'local',
        tenantId: 'local',
        projectId: 'local-project',
      },
    );
    const snapshot = await client.loadSnapshot();

    assert.deepEqual(
      snapshot.capabilities.search,
      withObservedAuthority(
        withScope(
          degradedCapability(
            'local_embeddings_unavailable',
            ['advanced', 'temporal', 'faceted'],
            7,
          ),
          {
            tenant_id: 'local',
            project_id: 'local-project',
            workspace_id: null,
            instance_id: null,
          },
        ),
        'sidecar',
      ),
    );
    assert.deepEqual(snapshot.capabilities['project-project-search'], snapshot.capabilities.search);
    assert.deepEqual(
      snapshot.capabilities['project-support'],
      withDeclaredAuthority({
        availability: 'not_applicable',
        reason_code: 'local_support_service_not_applicable',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: {
          tenant_id: 'local',
          project_id: 'local-project',
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: null,
      }),
    );
    assert.deepEqual(
      snapshot.capabilities['backend-stores'],
      withDeclaredAuthority(
        withScope(
          {
            availability: 'not_applicable',
            reason_code: 'local_backend_stores_cloud_authority_unavailable',
            service_version: null,
            contract_version: null,
            allowed_actions: [],
            scope: emptyScope,
            authority_revision: null,
            retryable: false,
          },
          {
            tenant_id: 'local',
            project_id: null,
            workspace_id: null,
            instance_id: null,
          },
        ),
      ),
    );
    assert.deepEqual(
      snapshot.capabilities['project-playbooks'],
      withDeclaredAuthority(
        withScope(
          {
            ...unavailableCapability('local_project_playbooks_cloud_authority_unavailable'),
            retryable: true,
          },
          {
            tenant_id: 'local',
            project_id: 'local-project',
            workspace_id: null,
            instance_id: null,
          },
        ),
      ),
    );
    const searchCall = calls.find(({ input }) =>
      input.endsWith('/api/v1/search-enhanced/capabilities'),
    );
    assert.ok(searchCall);
    assert.equal(searchCall.input, 'http://127.0.0.1:4123/api/v1/search-enhanced/capabilities');
    assert.equal(searchCall.init?.headers.get('Authorization'), null);
    assert.equal(searchCall.init?.headers.get('X-Agistack-Launch'), 'launch-capability');
    assert.deepEqual(
      snapshot.capabilities.automation_run,
      withObservedAuthority(
        withScope(unavailableCapability('durable_automation_execution_unavailable', true), {
          tenant_id: 'local',
          project_id: 'local-project',
          workspace_id: null,
          instance_id: null,
        }),
        'sidecar',
      ),
    );
    assert.deepEqual(
      snapshot.capabilities['project-project-cron-jobs'],
      withObservedAuthority(
        withScope(
          withoutAuthorityRevision(
            degradedCapability('automation_actions_restricted', [
              'view',
              'list',
              'view-history',
              'inspect-capabilities',
              'create',
              'update',
              'toggle',
              'delete',
            ]),
          ),
          {
            tenant_id: 'local',
            project_id: 'local-project',
            workspace_id: null,
            instance_id: null,
          },
        ),
        'sidecar',
      ),
    );
    assert.deepEqual(
      snapshot.capabilities['tenant-tenant-tasks'],
      withObservedAuthority(
        {
          availability: 'unavailable',
          reason_code: 'capability_authority_revision_unavailable',
          service_version: '0.1.0',
          contract_version: '3.0.0',
          allowed_actions: [],
          scope: {
            tenant_id: 'local',
            project_id: 'local-project',
            workspace_id: null,
            instance_id: null,
          },
          authority_revision: null,
        },
        'sidecar',
      ),
    );
    assert.deepEqual(
      snapshot.capabilities.sandbox_isolation,
      withDeclaredAuthority(
        withScope(notApplicableCapability('local_isolation_not_applicable'), {
          tenant_id: 'local',
          project_id: 'local-project',
          workspace_id: null,
          instance_id: null,
        }),
      ),
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('local-online snapshot requires observed cloud scope and preserves compound authority', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        service_version: '0.1.0',
        contract_version: '2.0.0',
        mode: 'keyword_degraded',
        reason_code: 'local_embeddings_unavailable',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        projection_revision: 7,
        backfill_cursor: null,
        supported_search_types: ['advanced', 'temporal', 'faceted'],
        unavailable_search_types: ['graph_traversal', 'community'],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );

  try {
    const client = createWorkbenchCapabilityClient(
      {
        getAutomationCapabilities: async () => ({
          ...automationContract,
          durable_execution: false,
        }),
      },
      {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'http://127.0.0.1:4123',
        localApiToken: 'launch-capability',
        mode: 'local',
        tenantId: 'tenant-1',
        projectId: 'project-1',
      },
      {
        cloudRequestBroker: {
          async requestJson(request) {
            assert.equal(request.path, '/api/v1/workspace-context');
            return {
              context: {
                tenant_id: 'tenant-1',
                project_id: 'project-1',
                revision: 41,
              },
              membership_role: 'admin',
            };
          },
          async requestNoContent() {},
        },
      },
    );
    const snapshot = await client.loadSnapshot();

    assert.equal(snapshot.runtime_state, 'local_online');
    assert.deepEqual(snapshot.capabilities['backend-stores'], {
      availability: 'not_applicable',
      reason_code: 'local_backend_stores_cloud_authority_unavailable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: {
        tenant_id: 'tenant-1',
        project_id: null,
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: null,
      retryable: false,
      authority_source: 'cloud_service',
      supporting_authority_sources: [],
      provenance: 'observed',
    });
    assert.deepEqual(snapshot.capabilities['project-playbooks'], {
      availability: 'available',
      reason_code: null,
      service_version: '0.1.0',
      contract_version: '4.0.0',
      allowed_actions: ['view', 'list', 'refresh', 'review-verdicts'],
      scope: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: 41,
      retryable: false,
      authority_source: 'cloud_service',
      supporting_authority_sources: ['sidecar', 'electron'],
      provenance: 'observed',
    });
    assert.equal(snapshot.capabilities.search.authority_source, 'sidecar');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('local Search capability rejects scope drift and cursor/reason mismatches', () => {
  const contract = {
    service_version: '0.1.0',
    contract_version: '2.0.0',
    mode: 'keyword_degraded',
    reason_code: 'local_search_backfill_in_progress',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    projection_revision: 256,
    backfill_cursor: 'timeline_rowid:256',
    supported_search_types: ['advanced', 'temporal', 'faceted'],
    unavailable_search_types: ['graph_traversal', 'community'],
  };
  assert.deepEqual(
    normalizeLocalSearchCapabilityContract(contract, {
      tenantId: 'tenant-1',
      projectId: 'project-1',
    }),
    degradedCapability(
      'local_search_backfill_in_progress',
      ['advanced', 'temporal', 'faceted'],
      256,
    ),
  );
  assert.equal(
    normalizeLocalSearchCapabilityContract(
      { ...contract, project_id: 'project-2' },
      { tenantId: 'tenant-1', projectId: 'project-1' },
    ).reason_code,
    'local_search_capability_contract_invalid',
  );
  assert.equal(
    normalizeLocalSearchCapabilityContract(
      { ...contract, backfill_cursor: null },
      { tenantId: 'tenant-1', projectId: 'project-1' },
    ).reason_code,
    'local_search_capability_contract_invalid',
  );
});

test('legacy capability authorities fail closed before payload inference', async () => {
  assert.deepEqual(
    normalizeSearchCapabilityContract({ search_types: {} }),
    unavailableCapability('capability_contract_version_missing'),
  );
  assert.deepEqual(
    normalizeAutomationCapabilityContract({
      ...automationContract,
      service_version: undefined,
      contract_version: undefined,
      durable_execution: false,
    }),
    unavailableCapability('capability_contract_version_missing'),
  );

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: 'not declared' }), {
      status: 404,
      headers: { 'content-type': 'application/json' },
    });
  try {
    const client = createWorkbenchCapabilityClient(
      {
        getAutomationCapabilities: async () => {
          throw new Error('capability authority unavailable');
        },
      },
      {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'https://api.memstack.test',
        mode: 'cloud',
        projectId: 'project-1',
      },
    );
    const snapshot = await client.loadSnapshot();
    const scope = {
      tenant_id: 'default',
      project_id: 'project-1',
      workspace_id: null,
      instance_id: null,
    };
    assert.deepEqual(
      snapshot.capabilities.search,
      withObservedAuthority(
        withScope(unavailableCapability('search_capability_contract_unavailable'), scope),
        'cloud_service',
      ),
    );
    assert.deepEqual(
      snapshot.capabilities.automation_run,
      withObservedAuthority(
        withScope(unavailableCapability('automation_capability_contract_unavailable'), scope),
        'cloud_service',
      ),
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('capability normalizers reject endpoint and guard drift', () => {
  assert.deepEqual(
    normalizeSearchCapabilityContract({
      ...searchContract,
      search_types: {
        ...searchContract.search_types,
        temporal: {
          ...searchContract.search_types.temporal,
          endpoint: '/api/v1/search-enhanced/renamed',
        },
      },
    }),
    unavailableCapability('search_capability_contract_invalid', true),
  );
  assert.deepEqual(
    normalizeAutomationCapabilityContract(automationContract),
    availableCapability(['run_now']),
  );
  const missingAdvanced = structuredClone(searchContract);
  delete missingAdvanced.search_types.advanced;
  assert.deepEqual(
    normalizeSearchCapabilityContract(missingAdvanced),
    unavailableCapability('search_capability_contract_invalid', true),
  );
});

test('Search capability normalizer rejects incomplete or drifted advanced parameters', () => {
  const missingParameter = structuredClone(searchContract);
  delete missingParameter.search_types.advanced.parameters.since;
  assert.deepEqual(
    normalizeSearchCapabilityContract(missingParameter),
    unavailableCapability('search_capability_contract_invalid', true),
  );

  const driftedParameter = structuredClone(searchContract);
  driftedParameter.search_types.advanced.parameters.limit = 'integer (1-100)';
  assert.deepEqual(
    normalizeSearchCapabilityContract(driftedParameter),
    unavailableCapability('search_capability_contract_invalid', true),
  );
});

test('cloud client loads the scoped degraded Workspace Collaboration authority', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    const url = String(input);
    const payload = url.endsWith('/collaboration/capabilities')
      ? workspaceCollaborationContract
      : url.endsWith('/collaboration/authority')
        ? workspaceCollaborationAuthority
        : searchContract;
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = createWorkbenchCapabilityClient(
      {
        getAutomationCapabilities: async () => automationContract,
      },
      {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'https://api.memstack.test',
        apiKey: 'session-credential',
        mode: 'cloud',
        tenantId: 'tenant / 1',
        projectId: 'project / 1',
        workspaceId: 'workspace / 1',
      },
    );
    const snapshot = await client.loadSnapshot();
    assert.deepEqual(
      snapshot.capabilities.workspace_collaboration,
      withObservedAuthority(
        withScope(
          degradedCapability(
            'workspace_collaboration_mutation_guards_unavailable',
            workspaceReadActions,
            7,
          ),
          {
            tenant_id: 'tenant / 1',
            project_id: 'project / 1',
            workspace_id: 'workspace / 1',
            instance_id: null,
          },
        ),
        'cloud_service',
      ),
    );

    const authorityCall = calls.find(({ input }) => input.endsWith('/collaboration/capabilities'));
    assert.equal(
      authorityCall?.input,
      'https://api.memstack.test/api/v1/tenants/tenant%20%2F%201/projects/' +
        'project%20%2F%201/workspaces/workspace%20%2F%201/collaboration/capabilities',
    );
    assert.equal(authorityCall?.init?.headers.get('Authorization'), 'Bearer session-credential');
    assert.equal(authorityCall?.init?.headers.has('X-Agistack-Launch'), false);

    const revisionCall = calls.find(({ input }) => input.endsWith('/collaboration/authority'));
    assert.equal(
      revisionCall?.input,
      'https://api.memstack.test/api/v1/tenants/tenant%20%2F%201/projects/' +
        'project%20%2F%201/workspaces/workspace%20%2F%201/collaboration/authority',
    );
    assert.equal(revisionCall?.init?.headers.get('Authorization'), 'Bearer session-credential');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Workspace Collaboration capability normalization fails closed on contract drift', () => {
  const scope = {
    tenantId: 'tenant / 1',
    projectId: 'project / 1',
    workspaceId: 'workspace / 1',
  };
  assert.deepEqual(
    normalizeWorkspaceCollaborationCapabilityContract(workspaceCollaborationContract, scope),
    degradedCapability('workspace_collaboration_mutation_guards_unavailable', workspaceReadActions),
  );

  const missingSurface = structuredClone(workspaceCollaborationContract);
  missingSurface.read_surfaces.pop();
  assert.deepEqual(
    normalizeWorkspaceCollaborationCapabilityContract(missingSurface, scope),
    unavailableCapability('workspace_collaboration_capability_contract_invalid', true),
  );

  const unsafeMutationClaim = structuredClone(workspaceCollaborationContract);
  unsafeMutationClaim.mutations.revision_guarded = true;
  assert.deepEqual(
    normalizeWorkspaceCollaborationCapabilityContract(unsafeMutationClaim, scope),
    unavailableCapability('workspace_collaboration_capability_contract_invalid', true),
  );

  assert.deepEqual(
    normalizeWorkspaceCollaborationCapabilityContract(
      { ...workspaceCollaborationContract, workspace_id: 'workspace-other' },
      scope,
    ),
    unavailableCapability('workspace_collaboration_capability_scope_mismatch', true),
  );
  const legacy = structuredClone(workspaceCollaborationContract);
  delete legacy.contract_version;
  assert.deepEqual(
    normalizeWorkspaceCollaborationCapabilityContract(legacy, scope),
    unavailableCapability('capability_contract_version_missing', false, '0.1.0', null),
  );
});

test('Workspace Collaboration authority normalization requires exact scoped revision', () => {
  const scope = {
    tenantId: 'tenant / 1',
    projectId: 'project / 1',
    workspaceId: 'workspace / 1',
  };
  assert.equal(
    normalizeWorkspaceCollaborationAuthorityContract(workspaceCollaborationAuthority, scope),
    7,
  );
  assert.equal(
    normalizeWorkspaceCollaborationAuthorityContract(
      { ...workspaceCollaborationAuthority, workspace_id: 'workspace-other' },
      scope,
    ),
    null,
  );
  assert.equal(
    normalizeWorkspaceCollaborationAuthorityContract(
      { ...workspaceCollaborationAuthority, revision: -1 },
      scope,
    ),
    null,
  );
});

test('Workspace Collaboration 404 remains unavailable while local mode observes Sidecar authority', async () => {
  const originalFetch = globalThis.fetch;
  let capabilityFetchCalls = 0;
  globalThis.fetch = async (input) => {
    if (String(input).includes('/collaboration/capabilities')) {
      capabilityFetchCalls += 1;
      if (String(input).startsWith(DEFAULT_CONFIG.apiBaseUrl)) {
        return new Response(
          JSON.stringify({
            ...workspaceCollaborationContract,
            authority: 'local',
            tenant_id: 'local',
            project_id: 'local-project',
            workspace_id: 'local-workspace',
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      }
      return new Response(JSON.stringify({ detail: 'legacy server' }), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (String(input).includes('/collaboration/authority')) {
      return new Response(
        JSON.stringify({
          ...workspaceCollaborationAuthority,
          tenant_id: 'local',
          project_id: 'local-project',
          workspace_id: 'local-workspace',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    return new Response(JSON.stringify(searchContract), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const cloudClient = createWorkbenchCapabilityClient(
      { getAutomationCapabilities: async () => automationContract },
      {
        ...DEFAULT_CONFIG,
        apiBaseUrl: 'https://api.memstack.test',
        mode: 'cloud',
        tenantId: 'tenant-1',
        projectId: 'project-1',
        workspaceId: 'workspace-1',
      },
    );
    const cloud = await cloudClient.loadSnapshot();
    assert.deepEqual(
      cloud.capabilities.workspace_collaboration,
      withObservedAuthority(
        withScope(
          unavailableCapability('workspace_collaboration_capability_contract_unavailable'),
          {
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            workspace_id: 'workspace-1',
            instance_id: null,
          },
        ),
        'cloud_service',
      ),
    );
    assert.equal(capabilityFetchCalls, 1);

    const localClient = createWorkbenchCapabilityClient(
      { getAutomationCapabilities: async () => automationContract },
      {
        ...DEFAULT_CONFIG,
        mode: 'local',
        tenantId: 'local',
        projectId: 'local-project',
        workspaceId: 'local-workspace',
      },
    );
    const local = await localClient.loadSnapshot();
    assert.deepEqual(
      local.capabilities.workspace_collaboration,
      withObservedAuthority(
        withScope(
          degradedCapability(
            'workspace_collaboration_mutation_guards_unavailable',
            workspaceReadActions,
            7,
          ),
          {
            tenant_id: 'local',
            project_id: 'local-project',
            workspace_id: 'local-workspace',
            instance_id: null,
          },
        ),
        'sidecar',
      ),
    );
    assert.deepEqual(
      local.capabilities['tenant-tenant-pool'],
      withDeclaredAuthority({
        availability: 'not_applicable',
        reason_code: 'cloud_runtime_pool_not_applicable',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: {
          tenant_id: 'local',
          project_id: null,
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: null,
      }),
    );
    assert.deepEqual(
      local.capabilities['tenant-tenant-instances'],
      withObservedAuthority(
        {
          availability: 'unavailable',
          reason_code: 'capability_authority_revision_unavailable',
          service_version: '0.1.0',
          contract_version: '3.0.0',
          allowed_actions: [],
          scope: {
            tenant_id: 'local',
            project_id: null,
            workspace_id: null,
            instance_id: null,
          },
          authority_revision: null,
        },
        'sidecar',
      ),
    );
    assert.deepEqual(
      local.capabilities['tenant-tenant-clusters'],
      withDeclaredAuthority({
        availability: 'not_applicable',
        reason_code: 'cloud_cluster_control_not_applicable',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: {
          tenant_id: 'local',
          project_id: null,
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: null,
      }),
    );
    assert.deepEqual(
      local.capabilities['tenant-tenant-deploy'],
      withObservedAuthority(
        {
          availability: 'not_applicable',
          reason_code: 'cloud_deployment_authority_not_applicable',
          service_version: null,
          contract_version: null,
          allowed_actions: [],
          scope: {
            tenant_id: 'local',
            project_id: null,
            workspace_id: null,
            instance_id: null,
          },
          authority_revision: null,
        },
        'sidecar',
      ),
    );
    assert.equal(capabilityFetchCalls, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('local Electron Workspace Collaboration reports permanent Core cutover outages before HTTP probing', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  let collaborationFetchCalls = 0;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        invoke: async (command) => {
          assert.equal(command, 'workspace_core_status');
          return {
            state: 'failed',
            pid: null,
            apiBaseUrl: null,
            restartAttempts: 4,
            failureReason: 'workspace_core_exited_unexpectedly',
            cutoverState: 'core-unavailable',
          };
        },
      },
    },
  };
  globalThis.fetch = async (input) => {
    if (String(input).includes('/collaboration/')) collaborationFetchCalls += 1;
    return new Response(JSON.stringify(searchContract), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = createWorkbenchCapabilityClient(
      { getAutomationCapabilities: async () => automationContract },
      {
        ...DEFAULT_CONFIG,
        mode: 'local',
        tenantId: 'local',
        projectId: 'local-project',
        workspaceId: 'local-workspace',
      },
    );
    const snapshot = await client.loadSnapshot();
    assert.equal(
      snapshot.capabilities.workspace_collaboration.reason_code,
      'workspace_core_cutover_unavailable',
    );
    assert.equal(collaborationFetchCalls, 0);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

function createWorkbenchCapabilityClient(automationApi, config, options = {}) {
  return createDesktopWorkbenchCapabilityClient(automationApi, config, {
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
    backendStoresOperationsV2: {
      async probeBackendStores({ config }) {
        return config.mode === 'local'
          ? {
              availability: 'not_applicable',
              reasonCode: 'local_backend_stores_cloud_authority_unavailable',
              allowedActions: [],
              authorityRevision: null,
            }
          : {
              availability: 'available',
              reasonCode: null,
              allowedActions: ['view', 'list', 'create', 'update', 'delete', 'test'],
              authorityRevision: 23,
            };
      },
    },
    projectWorkspacesClient: projectWorkspacesClientV2Fixture(),
    tenantAgentBindingsOperationsV2: tenantAgentBindingsOperationsV2Fixture(),

    tenantProjectsOperationsV2: tenantProjectsOperationsV2Fixture(),
    tenantTasksOperationsV2: tenantTasksOperationsV2Fixture(),
    tenantAgentDashboardOperationsV2: tenantAgentDashboardOperationsV2Fixture(),
    tenantAnalyticsOperationsV2: tenantAnalyticsOperationsV2Fixture(),
    ...options,
  });
}
