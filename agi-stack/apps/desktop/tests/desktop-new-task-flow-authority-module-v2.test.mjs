import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const {
  createDesktopRendererDefinitionsV2,
  GenerationManagerV2,
  LoaderV2,
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
} = require('@agistack/plugin-runtime');
const {
  DESKTOP_NEW_TASK_FLOW_AUTHORITY_MODULE_REF_V2,
  DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
  DESKTOP_NEW_TASK_FLOW_AUTHORITY_VERSION_V2,
  DesktopNewTaskFlowAuthorityUnavailableErrorV2,
  applyDesktopNewTaskFlowAuthorityV2,
  createDesktopNewTaskFlowOperationsV2,
  desktopNewTaskFlowAuthorityDefinitionV2,
  withDesktopNewTaskFlowAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopNewTaskFlowAuthorityModuleV2.js');
const { desktopNewThreadCreationAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopNewThreadCreationAuthorityModuleV2.js',
);
const { desktopProjectSearchAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectSearchAuthorityModuleV2.js',
);

const { desktopRuntimePoolAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopRuntimePoolAuthorityModuleV2.js',
);
const { desktopRuntimeClustersAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopRuntimeClustersAuthorityModuleV2.js',
);

const { desktopRuntimeInstancesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopRuntimeInstancesAuthorityModuleV2.js',
);
const { desktopRuntimeDeploymentsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopRuntimeDeploymentsAuthorityModuleV2.js',
);

const { desktopProjectPlaybooksEventsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectPlaybooksEventsAuthorityModuleV2.js',
);
const { desktopBackendStoresAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopBackendStoresAuthorityModuleV2.js',
);
const { desktopDeadLetterQueueAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopDeadLetterQueueAuthorityModuleV2.js',
);
const { desktopInstanceTemplatesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopInstanceTemplatesAuthorityModuleV2.js',
);
const { desktopUnifiedRuntimesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopUnifiedRuntimesAuthorityModuleV2.js',
);
const { desktopTenantEventsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantEventsAuthorityModuleV2.js',
);
const { desktopTenantPatternsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantPatternsAuthorityModuleV2.js',
);
const { desktopTenantDecisionRecordsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantDecisionRecordsAuthorityModuleV2.js',
);
const { desktopTenantSettingsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantSettingsAuthorityModuleV2.js',
);
const { desktopTenantWebhooksAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantWebhooksAuthorityModuleV2.js',
);
const { desktopTenantBillingAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantBillingAuthorityModuleV2.js',
);

const { desktopTenantAuditAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantAuditAuthorityModuleV2.js',
);
const { desktopTenantGovernanceAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantGovernanceAuthorityModuleV2.js',
);
const { desktopTenantAcpAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantAcpAuthorityModuleV2.js',
);
const { desktopTenantEvolutionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantEvolutionAuthorityModuleV2.js',
);
const { desktopTenantGenesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantGenesAuthorityModuleV2.js',
);
const { desktopTenantTemplatesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantTemplatesAuthorityModuleV2.js',
);
const { desktopProjectChannelsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectChannelsAuthorityModuleV2.js',
);
const { desktopUserProfileAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopUserProfileAuthorityModuleV2.js',
);
const { desktopTenantAgentDefinitionsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantAgentDefinitionsAuthorityModuleV2.js',
);
const { desktopTenantPromptTemplatesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantPromptTemplatesAuthorityModuleV2.js',
);
const { desktopTenantProvidersAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantProvidersAuthorityModuleV2.js',
);
const { desktopWorkspaceAgentPolicyAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceAgentPolicyAuthorityModuleV2.js',
);
const { desktopTenantSkillDefinitionsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantSkillDefinitionsAuthorityModuleV2.js',
);
const { desktopTenantSkillPackagesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantSkillPackagesAuthorityModuleV2.js',
);
const { desktopTenantSkillEvolutionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantSkillEvolutionAuthorityModuleV2.js',
);
const { desktopTenantSubAgentDefinitionsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantSubAgentDefinitionsAuthorityModuleV2.js',
);
const { desktopTenantOrganizationSettingsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantOrganizationSettingsAuthorityModuleV2.js',
);
const { desktopTenantTrustAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantTrustAuthorityModuleV2.js',
);
const { desktopSessionArtifactActionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionArtifactActionAuthorityModuleV2.js',
);
const { desktopSessionRunControlAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionRunControlAuthorityModuleV2.js',
);
const { desktopArtifactContentAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopArtifactContentAuthorityModuleV2.js',
);
const { desktopAutomationAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopAutomationAuthorityModuleV2.js',
);
const { desktopConversationConfigAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationConfigAuthorityModuleV2.js',
);
const { desktopConversationLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js',
);
const { desktopHitlResponseAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopHitlResponseAuthorityModuleV2.js',
);
const { desktopMyWorkAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopMyWorkAuthorityModuleV2.js',
);
const {
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js');
const { desktopSessionProjectionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionProjectionAuthorityModuleV2.js',
);
const { desktopSessionRunChangesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionRunChangesAuthorityModuleV2.js',
);
const { desktopSessionTimelineAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopSessionTimelineAuthorityModuleV2.js',
);
const { desktopTenantAnalyticsAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantAnalyticsAuthorityModuleV2.js',
);
const { desktopTenantCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantCatalogAuthorityModuleV2.js',
);
const { desktopTenantOverviewAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTenantOverviewAuthorityModuleV2.js',
);
const { desktopTerminalLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopTerminalLifecycleAuthorityModuleV2.js',
);
const { desktopWorkspaceCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceCatalogAuthorityModuleV2.js',
);
const { desktopWorkspaceContextAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceContextAuthorityModuleV2.js',
);
const { desktopWorkspaceAgentBindingAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceAgentBindingAuthorityModuleV2.js',
);
const { desktopWorkspaceAutonomyAttentionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceAutonomyAttentionAuthorityModuleV2.js',
);
const { desktopWorkspaceMemberMutationAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceMemberMutationAuthorityModuleV2.js',
);
const { desktopWorkspaceConversationCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceConversationCatalogAuthorityModuleV2.js',
);
const { desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceExecutionSnapshotAuthorityModuleV2.js',
);
const { desktopWorkspaceMessageCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopWorkspaceMessageCatalogAuthorityModuleV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

const REPOSITORY_ROOT = new URL('../../../../', import.meta.url);
const BOOTSTRAP_PATH = new URL(
  'shared/profiles/memstack-default-bootstrap.v2.json',
  REPOSITORY_ROOT,
);
const MANIFEST_PATH = new URL(
  'config/plugin-manifests-v2/memstack-renderer-target-hosts.v2.json',
  REPOSITORY_ROOT,
);
const PROFILE_PATH = new URL(
  'config/plugin-profiles/memstack-production-target-hosts.v2.yaml',
  REPOSITORY_ROOT,
);

function loadBootstrap() {
  return JSON.parse(readFileSync(BOOTSTRAP_PATH, 'utf8'));
}

function rendererDefinitions() {
  return [
    ...createDesktopRendererDefinitionsV2(),
    require(COMPILED_ROOT + '/src/plugins/desktopProjectBlackboardAuthorityModuleV2.js')
      .desktopProjectBlackboardAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopSessionRunInputAuthorityModuleV2.js')
      .desktopSessionRunInputAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectAgentDashboardAuthorityModuleV2.js')
      .desktopProjectAgentDashboardAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectAgentLogsAuthorityModuleV2.js')
      .desktopProjectAgentLogsAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectAgentPatternsAuthorityModuleV2.js')
      .desktopProjectAgentPatternsAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectEntitiesAuthorityModuleV2.js')
      .desktopProjectEntitiesAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectCommunitiesAuthorityModuleV2.js')
      .desktopProjectCommunitiesAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectMemoriesAuthorityModuleV2.js')
      .desktopProjectMemoriesAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectTeamAuthorityModuleV2.js')
      .desktopProjectTeamAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectSchemaAuthorityModuleV2.js')
      .desktopProjectSchemaAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectMaintenanceAuthorityModuleV2.js')
      .desktopProjectMaintenanceAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectSettingsAuthorityModuleV2.js')
      .desktopProjectSettingsAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopTenantCreationAuthorityModuleV2.js')
      .desktopTenantCreationAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectSupportAuthorityModuleV2.js')
      .desktopProjectSupportAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectPlaybooksReadAuthorityModuleV2.js')
      .desktopProjectPlaybooksReadAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectGraphAuthorityModuleV2.js')
      .desktopProjectGraphAuthorityDefinitionV2,
    desktopArtifactContentAuthorityDefinitionV2,
    desktopAutomationAuthorityDefinitionV2,
    desktopPluginMarketplaceCatalogDefinitionV2,
    desktopPluginMarketplaceManagementDefinitionV2,
    desktopConversationConfigAuthorityDefinitionV2,
    desktopConversationLifecycleAuthorityDefinitionV2,
    desktopHitlResponseAuthorityDefinitionV2,
    desktopMyWorkAuthorityDefinitionV2,
    desktopNewTaskFlowAuthorityDefinitionV2,
    desktopNewThreadCreationAuthorityDefinitionV2,
    desktopProjectSearchAuthorityDefinitionV2,
    desktopRuntimePoolAuthorityDefinitionV2,
    desktopRuntimeClustersAuthorityDefinitionV2,
    desktopRuntimeInstancesAuthorityDefinitionV2,
    desktopRuntimeDeploymentsAuthorityDefinitionV2,
    desktopProjectPlaybooksEventsAuthorityDefinitionV2,
    desktopBackendStoresAuthorityDefinitionV2,
    desktopDeadLetterQueueAuthorityDefinitionV2,
    desktopInstanceTemplatesAuthorityDefinitionV2,
    desktopUnifiedRuntimesAuthorityDefinitionV2,
    desktopTenantEventsAuthorityDefinitionV2,
    desktopTenantPatternsAuthorityDefinitionV2,
    desktopTenantDecisionRecordsAuthorityDefinitionV2,
    desktopTenantSettingsAuthorityDefinitionV2,
    desktopTenantWebhooksAuthorityDefinitionV2,
    desktopTenantBillingAuthorityDefinitionV2,
    desktopTenantAuditAuthorityDefinitionV2,
    desktopTenantGovernanceAuthorityDefinitionV2,
    desktopTenantAcpAuthorityDefinitionV2,
    desktopTenantEvolutionAuthorityDefinitionV2,
  desktopTenantGenesAuthorityDefinitionV2,
  desktopTenantTemplatesAuthorityDefinitionV2,
  desktopProjectChannelsAuthorityDefinitionV2,
    desktopUserProfileAuthorityDefinitionV2,
    desktopTenantAgentDefinitionsAuthorityDefinitionV2,
    desktopTenantPromptTemplatesAuthorityDefinitionV2,
    desktopTenantSubAgentDefinitionsAuthorityDefinitionV2,
    desktopTenantSkillDefinitionsAuthorityDefinitionV2,
    desktopTenantProvidersAuthorityDefinitionV2,
    desktopWorkspaceAgentPolicyAuthorityDefinitionV2,
    desktopTenantSkillPackagesAuthorityDefinitionV2,
    desktopTenantSkillEvolutionAuthorityDefinitionV2,
  desktopTenantOrganizationSettingsAuthorityDefinitionV2,
    desktopTenantTrustAuthorityDefinitionV2,
    desktopSessionArtifactActionAuthorityDefinitionV2,
    desktopSessionRunControlAuthorityDefinitionV2,
    desktopSessionProjectionAuthorityDefinitionV2,
    desktopSessionRunChangesAuthorityDefinitionV2,
    desktopSessionTimelineAuthorityDefinitionV2,
    desktopTerminalLifecycleAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopTenantAgentBindingsAuthorityModuleV2.js')
      .desktopTenantAgentBindingsAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopTenantProjectsAuthorityModuleV2.js')
      .desktopTenantProjectsAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopTenantTasksAuthorityModuleV2.js')
      .desktopTenantTasksAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopProjectOverviewAuthorityModuleV2.js')
      .desktopProjectOverviewAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopTenantAgentDashboardAuthorityModuleV2.js')
      .desktopTenantAgentDashboardAuthorityDefinitionV2,
    desktopTenantAnalyticsAuthorityDefinitionV2,
    desktopTenantCatalogAuthorityDefinitionV2,
    desktopTenantOverviewAuthorityDefinitionV2,
    desktopWorkspaceContextAuthorityDefinitionV2,
    desktopWorkspaceCatalogAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceLifecycleAuthorityModuleV2.js')
      .desktopWorkspaceLifecycleAuthorityDefinitionV2,
    require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceRosterAuthorityModuleV2.js')
      .desktopWorkspaceRosterAuthorityDefinitionV2,
    desktopWorkspaceAgentBindingAuthorityDefinitionV2,
    desktopWorkspaceAutonomyAttentionAuthorityDefinitionV2,
    desktopWorkspaceMemberMutationAuthorityDefinitionV2,
    desktopWorkspaceConversationCatalogAuthorityDefinitionV2,
    desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2,
    desktopWorkspaceMessageCatalogAuthorityDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46551',
    apiKey: 'new-task-session',
    localApiToken: 'new-task-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function workspace(overrides = {}) {
  return {
    id: 'workspace-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    name: 'Review task',
    is_archived: false,
    ...overrides,
  };
}

function conversation(overrides = {}) {
  return {
    id: 'conversation-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: 'workspace-1',
    user_id: 'user-1',
    title: 'Review task',
    status: 'active',
    message_count: 1,
    created_at: '2026-09-02T00:00:00Z',
    conversation_mode: 'workspace',
    current_mode: 'plan',
    agent_config: { selected_agent_id: 'builtin:all-access', capability_mode: 'work' },
    ...overrides,
  };
}

function message(overrides = {}) {
  return {
    id: 'message-1',
    workspace_id: 'workspace-1',
    sender_id: 'user-1',
    sender_type: 'human',
    content: 'Prepare the plan',
    mentions: [],
    parent_message_id: null,
    metadata: { source: 'task_session', conversation_id: 'conversation-1' },
    created_at: '2026-09-02T00:00:00Z',
    ...overrides,
  };
}

function planVersion(overrides = {}) {
  return {
    id: 'plan-1',
    conversation_id: 'conversation-1',
    version: 1,
    status: 'draft',
    tasks: [],
    created_at: '2026-09-02T00:00:00Z',
    ...overrides,
  };
}

function run(overrides = {}) {
  return {
    id: 'run-1',
    conversation_id: 'conversation-1',
    project_id: 'project-1',
    plan_version_id: 'plan-1',
    idempotency_key: 'approval-key-1',
    message_id: 'message-1',
    request_message: 'Start the plan',
    status: 'queued',
    revision: 1,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:00:00Z',
    authorization_snapshot: {},
    ...overrides,
  };
}

function taskSessionRequest(overrides = {}) {
  return {
    idempotency_key: 'desktop-task-session-1',
    workspace: { kind: 'existing', workspace_id: 'workspace-1' },
    conversation: { title: 'Review task', capability_mode: 'work' },
    initial_message: { content: 'Prepare the plan', context_items: [] },
    ...overrides,
  };
}

function approvalRequest(overrides = {}) {
  return {
    conversationId: 'conversation-1',
    projectId: 'project-1',
    planVersionId: 'plan-1',
    expectedPlanVersion: 1,
    permissionProfile: 'workspace_write',
    message: 'Start the plan',
    messageId: 'message-1',
    idempotencyKey: 'approval-key-1',
    environmentKind: 'worktree',
    ...overrides,
  };
}

function responses() {
  return {
    workspaces: [workspace()],
    taskSession: {
      replayed: false,
      workspace: workspace(),
      conversation: conversation(),
      initial_message: message(),
    },
    sentMessage: message(),
    timeline: {
      conversationId: 'conversation-1',
      timeline: [],
      total: 0,
      has_more: false,
    },
    planTasks: {
      conversation_id: 'conversation-1',
      tasks: [],
      total_count: 0,
      plan_version: planVersion(),
    },
    mode: { conversation_id: 'conversation-1', mode: 'build' },
    approval: {
      queued: true,
      created: true,
      conversation: conversation({ current_mode: 'build' }),
      plan_version: planVersion({ status: 'approved' }),
      run: run(),
    },
  };
}

function serviceFixture(received = [], result = responses()) {
  return Object.freeze({
    bindOperation(config) {
      received.push({ kind: 'bind', config });
      return Object.freeze({
        async listWorkspaces(signal) {
          received.push({ kind: 'listWorkspaces', signal });
          return result.workspaces;
        },
        async supportsAgentPlanWorkflow(signal) {
          received.push({ kind: 'supportsAgentPlanWorkflow', signal });
          return true;
        },
        async createTaskSession(input) {
          received.push({ kind: 'createTaskSession', input });
          return result.taskSession;
        },
        async sendMessage(content, parentMessageId, contextItems, mentions) {
          received.push({ kind: 'sendMessage', content, parentMessageId, contextItems, mentions });
          return result.sentMessage;
        },
        async getConversationMessages(conversationId, projectId, options) {
          received.push({ kind: 'getConversationMessages', conversationId, projectId, options });
          return result.timeline;
        },
        async listAgentPlanTasks(conversationId, signal) {
          received.push({ kind: 'listAgentPlanTasks', conversationId, signal });
          return result.planTasks;
        },
        async switchPlanMode(conversationId, mode) {
          received.push({ kind: 'switchPlanMode', conversationId, mode });
          return result.mode;
        },
        async approvePlanAndStart(input) {
          received.push({ kind: 'approvePlanAndStart', input });
          return result.approval;
        },
      });
    },
  });
}

function acceptedActions(service, digest, lifecycle = []) {
  return {
    acquireServiceOperationLease: async (request) => {
      lifecycle.push({ type: 'acquire', digest, request });
      let released = false;
      return {
        status: 'accepted',
        digest,
        useService(operation) {
          if (released) throw new Error('lease_released');
          return operation(service);
        },
        async release() {
          if (released) return;
          released = true;
          lifecycle.push({ type: 'release', digest });
        },
      };
    },
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

test('generated contract exposes one credential-free root new-task-flow Provider', () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const profile = readFileSync(PROFILE_PATH, 'utf8');
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_NEW_TASK_FLOW_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) => moduleRef === DESKTOP_NEW_TASK_FLOW_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-new-task-flow-authority',
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ['desktop-renderer']);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
        version: DESKTOP_NEW_TASK_FLOW_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ['strategy']);
  assert.equal(module.contract.config_schema.properties.strategy.const, 'desktop-api-client');
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(module.contract_digest, desktopNewTaskFlowAuthorityDefinitionV2.contractDigest);
  assert.equal(catalog.entrypoint, 'applyDesktopNewTaskFlowAuthorityV2');
  assert.equal(
    catalog.artifact_source,
    'repo+typescript://agi-stack/apps/desktop/src/plugins/' +
      'desktopNewTaskFlowAuthorityModuleV2.ts',
  );
  assert.equal(entry.module_ref, DESKTOP_NEW_TASK_FLOW_AUTHORITY_MODULE_REF_V2);
  assert.equal(entry.parent_entry_id, 'builtin-desktop-renderer-host');
  assert.deepEqual(entry.scope, { kind: 'root' });
  assert.deepEqual(entry.config, { strategy: 'desktop-api-client' });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(profile, /entry_id: builtin-desktop-new-task-flow-authority/u);
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(JSON.stringify(value), /apiKey|localApiToken|Authorization/iu);
  }
});

test('Loader activates the exact service and Profile disable removes it without fallback', async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), 'desktop-renderer');
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
    { kind: 'root' },
    { version: DESKTOP_NEW_TASK_FLOW_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ['bindOperation']);
  assert.equal('config' in service, false);
  assert.equal('client' in service, false);
  assert.throws(
    () =>
      applyDesktopNewTaskFlowAuthorityV2(
        { provide: () => assert.fail('invalid config must not provide a service') },
        { strategy: 'legacy-client' },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_new_task_flow_authority_config_invalid',
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-new-task-flow-authority',
  ).enabled = false;
  disabled.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-new-thread-creation-authority',
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
        { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
        { version: DESKTOP_NEW_TASK_FLOW_AUTHORITY_VERSION_V2 },
      ),
    (error) => error instanceof RuntimeV2Error && error.code === 'missing_service',
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_NEW_TASK_FLOW_AUTHORITY_MODULE_REF_V2
        ? { ...definition, contractDigest: 'sha256:' + '0'.repeat(64) }
        : definition,
    ),
    'desktop-renderer',
  );
  await assert.rejects(
    wrongDefinitionLoader.stage(bootstrap),
    (error) => error instanceof RuntimeV2Error && error.code === 'contract_digest_mismatch',
  );
  assert.equal(manager.current, generation);
  await disabledGeneration.dispose();
  await manager.close();
});

test('local service owns all eight authenticated transport contracts', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const result = responses();
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input));
    calls.push({ url, init });
    if (url.pathname.endsWith('/workspaces')) return json(result.workspaces);
    if (url.pathname.endsWith('/task-sessions/capabilities')) {
      return json({
        schema_version: 2,
        atomic_creation: true,
        initial_conversation_mode: 'workspace',
        initial_plan_mode: 'plan',
      });
    }
    if (url.pathname.endsWith('/task-sessions')) return json(result.taskSession);
    if (url.pathname.endsWith('/workspaces/workspace-1/messages')) {
      return json(result.sentMessage);
    }
    if (url.pathname.endsWith('/conversations/conversation-1/messages')) {
      return json(result.timeline);
    }
    if (url.pathname.endsWith('/plan/tasks/conversation-1')) return json(result.planTasks);
    if (url.pathname.endsWith('/plan/mode')) return json(result.mode);
    if (url.pathname.endsWith('/plans/approve-and-start')) return json(result.approval);
    return json({ detail: `unexpected route ${url.pathname}` }, 404);
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_NEW_TASK_FLOW_AUTHORITY_VERSION_V2 },
    );
    const client = service.bindOperation(runtimeConfig());

    assert.deepEqual(await client.listWorkspaces(), result.workspaces);
    assert.equal(await client.supportsAgentPlanWorkflow(), true);
    assert.deepEqual(await client.createTaskSession(taskSessionRequest()), result.taskSession);
    assert.deepEqual(await client.sendMessage('Prepare the plan'), result.sentMessage);
    assert.deepEqual(
      await client.getConversationMessages('conversation-1', 'project-1'),
      result.timeline,
    );
    assert.deepEqual(await client.listAgentPlanTasks('conversation-1'), result.planTasks);
    assert.deepEqual(await client.switchPlanMode('conversation-1', 'build'), result.mode);
    assert.deepEqual(await client.approvePlanAndStart(approvalRequest()), result.approval);
    assert.equal(calls.length, 8);
    for (const call of calls) {
      const headers = new Headers(call.init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer new-task-session');
      assert.equal(headers.get('X-Agistack-Launch'), 'new-task-launch');
    }
    assert.deepEqual(
      calls.map(({ url, init }) => [url.pathname, init.method ?? 'GET']),
      [
        ['/api/v1/tenants/tenant-1/projects/project-1/workspaces', 'GET'],
        ['/api/v1/tenants/tenant-1/projects/project-1/task-sessions/capabilities', 'GET'],
        ['/api/v1/tenants/tenant-1/projects/project-1/task-sessions', 'POST'],
        ['/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/messages', 'POST'],
        ['/api/v1/agent/conversations/conversation-1/messages', 'GET'],
        ['/api/v1/agent/plan/tasks/conversation-1', 'GET'],
        ['/api/v1/agent/plan/mode', 'POST'],
        ['/api/v1/agent/plans/approve-and-start', 'POST'],
      ],
    );
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Cloud service uses the vault broker without exposing credentials', async () => {
  const originalWindow = globalThis.window;
  const calls = [];
  const result = responses();
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          calls.push({ command, args });
          return {
            status: 200,
            body: args.request.path.endsWith('/capabilities')
              ? {
                  schema_version: 2,
                  atomic_creation: true,
                  initial_conversation_mode: 'workspace',
                  initial_plan_mode: 'plan',
                }
              : result.approval,
          };
        },
      },
    },
  };

  try {
    const generation = await new LoaderV2(rendererDefinitions(), 'desktop-renderer').stage(
      loadBootstrap(),
    );
    const service = generation.resolve(
      DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
      { kind: 'root' },
      { version: DESKTOP_NEW_TASK_FLOW_AUTHORITY_VERSION_V2 },
    );
    const client = service.bindOperation(
      runtimeConfig({ mode: 'cloud', apiKey: '', localApiToken: '' }),
    );

    assert.equal(await client.supportsAgentPlanWorkflow(), true);
    assert.deepEqual(await client.approvePlanAndStart(approvalRequest()), result.approval);
    assert.deepEqual(
      calls.map(({ command }) => command),
      ['cloud_request', 'cloud_request'],
    );
    assert.deepEqual(calls[1].args.request, {
      path: '/api/v1/agent/plans/approve-and-start',
      method: 'POST',
      body: {
        conversation_id: 'conversation-1',
        project_id: 'project-1',
        plan_version_id: 'plan-1',
        expected_plan_version: 1,
        permission_profile: 'workspace_write',
        message: 'Start the plan',
        message_id: 'message-1',
        idempotency_key: 'approval-key-1',
        environment: { kind: 'worktree' },
      },
    });
    assert.equal(JSON.stringify(calls).includes('new-task-session'), false);
    assert.equal(JSON.stringify(calls).includes('new-task-launch'), false);
    await generation.dispose();
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('every client call freezes inputs before one exact project or session lease', async () => {
  const lifecycle = [];
  const received = [];
  const service = serviceFixture(received);
  const actions = acceptedActions(service, 'sha256:generation-1', lifecycle);
  const config = runtimeConfig();
  const operations = createDesktopNewTaskFlowOperationsV2(() => actions);
  const client = operations.bindOperation(config);
  const controller = new AbortController();
  const request = taskSessionRequest();
  const contexts = [{ kind: 'attachment', resource_id: 'artifact-1', label: 'Brief' }];
  const mentions = ['agent-1'];
  const approval = approvalRequest();

  const pending = [
    client.listWorkspaces(controller.signal),
    client.supportsAgentPlanWorkflow(controller.signal),
    client.createTaskSession(request),
    client.sendMessage('Prepare the plan', undefined, contexts, mentions),
    client.getConversationMessages('conversation-1', 'project-1', {
      limit: 20,
      signal: controller.signal,
    }),
    client.listAgentPlanTasks('conversation-1', controller.signal),
    client.switchPlanMode('conversation-1', 'build'),
    client.approvePlanAndStart(approval),
  ];
  config.tenantId = 'mutated-tenant';
  config.projectId = 'mutated-project';
  request.initial_message.content = 'mutated';
  contexts[0].label = 'mutated';
  mentions[0] = 'mutated-agent';
  approval.message = 'mutated';
  await Promise.all(pending);

  assert.equal(Object.isFrozen(operations), true);
  assert.equal(Object.isFrozen(client), true);
  const bindings = received.filter(({ kind }) => kind === 'bind');
  assert.equal(bindings.length, 8);
  for (const binding of bindings) {
    assert.equal(Object.isFrozen(binding.config), true);
    assert.equal(binding.config.tenantId, 'tenant-1');
    assert.equal(binding.config.projectId, 'project-1');
  }
  assert.equal(
    received.find(({ kind }) => kind === 'createTaskSession').input.initial_message.content,
    'Prepare the plan',
  );
  assert.equal(received.find(({ kind }) => kind === 'sendMessage').contextItems[0].label, 'Brief');
  assert.deepEqual(received.find(({ kind }) => kind === 'sendMessage').mentions, ['agent-1']);
  assert.equal(
    received.find(({ kind }) => kind === 'approvePlanAndStart').input.message,
    'Start the plan',
  );
  assert.deepEqual(
    lifecycle.filter(({ type }) => type === 'acquire').map(({ request: lease }) => lease.scope),
    [
      { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
      { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
      { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
      { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
      {
        kind: 'session',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        session_id: 'conversation-1',
      },
      {
        kind: 'session',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        session_id: 'conversation-1',
      },
      {
        kind: 'session',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        session_id: 'conversation-1',
      },
      {
        kind: 'session',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        session_id: 'conversation-1',
      },
    ],
  );
  assert.equal(lifecycle.filter(({ type }) => type === 'release').length, 8);
});

test('malformed scope, request and response fail closed at the V2 operation boundary', async () => {
  let acquisitions = 0;
  const neverActions = {
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  };
  let config = runtimeConfig({ tenantId: '' });
  const invalidClient = createDesktopNewTaskFlowOperationsV2(() => neverActions).bindOperation(
    config,
  );
  await assert.rejects(
    invalidClient.listWorkspaces(),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_new_task_flow_input_invalid',
  );
  config = runtimeConfig();
  const client = createDesktopNewTaskFlowOperationsV2(() => neverActions).bindOperation(config);
  await assert.rejects(
    client.switchPlanMode(' ', 'build'),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_new_task_flow_input_invalid',
  );
  await assert.rejects(
    client.approvePlanAndStart(approvalRequest({ projectId: 'other-project' })),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_new_task_flow_scope_mismatch',
  );
  assert.equal(acquisitions, 0);

  const malformed = responses();
  malformed.timeline = { ...malformed.timeline, conversationId: 'other-conversation' };
  const malformedClient = createDesktopNewTaskFlowOperationsV2(() =>
    acceptedActions(serviceFixture([], malformed), 'sha256:malformed'),
  ).bindOperation(runtimeConfig());
  await assert.rejects(
    malformedClient.getConversationMessages('conversation-1'),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_new_task_flow_response_invalid',
  );
});

test('missing generation service is structured and an escaped authority is revoked', async () => {
  const unavailable = createDesktopNewTaskFlowOperationsV2(() => null).bindOperation(
    runtimeConfig(),
  );
  await assert.rejects(
    unavailable.listWorkspaces(),
    (error) =>
      error instanceof DesktopNewTaskFlowAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );

  const rejected = createDesktopNewTaskFlowOperationsV2(() => ({
    acquireServiceOperationLease: async () => ({
      status: 'rejected',
      reasonCode: 'desktop_renderer_service_resolve_failed',
      runtimeCode: 'missing_service',
    }),
  })).bindOperation(runtimeConfig());
  await assert.rejects(
    rejected.listWorkspaces(),
    (error) =>
      error instanceof DesktopNewTaskFlowAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_resolve_failed' &&
      error.runtimeCode === 'missing_service',
  );

  let escaped;
  await withDesktopNewTaskFlowAuthorityOperationV2(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
    { kind: 'list-workspaces', config: runtimeConfig() },
    (authority) => {
      escaped = authority;
      return 'complete';
    },
  );
  assert.throws(
    () => escaped.listWorkspaces(),
    (error) =>
      error instanceof RuntimeV2Error && error.code === 'desktop_new_task_flow_operation_released',
  );
});

test('operation failure outranks release failure and successful release failure propagates', async () => {
  let failOperation = true;
  const service = {
    bindOperation() {
      const authority = serviceFixture().bindOperation(runtimeConfig());
      return {
        ...authority,
        listWorkspaces: async () => {
          if (failOperation) throw new Error('new_task_operation_failed');
          return [workspace()];
        },
      };
    },
  };
  const actions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) => operation(service),
      release: async () => {
        throw new Error('new_task_release_failed');
      },
    }),
  };
  const client = createDesktopNewTaskFlowOperationsV2(() => actions).bindOperation(runtimeConfig());

  await assert.rejects(client.listWorkspaces(), /new_task_operation_failed/u);
  failOperation = false;
  await assert.rejects(client.listWorkspaces(), /new_task_release_failed/u);
});

test('HMR pins an in-flight new-task operation and sends the next call to the new generation', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const oldService = {
    bindOperation() {
      return {
        ...serviceFixture().bindOperation(runtimeConfig()),
        listWorkspaces: async () => oldResponse,
      };
    },
  };
  const newResponses = responses();
  newResponses.workspaces = [workspace({ id: 'workspace-new' })];
  const newService = serviceFixture([], newResponses);
  let actions = acceptedActions(oldService, 'sha256:old', lifecycle);
  const client = createDesktopNewTaskFlowOperationsV2(() => actions).bindOperation(runtimeConfig());
  const oldPending = client.listWorkspaces();
  actions = acceptedActions(newService, 'sha256:new', lifecycle);
  const next = await client.listWorkspaces();
  resolveOld([workspace({ id: 'workspace-old' })]);
  const old = await oldPending;

  assert.equal(next[0].id, 'workspace-new');
  assert.equal(old[0].id, 'workspace-old');
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    ['acquire:sha256:old', 'acquire:sha256:new', 'release:sha256:new', 'release:sha256:old'],
  );
});
