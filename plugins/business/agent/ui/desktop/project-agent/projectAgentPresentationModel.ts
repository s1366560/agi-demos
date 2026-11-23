import type { ProjectAgentScope, ProjectAgentSnapshotBase } from './projectAgentClient';

export type ProjectAgentItem = Readonly<{
  id: string;
  title: string;
  detail: string;
  status: string;
  createdAt: string;
}>;
export type ProjectAgentViewModel = Readonly<{
  routeId: string;
  state:
    | 'loading'
    | 'scope_switch'
    | 'empty'
    | 'ready'
    | 'degraded'
    | 'error'
    | 'forbidden'
    | 'unavailable';
  scope: ProjectAgentScope;
  reasonCode: string | null;
  retryVisible: boolean;
  allowedActions: readonly string[];
  items: readonly ProjectAgentItem[];
  total: number;
  metrics: Readonly<Record<string, string | number>>;
}>;
export type ProjectAgentPresentationInput<TSnapshot extends ProjectAgentSnapshotBase> =
  | Readonly<{
      kind: 'loading';
      scope: ProjectAgentScope;
      scopeSwitch: boolean;
    }>
  | Readonly<{ kind: 'snapshot'; snapshot: TSnapshot }>
  | Readonly<{
      kind: 'failure';
      scope: ProjectAgentScope;
      state: 'error' | 'forbidden' | 'unavailable';
      reasonCode: string;
      retryable: boolean;
    }>;

export function buildProjectAgentPresentation<TSnapshot extends ProjectAgentSnapshotBase>(
  routeId: string,
  input: ProjectAgentPresentationInput<TSnapshot>,
  project: (snapshot: TSnapshot) => Readonly<{
    items: readonly ProjectAgentItem[];
    total: number;
    metrics?: Readonly<Record<string, string | number>>;
  }>,
): ProjectAgentViewModel {
  if (input.kind === 'snapshot') {
    const projected = project(input.snapshot);
    return Object.freeze({
      routeId,
      state:
        projected.total === 0
          ? 'empty'
          : input.snapshot.availability === 'degraded'
            ? 'degraded'
            : 'ready',
      scope: input.snapshot.scope,
      reasonCode: input.snapshot.reasonCode,
      retryVisible: false,
      allowedActions: input.snapshot.allowedActions,
      items: projected.items,
      total: projected.total,
      metrics: Object.freeze({ ...(projected.metrics ?? {}) }),
    });
  }
  return Object.freeze({
    routeId,
    state:
      input.kind === 'loading' ? (input.scopeSwitch ? 'scope_switch' : 'loading') : input.state,
    scope: input.scope,
    reasonCode: input.kind === 'failure' ? input.reasonCode : null,
    retryVisible: input.kind === 'failure' && input.retryable,
    allowedActions: Object.freeze([]),
    items: Object.freeze([]),
    total: 0,
    metrics: Object.freeze({}),
  });
}
