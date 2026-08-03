import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopAutomationApi } from '../automations/automationClient';
import {
  automationActionAvailability,
  normalizeAutomationCapabilities,
} from '../automations/automationModel';
import { deviceApprovalCapability } from '../device-approval/deviceApprovalCapability';
import { tenantCreationCapability } from '../tenant-creation/tenantCreationCapability';
import { invitationAcceptanceCapability } from '../invitation-acceptance/invitationAcceptanceCapability';
import { deadLetterQueueCapability } from '../governance/deadLetterQueueCapability';
import { instanceTemplatesCapability } from '../instance-templates/instanceTemplatesCapability';
import { runtimeClustersCapability } from '../runtime-clusters/runtimeClustersCapability';
import { runtimeDeploymentsCapability } from '../runtime-deployments/runtimeDeploymentsCapability';
import { runtimeInstancesCapability } from '../runtime-instances/runtimeInstancesCapability';
import { runtimePoolCapability } from '../runtime-pool/runtimePoolCapability';
import { unifiedRuntimesCapability } from '../unified-runtimes/unifiedRuntimesCapability';
import { createCloudProjectOverviewClient } from '../project/projectOverviewCloudClient';
import { createLocalProjectOverviewClient } from '../project/projectOverviewLocalClient';
import { projectSupportCapability } from '../project-support/projectSupportCapability';
import { loadTenantAnalyticsCapability } from '../tenant/tenantAnalyticsCapability';
import { loadTenantAgentDashboardCapability } from '../tenant/tenantAgentDashboardCapability';
import { loadTenantAgentBindingsCapability } from '../tenant/tenantAgentBindingsCapability';
import { loadTenantOverviewCapability } from '../tenant/tenantOverviewCapability';
import { loadTenantProjectsCapability } from '../tenant/tenantProjectsCapability';
import { tenantTasksCapability } from '../tenant/tenantTasksCapability';
import { WORKSPACE_HTTP_MUTATION_ACTIONS } from '../workspace/workspaceCollaborationHttpMutations';
import type { DesktopRuntimeConfig } from '../../types';
import {
  DESKTOP_CAPABILITY_SNAPSHOT_VERSION,
  DESKTOP_MINIMUM_CONTRACT_VERSION,
  parseDesktopCapabilitySnapshot,
  type DesktopCapabilityAvailability,
  type DesktopCapabilityScope,
  type DesktopCapabilitySnapshot,
} from './capabilitySnapshot';
import {
  negotiateCapabilityContract,
  type CapabilityContractNegotiation,
} from './capabilityVersion';

export type DesktopWorkbenchCapabilityClient = {
  loadSnapshot(signal?: AbortSignal): Promise<DesktopCapabilitySnapshot>;
};

type AutomationCapabilityAuthority = Pick<
  DesktopAutomationApi,
  'getAutomationCapabilities'
>;

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
): DesktopWorkbenchCapabilityClient {
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
      ]);
      const projectScope = projectCapabilityScope(config);
      const workspaceScope = workspaceCapabilityScope(config);
      const rawSnapshot = {
        version: DESKTOP_CAPABILITY_SNAPSHOT_VERSION,
        mode: config.mode,
        capabilities: {
          automation_run: withCapabilityScope(
            automationCapabilities.run,
            projectScope,
          ),
          'project-project-cron-jobs': withCapabilityScope(
            automationCapabilities.cronJobs,
            projectScope,
          ),
          search: withCapabilityScope(search, projectScope),
          workspace_collaboration: withCapabilityScope(
            workspaceCollaboration,
            workspaceScope,
          ),
          sandbox_isolation:
            config.mode === 'local'
              ? withCapabilityScope(
                  notApplicable('local_isolation_not_applicable'),
                  workspaceScope,
                )
              : withCapabilityScope(
                  unavailable('sandbox_isolation_capability_not_declared'),
                  workspaceScope,
                ),
          'device-approval': deviceApprovalCapability(config),
          'tenant-creation': tenantCreationCapability(config),
          'invitation-acceptance': invitationAcceptanceCapability(config),
          'project-project-overview': withCapabilityScope(
            projectOverview,
            projectScope,
          ),
          'project-project-search': withCapabilityScope(
            search,
            projectScope,
          ),
          'project-support': projectSupportCapability(config),
          'tenant-tenant-overview': tenantOverview,
          'tenant-tenant-analytics': tenantAnalytics,
          'tenant-tenant-agent-configuration': tenantAgentDashboard,
          'tenant-tenant-agent-bindings': tenantAgentBindings,
          'tenant-tenant-projects': tenantProjects,
          'tenant-tenant-tasks': tenantTasksCapability(config),
          'tenant-tenant-runtimes': unifiedRuntimesCapability(config),
          'tenant-tenant-pool': runtimePoolCapability(config),
          'tenant-tenant-instances': runtimeInstancesCapability(config),
          'tenant-tenant-clusters': runtimeClustersCapability(config),
          'tenant-tenant-deploy': runtimeDeploymentsCapability(config),
          'tenant-tenant-instance-templates':
            instanceTemplatesCapability(config),
          'tenant-tenant-dead-letter-queue': deadLetterQueueCapability(config),
        },
      };
      const snapshot = parseDesktopCapabilitySnapshot(rawSnapshot);
      if (!snapshot) throw new Error('desktop capability snapshot is invalid');
      return snapshot;
    },
  };
}

export function normalizeSearchCapabilityContract(
  input: unknown,
): DesktopCapabilityAvailability {
  const negotiation = negotiateCapabilityContract(
    input,
    DESKTOP_MINIMUM_CONTRACT_VERSION,
  );
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
      'search_types',
      'filters',
    ]) ||
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
  const negotiation = negotiateCapabilityContract(
    input,
    DESKTOP_MINIMUM_CONTRACT_VERSION,
  );
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
    !matchesExactStringArray(
      input.supported_search_types,
      LOCAL_SEARCH_SUPPORTED_TYPES,
    ) ||
    !matchesExactStringArray(
      input.unavailable_search_types,
      LOCAL_SEARCH_UNAVAILABLE_TYPES,
    )
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
  const negotiation = negotiateCapabilityContract(
    input,
    DESKTOP_MINIMUM_CONTRACT_VERSION,
  );
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
  const negotiation = negotiateCapabilityContract(
    input,
    DESKTOP_MINIMUM_CONTRACT_VERSION,
  );
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

  const allowedActions = [
    'view',
    'list',
    'view-history',
    'inspect-capabilities',
  ];
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
  const negotiation = negotiateCapabilityContract(
    input,
    DESKTOP_MINIMUM_CONTRACT_VERSION,
  );
  if (!negotiation.compatible) {
    return unavailable(
      negotiation.reason_code ?? 'capability_contract_version_invalid',
      negotiation,
    );
  }
  if (!isRecord(input)) {
    return unavailable(
      'workspace_collaboration_capability_contract_invalid',
      negotiation,
    );
  }
  if (
    input.authority !== 'cloud' ||
    input.canonical_read !== true ||
    !matchesExactStringArray(
      input.read_surfaces,
      WORKSPACE_COLLABORATION_READ_SURFACES,
    ) ||
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
      allowedActions: flattenWorkspaceMutationActions(input.mutations.actions),
    });
  }
  if (
    !isExactRecord(input, capabilityKeys) ||
    input.status !== 'degraded' ||
    input.reason_code !== WORKSPACE_COLLABORATION_DEGRADED_REASON ||
    !isExactRecord(input.mutations, [
      'allowed',
      'revision_guarded',
      'idempotency_guarded',
    ]) ||
    input.mutations.allowed !== false ||
    input.mutations.revision_guarded !== false ||
    input.mutations.idempotency_guarded !== false
  ) {
    return unavailable(
      'workspace_collaboration_capability_contract_invalid',
      negotiation,
    );
  }
  return degraded(WORKSPACE_COLLABORATION_DEGRADED_REASON, negotiation);
}

function matchesWorkspaceMutationActions(input: unknown): boolean {
  const surfaces = Object.keys(WORKSPACE_HTTP_MUTATION_ACTIONS);
  if (!isExactRecord(input, surfaces)) return false;
  return surfaces.every((surface) =>
    matchesExactStringArray(
      input[surface],
      WORKSPACE_HTTP_MUTATION_ACTIONS[
        surface as keyof typeof WORKSPACE_HTTP_MUTATION_ACTIONS
      ],
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
    const response = await fetch(
      absoluteUrl(config.apiBaseUrl, '/api/v1/search-enhanced/capabilities'),
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
): Promise<Readonly<{
  run: DesktopCapabilityAvailability;
  cronJobs: DesktopCapabilityAvailability;
}>> {
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
    const capability = unavailable(
      'automation_capability_contract_unavailable',
    );
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
    const path =
      `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}/projects/` +
      `${encodeURIComponent(scope.projectId)}/workspaces/` +
      `${encodeURIComponent(scope.workspaceId)}/collaboration/capabilities`;
    const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
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
    return normalizeWorkspaceCollaborationCapabilityContract(payload, scope);
  } catch (error) {
    if (signal?.aborted) throw error;
    return unavailable('workspace_collaboration_capability_contract_unavailable');
  }
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

function withCapabilityScope(
  capability: DesktopCapabilityAvailability,
  scope: DesktopCapabilityScope,
): DesktopCapabilityAvailability {
  return {
    ...capability,
    scope: { ...scope },
  };
}

function projectCapabilityScope(
  config: DesktopRuntimeConfig,
): DesktopCapabilityScope {
  return {
    tenant_id: scopeIdentifier(config.tenantId),
    project_id: scopeIdentifier(config.projectId),
    workspace_id: null,
    instance_id: null,
  };
}

function workspaceCapabilityScope(
  config: DesktopRuntimeConfig,
): DesktopCapabilityScope {
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

function matchesExactStringArray(
  input: unknown,
  expected: readonly string[],
): boolean {
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
  return Object.values(scope).every(
    (value) => value.length > 0 && value === value.trim(),
  )
    ? scope
    : null;
}
