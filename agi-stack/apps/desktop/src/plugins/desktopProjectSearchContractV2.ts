import { RuntimeV2Error } from '@agistack/plugin-runtime';

import {
  desktopSearchRequestContract,
  type DesktopSearchRequest,
  type DesktopSearchResponse,
  type DesktopSearchResult,
  type DesktopSearchType,
} from '../api/searchContract';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneRuntimeConfigV2,
  isPlainRecordV2,
} from './desktopNewTaskFlowContractV2';

export type DesktopProjectSearchScopeV2 = Readonly<{
  tenantId: string;
  projectId: string;
  signal?: AbortSignal;
}>;

const REQUEST_KEYS_V2 = Object.freeze({
  semantic: new Set([
    'mode',
    'query',
    'strategy',
    'focalNodeUuid',
    'reranker',
    'limit',
  ]),
  graphTraversal: new Set([
    'mode',
    'startEntityUuid',
    'maxDepth',
    'relationshipTypes',
    'limit',
  ]),
  temporal: new Set(['mode', 'query', 'since', 'until', 'limit']),
  faceted: new Set([
    'mode',
    'query',
    'entityTypes',
    'tags',
    'since',
    'limit',
    'offset',
  ]),
  community: new Set([
    'mode',
    'communityUuid',
    'includeEpisodes',
    'limit',
  ]),
});
const RESPONSE_KEYS_V2 = new Set([
  'results',
  'total',
  'searchType',
  'limit',
  'offset',
  'facets',
]);
const RESULT_KEYS_V2 = new Set([
  'id',
  'title',
  'content',
  'score',
  'source',
  'type',
  'createdAt',
  'tags',
]);
const FACET_KEYS_V2 = new Set(['entityTypes', 'total']);

export function cloneProjectSearchRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  try {
    return cloneRuntimeConfigV2(config);
  } catch {
    throw projectSearchInputInvalidV2();
  }
}

export function cloneProjectSearchScopeV2(
  value: unknown,
  config: DesktopRuntimeConfig,
): DesktopProjectSearchScopeV2 {
  if (
    !isPlainRecordV2(value) ||
    hasUnexpectedKeysV2(value, new Set(['tenantId', 'projectId', 'signal'])) ||
    !isCanonicalStringV2(value.tenantId) ||
    !isCanonicalStringV2(value.projectId)
  ) {
    throw projectSearchInputInvalidV2();
  }
  if (
    value.tenantId !== config.tenantId ||
    value.projectId !== config.projectId
  ) {
    throw projectSearchScopeMismatchV2();
  }
  const signal = cloneOptionalSignalV2(value.signal);
  return Object.freeze({
    tenantId: value.tenantId,
    projectId: value.projectId,
    ...(signal === undefined ? {} : { signal }),
  });
}

export function cloneProjectSearchRequestV2(
  value: unknown,
  scope: DesktopProjectSearchScopeV2,
): DesktopSearchRequest {
  if (!isPlainRecordV2(value) || typeof value.mode !== 'string') {
    throw projectSearchInputInvalidV2();
  }
  let copy: DesktopSearchRequest;
  switch (value.mode) {
    case 'semantic':
      assertExactRequestV2(value, REQUEST_KEYS_V2.semantic);
      copy = {
        mode: 'semantic',
        query: requireStringV2(value.query),
        strategy: requireStringV2(value.strategy),
        focalNodeUuid: optionalStringV2(value.focalNodeUuid),
        reranker: optionalStringV2(value.reranker),
        limit: requireNumberV2(value.limit),
      };
      break;
    case 'graphTraversal':
      assertExactRequestV2(value, REQUEST_KEYS_V2.graphTraversal);
      copy = {
        mode: 'graphTraversal',
        startEntityUuid: requireStringV2(value.startEntityUuid),
        maxDepth: requireNumberV2(value.maxDepth),
        relationshipTypes: cloneStringArrayV2(value.relationshipTypes),
        limit: requireNumberV2(value.limit),
      };
      break;
    case 'temporal':
      assertExactRequestV2(value, REQUEST_KEYS_V2.temporal);
      copy = {
        mode: 'temporal',
        query: requireStringV2(value.query),
        since: optionalStringV2(value.since),
        until: optionalStringV2(value.until),
        limit: requireNumberV2(value.limit),
      };
      break;
    case 'faceted':
      assertExactRequestV2(value, REQUEST_KEYS_V2.faceted);
      copy = {
        mode: 'faceted',
        query: requireStringV2(value.query),
        entityTypes: cloneStringArrayV2(value.entityTypes),
        tags: cloneStringArrayV2(value.tags),
        since: optionalStringV2(value.since),
        limit: requireNumberV2(value.limit),
        offset: requireNumberV2(value.offset),
      };
      break;
    case 'community':
      assertExactRequestV2(value, REQUEST_KEYS_V2.community);
      if (typeof value.includeEpisodes !== 'boolean') {
        throw projectSearchInputInvalidV2();
      }
      copy = {
        mode: 'community',
        communityUuid: requireStringV2(value.communityUuid),
        includeEpisodes: value.includeEpisodes,
        limit: requireNumberV2(value.limit),
      };
      break;
    default:
      throw projectSearchInputInvalidV2();
  }
  try {
    desktopSearchRequestContract(copy, scope);
  } catch {
    throw projectSearchInputInvalidV2();
  }
  return deepFreezeV2(copy);
}

export function assertProjectSearchResponseV2(
  value: unknown,
  request: DesktopSearchRequest,
): DesktopSearchResponse {
  const searchType = expectedSearchTypeV2(request.mode);
  if (
    !isPlainRecordV2(value) ||
    hasUnexpectedKeysV2(value, RESPONSE_KEYS_V2) ||
    !Array.isArray(value.results) ||
    !isNonNegativeIntegerV2(value.total) ||
    value.searchType !== searchType ||
    !isNullableNonNegativeIntegerV2(value.limit) ||
    !isNullableNonNegativeIntegerV2(value.offset)
  ) {
    throw projectSearchResponseInvalidV2();
  }
  const results = value.results.map(cloneSearchResultV2);
  const facets = cloneFacetsV2(value.facets);
  return deepFreezeV2({
    results,
    total: value.total,
    searchType,
    limit: value.limit,
    offset: value.offset,
    facets,
  });
}

export function projectSearchInputInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_search_input_invalid',
    'desktop Project Search authority received invalid input',
  );
}

export function projectSearchScopeMismatchV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_search_scope_mismatch',
    'desktop Project Search operation does not match its configured scope',
  );
}

function cloneSearchResultV2(value: unknown): DesktopSearchResult {
  if (
    !isPlainRecordV2(value) ||
    hasUnexpectedKeysV2(value, RESULT_KEYS_V2) ||
    !isNullableStringV2(value.id) ||
    !isNullableStringV2(value.title) ||
    typeof value.content !== 'string' ||
    !isNullableFiniteNumberV2(value.score) ||
    !isNullableStringV2(value.source) ||
    typeof value.type !== 'string' ||
    !isNullableStringV2(value.createdAt) ||
    !Array.isArray(value.tags) ||
    !value.tags.every((tag) => typeof tag === 'string')
  ) {
    throw projectSearchResponseInvalidV2();
  }
  return {
    id: value.id,
    title: value.title,
    content: value.content,
    score: value.score,
    source: value.source,
    type: value.type,
    createdAt: value.createdAt,
    tags: [...value.tags],
  };
}

function cloneFacetsV2(value: unknown): DesktopSearchResponse['facets'] {
  if (value === null) return null;
  if (
    !isPlainRecordV2(value) ||
    hasUnexpectedKeysV2(value, FACET_KEYS_V2) ||
    !isPlainRecordV2(value.entityTypes) ||
    !Object.values(value.entityTypes).every(isNonNegativeIntegerV2) ||
    !isNullableNonNegativeIntegerV2(value.total)
  ) {
    throw projectSearchResponseInvalidV2();
  }
  return {
    entityTypes: Object.fromEntries(
      Object.entries(value.entityTypes).map(([name, count]) => [
        name,
        count as number,
      ]),
    ),
    total: value.total,
  };
}

function expectedSearchTypeV2(
  mode: DesktopSearchRequest['mode'],
): DesktopSearchType {
  switch (mode) {
    case 'semantic':
      return 'advanced';
    case 'graphTraversal':
      return 'graph_traversal';
    case 'temporal':
      return 'temporal';
    case 'faceted':
      return 'faceted';
    case 'community':
      return 'community';
  }
}

function cloneOptionalSignalV2(value: unknown): AbortSignal | undefined {
  if (value === undefined) return undefined;
  if (typeof AbortSignal === 'undefined' || !(value instanceof AbortSignal)) {
    throw projectSearchInputInvalidV2();
  }
  return value;
}

function assertExactRequestV2(
  value: Record<string, unknown>,
  keys: ReadonlySet<string>,
): void {
  if (hasUnexpectedKeysV2(value, keys) || Object.keys(value).length !== keys.size) {
    throw projectSearchInputInvalidV2();
  }
}

function hasUnexpectedKeysV2(
  value: Record<string, unknown>,
  keys: ReadonlySet<string>,
): boolean {
  return Object.keys(value).some((key) => !keys.has(key));
}

function requireStringV2(value: unknown): string {
  if (typeof value !== 'string') throw projectSearchInputInvalidV2();
  return value;
}

function optionalStringV2(value: unknown): string | null {
  if (value === null) return null;
  return requireStringV2(value);
}

function requireNumberV2(value: unknown): number {
  if (typeof value !== 'number') throw projectSearchInputInvalidV2();
  return value;
}

function cloneStringArrayV2(value: unknown): string[] {
  if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) {
    throw projectSearchInputInvalidV2();
  }
  return [...value];
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isNullableStringV2(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNullableFiniteNumberV2(value: unknown): value is number | null {
  return value === null || (typeof value === 'number' && Number.isFinite(value));
}

function isNonNegativeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isNullableNonNegativeIntegerV2(
  value: unknown,
): value is number | null {
  return value === null || isNonNegativeIntegerV2(value);
}

function deepFreezeV2<T>(value: T): T {
  if (Array.isArray(value)) {
    for (const item of value) deepFreezeV2(item);
    return Object.freeze(value);
  }
  if (isPlainRecordV2(value)) {
    for (const item of Object.values(value)) deepFreezeV2(item);
    return Object.freeze(value) as T;
  }
  return value;
}

function projectSearchResponseInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_search_response_invalid',
    'desktop Project Search authority returned an invalid response',
  );
}
