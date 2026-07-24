import type { AgentTimelineItem, RuntimeMode } from '../../types';

const STORAGE_PREFIX = 'memstack:desktop:turn-collapse:v1';
const MAX_STORED_TURNS = 500;
const MAX_TURN_ID_LENGTH = 256;

export type TimelineTurn = {
  id: string;
  userItemId: string;
  responseItemIds: string[];
};

export type TimelineTurnCollapseScope = {
  mode: RuntimeMode;
  apiBaseUrl: string;
  tenantId: string;
  projectId: string;
  conversationId: string;
};

type TimelineTurnItem = Pick<AgentTimelineItem, 'id' | 'type' | 'role'>;

type TimelineTurnStorage = Pick<Storage, 'getItem' | 'setItem'>;

export function computeTimelineTurns(items: readonly TimelineTurnItem[]): TimelineTurn[] {
  const turns: TimelineTurn[] = [];
  let current: TimelineTurn | null = null;
  for (const item of items) {
    if (item.type === 'user_message' || item.role === 'user') {
      current = {
        id: item.id,
        userItemId: item.id,
        responseItemIds: [],
      };
      turns.push(current);
      continue;
    }
    if (current) current.responseItemIds.push(item.id);
  }
  return turns;
}

export function timelineTurnForMember(
  turns: readonly TimelineTurn[],
  memberId: string,
): TimelineTurn | null {
  return turns.find((turn) => turn.responseItemIds.includes(memberId)) ?? null;
}

export function collapsedTimelineTurnStorageKey(scope: TimelineTurnCollapseScope): string {
  const parts = [
    scope.mode,
    normalizedApiAuthority(scope.apiBaseUrl),
    boundedScopePart(scope.tenantId),
    boundedScopePart(scope.projectId),
    boundedScopePart(scope.conversationId),
  ];
  return `${STORAGE_PREFIX}:${encodeURIComponent(JSON.stringify(parts))}`;
}

export function readCollapsedTimelineTurnIds(
  storage: Pick<TimelineTurnStorage, 'getItem'>,
  scope: TimelineTurnCollapseScope,
): string[] {
  try {
    const parsed: unknown = JSON.parse(
      storage.getItem(collapsedTimelineTurnStorageKey(scope)) ?? '[]',
    );
    return normalizeStoredTurnIds(parsed);
  } catch {
    return [];
  }
}

export function writeCollapsedTimelineTurnIds(
  storage: Pick<TimelineTurnStorage, 'setItem'>,
  scope: TimelineTurnCollapseScope,
  turnIds: readonly string[],
): void {
  try {
    storage.setItem(
      collapsedTimelineTurnStorageKey(scope),
      JSON.stringify(normalizeStoredTurnIds(turnIds)),
    );
  } catch {
    // Storage can be unavailable or full. Collapsing still works for the current render.
  }
}

function normalizeStoredTurnIds(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const unique = Array.from(
    new Set(
      value.filter(
        (candidate): candidate is string =>
          typeof candidate === 'string' &&
          candidate.length > 0 &&
          candidate.length <= MAX_TURN_ID_LENGTH,
      ),
    ),
  );
  return unique.slice(-MAX_STORED_TURNS);
}

function normalizedApiAuthority(apiBaseUrl: string): string {
  try {
    const url = new URL(apiBaseUrl);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return 'invalid-api-authority';
    const pathname = url.pathname.replace(/\/+$/u, '') || '/';
    return `${url.origin.toLowerCase()}${pathname}`;
  } catch {
    return 'invalid-api-authority';
  }
}

function boundedScopePart(value: string): string {
  const trimmed = value.trim();
  return trimmed.length <= MAX_TURN_ID_LENGTH
    ? trimmed
    : trimmed.slice(0, MAX_TURN_ID_LENGTH);
}
