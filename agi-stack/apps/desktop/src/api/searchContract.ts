export type DesktopSearchMode =
  | 'semantic'
  | 'graphTraversal'
  | 'temporal'
  | 'faceted'
  | 'community';

export type DesktopSearchRequest =
  | {
      mode: 'semantic';
      query: string;
      strategy: string;
      focalNodeUuid: string | null;
      reranker: string | null;
      limit: number;
    }
  | {
      mode: 'graphTraversal';
      startEntityUuid: string;
      maxDepth: number;
      relationshipTypes: string[];
      limit: number;
    }
  | {
      mode: 'temporal';
      query: string;
      since: string | null;
      until: string | null;
      limit: number;
    }
  | {
      mode: 'faceted';
      query: string;
      entityTypes: string[];
      tags: string[];
      since: string | null;
      limit: number;
      offset: number;
    }
  | {
      mode: 'community';
      communityUuid: string;
      includeEpisodes: boolean;
      limit: number;
    };

export type DesktopSearchType =
  | 'advanced'
  | 'graph_traversal'
  | 'temporal'
  | 'faceted'
  | 'community';

export type DesktopSearchRequestContract = {
  path: string;
  expectedSearchType: DesktopSearchType;
  body: Record<string, unknown>;
};

export type DesktopSearchResult = {
  id: string | null;
  title: string | null;
  content: string;
  score: number | null;
  source: string | null;
  type: string;
  createdAt: string | null;
  tags: string[];
};

export type DesktopSearchResponse = {
  results: DesktopSearchResult[];
  total: number;
  searchType: DesktopSearchType;
  limit: number | null;
  offset: number | null;
  facets: { entityTypes: Record<string, number>; total: number | null } | null;
};

type DesktopSearchScope = {
  tenantId: string;
  projectId: string;
};

export function desktopSearchRequestContract(
  request: DesktopSearchRequest,
  scope: DesktopSearchScope,
): DesktopSearchRequestContract {
  const tenantId = requireSearchValue(scope.tenantId, 'tenant id');
  const projectId = requireSearchValue(scope.projectId, 'project id');
  const limit = requireSearchInteger(request.limit, 'result limit', 1, 200);
  const scopedBody = {
    tenant_id: tenantId,
    project_id: projectId,
  };

  switch (request.mode) {
    case 'semantic':
      return {
        path: '/api/v1/search-enhanced/advanced',
        expectedSearchType: 'advanced',
        body: {
          query: requireSearchValue(request.query, 'search query'),
          strategy: requireSearchValue(request.strategy, 'search strategy'),
          focal_node_uuid: optionalSearchValue(request.focalNodeUuid),
          reranker: optionalSearchValue(request.reranker),
          limit,
          ...scopedBody,
        },
      };
    case 'graphTraversal':
      return {
        path: '/api/v1/search-enhanced/graph-traversal',
        expectedSearchType: 'graph_traversal',
        body: {
          start_entity_uuid: requireSearchValue(request.startEntityUuid, 'start entity uuid'),
          max_depth: requireSearchInteger(request.maxDepth, 'max depth', 1, 5),
          relationship_types: normalizeSearchList(request.relationshipTypes),
          limit,
          ...scopedBody,
        },
      };
    case 'temporal':
      return {
        path: '/api/v1/search-enhanced/temporal',
        expectedSearchType: 'temporal',
        body: {
          query: requireSearchValue(request.query, 'search query'),
          since: optionalSearchValue(request.since),
          until: optionalSearchValue(request.until),
          limit,
          ...scopedBody,
        },
      };
    case 'faceted':
      return {
        path: '/api/v1/search-enhanced/faceted',
        expectedSearchType: 'faceted',
        body: {
          query: requireSearchValue(request.query, 'search query'),
          entity_types: normalizeSearchList(request.entityTypes),
          tags: normalizeSearchList(request.tags),
          since: optionalSearchValue(request.since),
          limit,
          offset: requireSearchInteger(request.offset, 'result offset', 0),
          ...scopedBody,
        },
      };
    case 'community':
      return {
        path: '/api/v1/search-enhanced/community',
        expectedSearchType: 'community',
        body: {
          community_uuid: requireSearchValue(request.communityUuid, 'community uuid'),
          include_episodes: request.includeEpisodes,
          limit,
          ...scopedBody,
        },
      };
  }
}

export function normalizeDesktopSearchResponse(
  payload: unknown,
  expectedSearchType: DesktopSearchType,
): DesktopSearchResponse | null {
  if (!isRecord(payload) || payload.search_type !== expectedSearchType) return null;
  if (!Array.isArray(payload.results)) return null;
  if (!isNonNegativeInteger(payload.total)) return null;

  const results: DesktopSearchResult[] = [];
  for (const item of payload.results) {
    const result = normalizeDesktopSearchResult(item);
    if (!result) return null;
    results.push(result);
  }

  const limit =
    payload.limit === undefined || payload.limit === null
      ? null
      : isNonNegativeInteger(payload.limit)
        ? payload.limit
        : null;
  const offset =
    payload.offset === undefined || payload.offset === null
      ? null
      : isNonNegativeInteger(payload.offset)
        ? payload.offset
        : null;
  if (
    (payload.limit !== undefined && payload.limit !== null && limit === null) ||
    (payload.offset !== undefined && payload.offset !== null && offset === null)
  ) {
    return null;
  }

  const facets = normalizeDesktopSearchFacets(payload.facets);
  if (payload.facets !== undefined && payload.facets !== null && !facets) return null;

  return {
    results,
    total: payload.total,
    searchType: expectedSearchType,
    limit,
    offset,
    facets,
  };
}

function normalizeDesktopSearchResult(value: unknown): DesktopSearchResult | null {
  if (!isRecord(value)) return null;
  const metadata = isRecord(value.metadata) ? value.metadata : {};
  const id = firstString(value, metadata, ['uuid', 'memory_id']);
  const title = firstString(value, metadata, ['name', 'title']);
  const rawContent = firstString(value, metadata, ['content', 'summary', 'text']);
  if (!id && !title && !rawContent) return null;

  const rawTags = value.tags ?? metadata.tags;
  if (
    rawTags !== undefined &&
    (!Array.isArray(rawTags) || !rawTags.every((tag): tag is string => typeof tag === 'string'))
  ) {
    return null;
  }
  const rawScore = value.score ?? metadata.score;
  if (
    rawScore !== undefined &&
    rawScore !== null &&
    (typeof rawScore !== 'number' || !Number.isFinite(rawScore))
  ) {
    return null;
  }

  return {
    id,
    title,
    content: rawContent ?? title ?? '',
    score: typeof rawScore === 'number' ? rawScore : null,
    source: firstString(value, metadata, ['source']),
    type: firstString(value, metadata, ['type', 'entity_type']) ?? 'Result',
    createdAt: firstString(value, metadata, ['created_at']),
    tags: rawTags ? [...rawTags] : [],
  };
}

function normalizeDesktopSearchFacets(value: unknown): DesktopSearchResponse['facets'] | null {
  if (value === undefined || value === null) return null;
  if (!isRecord(value)) return null;
  const entityTypesValue = value.entity_types;
  if (!isRecord(entityTypesValue)) return null;
  const entityTypes: Record<string, number> = {};
  for (const [key, count] of Object.entries(entityTypesValue)) {
    if (!isNonNegativeInteger(count)) return null;
    entityTypes[key] = count;
  }
  const total =
    value.total === undefined || value.total === null
      ? null
      : isNonNegativeInteger(value.total)
        ? value.total
        : null;
  if (value.total !== undefined && value.total !== null && total === null) return null;
  return { entityTypes, total };
}

function requireSearchValue(value: string, name: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`Missing ${name}`);
  return normalized;
}

function optionalSearchValue(value: string | null): string | null {
  const normalized = value?.trim() ?? '';
  return normalized || null;
}

function requireSearchInteger(
  value: number,
  name: string,
  minimum: number,
  maximum = Number.MAX_SAFE_INTEGER,
): number {
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`Invalid ${name}`);
  }
  return value;
}

function normalizeSearchList(values: string[]): string[] {
  const normalized: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const item = value.trim();
    if (!item || seen.has(item)) continue;
    seen.add(item);
    normalized.push(item);
  }
  return normalized;
}

function firstString(
  primary: Record<string, unknown>,
  secondary: Record<string, unknown>,
  keys: string[],
): string | null {
  for (const source of [primary, secondary]) {
    for (const key of keys) {
      const value = source[key];
      if (typeof value === 'string' && value.trim()) return value;
    }
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}
