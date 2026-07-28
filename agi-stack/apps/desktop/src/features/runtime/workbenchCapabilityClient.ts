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
  parseDesktopCapabilitySnapshot,
  type DesktopCapabilityAvailability,
  type DesktopCapabilitySnapshot,
} from './capabilitySnapshot';

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
      const [search, automationRun] = await Promise.all([
        loadSearchCapability(config, signal),
        loadAutomationCapability(automationApi, config.projectId, signal),
      ]);
      const rawSnapshot = {
        version: DESKTOP_CAPABILITY_SNAPSHOT_VERSION,
        mode: config.mode,
        capabilities: {
          automation_run: automationRun,
          search,
          workspace_collaboration: unavailable(
            config.mode === 'local'
              ? 'local_workspace_collaboration_unavailable'
              : 'workspace_collaboration_capability_not_declared',
          ),
          sandbox_isolation: unavailable(
            config.mode === 'local'
              ? 'local_isolation_not_applicable'
              : 'sandbox_isolation_capability_not_declared',
          ),
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
  if (
    !isExactRecord(input, ['search_types', 'filters']) ||
    !isExactRecord(input.search_types, Object.keys(SEARCH_CONTRACT)) ||
    !isExactRecord(input.filters, ['entity_types', 'relationship_types']) ||
    !isStringArray(input.filters.entity_types) ||
    !isStringArray(input.filters.relationship_types)
  ) {
    return unavailable('search_capability_contract_invalid');
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
      return unavailable('search_capability_contract_invalid');
    }
  }
  return available();
}

export function normalizeAutomationCapabilityContract(
  input: unknown,
): DesktopCapabilityAvailability {
  const capabilities = normalizeAutomationCapabilities(input);
  if (!capabilities) return unavailable('automation_capability_contract_invalid');

  const runCapability = capabilities.run_now;
  if (!runCapability.allowed) {
    return unavailable(runCapability.reason_code!);
  }
  if (
    !capabilities.read ||
    !capabilities.revision_guarded ||
    !capabilities.idempotency_guarded ||
    !capabilities.durable_execution
  ) {
    return unavailable('automation_capability_contract_invalid');
  }
  return available();
}

async function loadSearchCapability(
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  if (config.mode === 'local') {
    return unavailable('local_search_routes_unavailable');
  }

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

function available(): DesktopCapabilityAvailability {
  return { available: true, reason_code: null };
}

function unavailable(reasonCode: string): DesktopCapabilityAvailability {
  return { available: false, reason_code: reasonCode };
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
