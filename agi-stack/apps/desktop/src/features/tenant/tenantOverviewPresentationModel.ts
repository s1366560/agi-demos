import type {
  TenantOverviewAuthority,
  TenantOverviewAvailability,
  TenantOverviewProject,
  TenantOverviewScope,
  TenantOverviewSnapshot,
} from './tenantOverviewClient';

export type TenantOverviewTerminalState =
  | 'empty'
  | 'error'
  | 'forbidden'
  | 'unavailable';

export type TenantOverviewPresentationInput =
  | Readonly<{
      kind: 'ready';
      snapshot: TenantOverviewSnapshot;
    }>
  | Readonly<{
      kind: 'loading';
      scope: TenantOverviewScope;
      scopeSwitch: boolean;
    }>
  | Readonly<{
      kind: TenantOverviewTerminalState;
      scope: TenantOverviewScope;
      reasonCode: string;
      retryable?: boolean;
    }>;

export type TenantOverviewSummary = Readonly<{
  id: 'storage' | 'projects' | 'members';
  availability: TenantOverviewAvailability;
  reasonCode: string | null;
  value: number | null;
}>;

export type TenantOverviewPresentationModel = Readonly<{
  state:
    | 'loading'
    | 'scope_switch'
    | 'ready'
    | 'degraded'
    | TenantOverviewTerminalState;
  scope: TenantOverviewScope;
  authority: TenantOverviewAuthority;
  reasonCode: string | null;
  retryVisible: boolean;
  tenant: Readonly<{
    organizationId: string;
    plan: string;
    region: string | null;
    nextBillingDate: string | null;
  }> | null;
  summary: readonly TenantOverviewSummary[];
  projects: readonly Readonly<{
    id: string;
    name: string;
    owner: string | null;
    memoryConsumed: string | null;
    status: string;
  }>[];
  memoryHistory: TenantOverviewSnapshot['memoryHistory'];
}>;

export function buildTenantOverviewPresentation(
  input: TenantOverviewPresentationInput,
): TenantOverviewPresentationModel {
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
        (input.kind === 'error' || input.kind === 'unavailable') &&
        input.retryable === true,
      tenant: null,
      summary: Object.freeze([]),
      projects: Object.freeze([]),
      memoryHistory: {
        availability: 'unavailable',
        reasonCode: 'tenant_overview_not_loaded',
        value: Object.freeze([]),
      } satisfies TenantOverviewSnapshot['memoryHistory'],
    });
  }

  const snapshot = input.snapshot;
  return Object.freeze({
    state: snapshot.availability === 'degraded' ? 'degraded' : 'ready',
    scope: snapshot.scope,
    authority: snapshot.authority,
    reasonCode: snapshot.reasonCode,
    retryVisible: false,
    tenant: {
      organizationId: snapshot.tenantInfo.organizationId,
      plan: snapshot.tenantInfo.plan,
      region: snapshot.tenantInfo.region.value,
      nextBillingDate: snapshot.tenantInfo.nextBillingDate.value,
    },
    summary: Object.freeze([
      summaryField('storage', snapshot.storage.availability, snapshot.storage.reasonCode, snapshot.storage.value?.used ?? null),
      summaryField(
        'projects',
        snapshot.projects.availability,
        snapshot.projects.reasonCode,
        snapshot.projects.active,
      ),
      summaryField('members', snapshot.members.availability, snapshot.members.reasonCode, snapshot.members.value.total),
    ]),
    projects: Object.freeze(snapshot.projects.value.map(projectPresentation)),
    memoryHistory: snapshot.memoryHistory,
  });
}

function summaryField(
  id: TenantOverviewSummary['id'],
  availability: TenantOverviewAvailability,
  reasonCode: string | null,
  value: number | null,
): TenantOverviewSummary {
  return { id, availability, reasonCode, value };
}

function projectPresentation(project: TenantOverviewProject) {
  return {
    id: project.id,
    name: project.name,
    owner: project.owner.value,
    memoryConsumed: project.memoryConsumed.value,
    status: project.status,
  };
}
