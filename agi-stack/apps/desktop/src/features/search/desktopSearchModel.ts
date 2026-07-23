import type { DesktopSearchRequest } from '../../api/searchContract';

export const DESKTOP_SEARCH_PAGE_SIZE = 50;
export const DESKTOP_SEARCH_MAX_RESULTS = 200;

export type DesktopSearchResponseAuthority = {
  generation: number;
  tenantId: string;
  projectId: string;
};

export function nextDesktopSearchLimit(currentLimit: number): number | null {
  if (!Number.isSafeInteger(currentLimit) || currentLimit < DESKTOP_SEARCH_PAGE_SIZE) {
    throw new Error('Search result limit must be a positive page-sized integer');
  }
  if (currentLimit >= DESKTOP_SEARCH_MAX_RESULTS) return null;
  return Math.min(currentLimit + DESKTOP_SEARCH_PAGE_SIZE, DESKTOP_SEARCH_MAX_RESULTS);
}

export function searchResponseMayCommit(
  expected: DesktopSearchResponseAuthority,
  current: DesktopSearchResponseAuthority,
): boolean {
  return (
    expected.generation === current.generation &&
    expected.tenantId === current.tenantId &&
    expected.projectId === current.projectId
  );
}

export function commaSeparatedSearchValues(value: string): string[] {
  const normalized = value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  return [...new Set(normalized)];
}

export function desktopSearchRequestIsComplete(request: DesktopSearchRequest): boolean {
  if (
    !Number.isSafeInteger(request.limit) ||
    request.limit < 1 ||
    request.limit > DESKTOP_SEARCH_MAX_RESULTS
  ) {
    return false;
  }
  switch (request.mode) {
    case 'semantic':
      return Boolean(request.query.trim() && request.strategy.trim());
    case 'graphTraversal':
      return Boolean(
        request.startEntityUuid.trim() &&
        Number.isSafeInteger(request.maxDepth) &&
        request.maxDepth >= 1 &&
        request.maxDepth <= 5,
      );
    case 'temporal':
      return Boolean(request.query.trim());
    case 'faceted':
      return Boolean(
        request.query.trim() && Number.isSafeInteger(request.offset) && request.offset >= 0,
      );
    case 'community':
      return Boolean(request.communityUuid.trim());
  }
}

export function toggleSelectedSearchResult(
  selectedIds: readonly string[],
  resultId: string,
): string[] {
  return selectedIds.includes(resultId)
    ? selectedIds.filter((id) => id !== resultId)
    : [...selectedIds, resultId];
}
