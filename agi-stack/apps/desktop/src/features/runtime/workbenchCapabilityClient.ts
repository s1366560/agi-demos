import {
  absoluteUrl,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopAutomationApi } from '../automations/automationClient';
import { normalizeAutomationCapabilities } from '../automations/automationModel';
import type { DesktopRuntimeConfig } from '../../types';
import {
  DESKTOP_CAPABILITY_SNAPSHOT_VERSION,
  DESKTOP_MINIMUM_CONTRACT_VERSION,
  parseDesktopCapabilitySnapshot,
  type DesktopCapabilityAvailability,
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
      const [search, automationRun, workspaceCollaboration] = await Promise.all([
        loadSearchCapability(config, signal),
        loadAutomationCapability(automationApi, config.projectId, signal),
        loadWorkspaceCollaborationCapability(config, signal),
      ]);
      const rawSnapshot = {
        version: DESKTOP_CAPABILITY_SNAPSHOT_VERSION,
        mode: config.mode,
        capabilities: {
          automation_run: automationRun,
          search,
          workspace_collaboration: workspaceCollaboration,
          sandbox_isolation:
            config.mode === 'local'
              ? notApplicable('local_isolation_not_applicable')
              : unavailable('sandbox_isolation_capability_not_declared'),
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
  return available(negotiation);
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
  return degraded(input.reason_code, negotiation);
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
  return available(negotiation);
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
  if (
    !isExactRecord(input, [
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
    ]) ||
    input.authority !== 'cloud' ||
    input.status !== 'degraded' ||
    input.reason_code !== WORKSPACE_COLLABORATION_DEGRADED_REASON ||
    input.canonical_read !== true ||
    !matchesExactStringArray(
      input.read_surfaces,
      WORKSPACE_COLLABORATION_READ_SURFACES,
    ) ||
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
  if (
    input.tenant_id !== scope.tenantId ||
    input.project_id !== scope.projectId ||
    input.workspace_id !== scope.workspaceId
  ) {
    return unavailable(
      'workspace_collaboration_capability_scope_mismatch',
      negotiation,
    );
  }
  return degraded(WORKSPACE_COLLABORATION_DEGRADED_REASON, negotiation);
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

async function loadAutomationCapability(
  automationApi: AutomationCapabilityAuthority,
  projectId: string,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  if (!projectId.trim()) {
    return unavailable('automation_capability_scope_unavailable');
  }
  try {
    const payload = await automationApi.getAutomationCapabilities(projectId, signal);
    return normalizeAutomationCapabilityContract(payload);
  } catch (error) {
    if (signal?.aborted) throw error;
    return unavailable('automation_capability_contract_unavailable');
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

function available(
  negotiation: CapabilityContractNegotiation,
): DesktopCapabilityAvailability {
  return {
    status: 'available',
    reason_code: null,
    service_version: negotiation.service_version,
    contract_version: negotiation.contract_version,
    minimum_contract_version: DESKTOP_MINIMUM_CONTRACT_VERSION,
  };
}

function degraded(
  reasonCode: string,
  negotiation: CapabilityContractNegotiation,
): DesktopCapabilityAvailability {
  return {
    status: 'degraded',
    reason_code: reasonCode,
    service_version: negotiation.service_version,
    contract_version: negotiation.contract_version,
    minimum_contract_version: DESKTOP_MINIMUM_CONTRACT_VERSION,
  };
}

function unavailable(
  reasonCode: string,
  negotiation?: CapabilityContractNegotiation,
): DesktopCapabilityAvailability {
  return {
    status: 'unavailable',
    reason_code: reasonCode,
    service_version: negotiation?.service_version ?? null,
    contract_version: negotiation?.contract_version ?? null,
    minimum_contract_version: DESKTOP_MINIMUM_CONTRACT_VERSION,
  };
}

function notApplicable(reasonCode: string): DesktopCapabilityAvailability {
  return {
    status: 'not_applicable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    minimum_contract_version: DESKTOP_MINIMUM_CONTRACT_VERSION,
  };
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
