import {
  DESKTOP_MINIMUM_CONTRACT_VERSION,
  type DesktopCapabilityAvailability,
} from './capabilitySnapshot';
import { negotiateCapabilityContract } from './capabilityVersion';
import { available, degraded, unavailable } from './workbenchCapabilityAvailability';

type SearchCapabilityDeclaration = {
  endpoint: string;
  parameters?: Readonly<Record<string, string>>;
};

const LOCAL_SEARCH_SUPPORTED_TYPES = [
  'advanced',
  'temporal',
  'faceted',
] as const;
const LOCAL_SEARCH_UNAVAILABLE_TYPES = [
  'graph_traversal',
  'community',
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
  return (
    keys.length === expected.length &&
    keys.every((key, index) => key === expected[index])
  );
}

function isStringArray(input: unknown): input is string[] {
  return (
    Array.isArray(input) && input.every((item) => typeof item === 'string')
  );
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

