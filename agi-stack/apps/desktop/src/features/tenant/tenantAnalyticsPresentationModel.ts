import type {
  TenantAnalyticsAuthority,
  TenantAnalyticsAvailability,
  TenantAnalyticsScope,
  TenantAnalyticsSnapshot,
} from './tenantAnalyticsClient';

export type TenantAnalyticsTerminalState =
  | 'error'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type TenantAnalyticsPresentationInput =
  | Readonly<{ kind: 'ready'; snapshot: TenantAnalyticsSnapshot }>
  | Readonly<{
      kind: 'loading';
      scope: TenantAnalyticsScope;
      scopeSwitch: boolean;
    }>
  | Readonly<{
      kind: TenantAnalyticsTerminalState;
      scope: TenantAnalyticsScope;
      reasonCode: string;
      retryable?: boolean;
    }>;

export type TenantAnalyticsSummaryItem = Readonly<{
  id: 'memories' | 'projects' | 'average' | 'storage';
  availability: TenantAnalyticsAvailability;
  reasonCode: string | null;
  value: string | null;
}>;

export type TenantAnalyticsPresentationModel = Readonly<{
  state:
    | 'loading'
    | 'scope_switch'
    | 'empty'
    | 'ready'
    | 'degraded'
    | TenantAnalyticsTerminalState;
  scope: TenantAnalyticsScope;
  authority: TenantAnalyticsAuthority;
  reasonCode: string | null;
  retryVisible: boolean;
  summary: readonly TenantAnalyticsSummaryItem[];
  trend: 'up' | 'down' | 'flat' | null;
  memoryGrowth: Readonly<{
    availability: TenantAnalyticsAvailability;
    reasonCode: string | null;
    points: readonly Readonly<{ date: string; count: number }>[];
  }>;
  projects: readonly Readonly<{
    name: string;
    storageBytes: number | null;
    storageLabel: string | null;
    memoryCount: number | null;
    reasonCode: string | null;
  }>[];
}>;

export function buildTenantAnalyticsPresentation(
  input: TenantAnalyticsPresentationInput,
): TenantAnalyticsPresentationModel {
  if (input.kind !== 'ready') {
    return Object.freeze({
      state:
        input.kind === 'loading'
          ? input.scopeSwitch
            ? 'scope_switch'
            : 'loading'
          : input.kind,
      scope: input.scope,
      authority: input.scope.authority,
      reasonCode: input.kind === 'loading' ? null : input.reasonCode,
      retryVisible:
        input.kind !== 'loading' &&
        (input.kind === 'error' ||
          input.kind === 'conflict' ||
          input.kind === 'unavailable') &&
        input.retryable === true,
      summary: Object.freeze([]),
      trend: null,
      memoryGrowth: {
        availability: 'unavailable',
        reasonCode: 'tenant_analytics_not_loaded',
        points: Object.freeze([]),
      },
      projects: Object.freeze([]),
    } satisfies TenantAnalyticsPresentationModel);
  }

  const snapshot = input.snapshot;
  const summary = Object.freeze([
    summaryItem(
      'memories',
      snapshot.summary.totalMemories,
      formatCount(snapshot.summary.totalMemories.value),
    ),
    summaryItem(
      'projects',
      snapshot.summary.totalProjects,
      formatCount(snapshot.summary.totalProjects.value),
    ),
    averageSummary(snapshot),
    summaryItem(
      'storage',
      snapshot.summary.totalStorageBytes,
      snapshot.summary.totalStorageBytes.value === null
        ? null
        : formatTenantAnalyticsBytes(snapshot.summary.totalStorageBytes.value),
    ),
  ]);
  const empty =
    snapshot.availability === 'available' &&
    snapshot.summary.totalMemories.value === 0 &&
    snapshot.summary.totalProjects.value === 0 &&
    snapshot.memoryGrowth.value.length === 0 &&
    snapshot.projectStorage.value.length === 0;
  return Object.freeze({
    state:
      snapshot.availability === 'degraded'
        ? 'degraded'
        : empty
          ? 'empty'
          : 'ready',
    scope: snapshot.scope,
    authority: snapshot.authority,
    reasonCode: snapshot.reasonCode,
    retryVisible: false,
    summary,
    trend: memoryTrend(snapshot.memoryGrowth.value),
    memoryGrowth: {
      availability: snapshot.memoryGrowth.availability,
      reasonCode: snapshot.memoryGrowth.reasonCode,
      points: snapshot.memoryGrowth.value,
    },
    projects: Object.freeze(
      snapshot.projectStorage.value.map((project) => ({
        name: project.name,
        storageBytes: project.storageBytes.value,
        storageLabel:
          project.storageBytes.value === null
            ? null
            : formatTenantAnalyticsBytes(project.storageBytes.value),
        memoryCount: project.memoryCount.value,
        reasonCode:
          project.storageBytes.reasonCode ?? project.memoryCount.reasonCode,
      })),
    ),
  });
}

export function formatTenantAnalyticsBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'] as const;
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const rounded = Math.round(value * 10) / 10;
  return `${rounded} ${units[unitIndex]}`;
}

function averageSummary(
  snapshot: TenantAnalyticsSnapshot,
): TenantAnalyticsSummaryItem {
  const memories = snapshot.summary.totalMemories;
  const projects = snapshot.summary.totalProjects;
  if (memories.value === null || projects.value === null) {
    return {
      id: 'average',
      availability:
        memories.availability === 'unavailable'
          ? memories.availability
          : projects.availability,
      reasonCode: memories.reasonCode ?? projects.reasonCode,
      value: null,
    };
  }
  return {
    id: 'average',
    availability:
      memories.availability === 'degraded' ||
      projects.availability === 'degraded'
        ? 'degraded'
        : 'available',
    reasonCode: memories.reasonCode ?? projects.reasonCode,
    value:
      projects.value === 0
        ? '0'
        : Math.round(memories.value / projects.value).toLocaleString(),
  };
}

function summaryItem(
  id: TenantAnalyticsSummaryItem['id'],
  field: Readonly<{
    availability: TenantAnalyticsAvailability;
    reasonCode: string | null;
  }>,
  value: string | null,
): TenantAnalyticsSummaryItem {
  return {
    id,
    availability: field.availability,
    reasonCode: field.reasonCode,
    value,
  };
}

function formatCount(value: number | null): string | null {
  return value === null ? null : value.toLocaleString();
}

function memoryTrend(
  points: readonly Readonly<{ count: number }>[],
): 'up' | 'down' | 'flat' | null {
  if (points.length < 2) return null;
  const half = Math.floor(points.length / 2);
  const earlier = points.slice(0, half).reduce((sum, point) => sum + point.count, 0);
  const recent = points.slice(half).reduce((sum, point) => sum + point.count, 0);
  if (recent === earlier) return 'flat';
  return recent > earlier ? 'up' : 'down';
}
