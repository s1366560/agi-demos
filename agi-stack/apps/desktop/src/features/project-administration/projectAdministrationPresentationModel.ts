import type {
  ProjectAdministrationScope,
  ProjectAdministrationSnapshotBase,
} from './projectAdministrationClient';

export type ProjectAdministrationState =
  | 'loading'
  | 'scope_switch'
  | 'empty'
  | 'ready'
  | 'degraded'
  | 'stale'
  | 'error'
  | 'forbidden'
  | 'conflict'
  | 'unavailable';
export type ProjectAdministrationItem = Readonly<{
  id: string;
  title: string;
  detail: string;
}>;
export type ProjectAdministrationViewModelBase = Readonly<{
  routeId: string;
  state: ProjectAdministrationState;
  scope: ProjectAdministrationScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  items: readonly ProjectAdministrationItem[];
}>;
export type ProjectAdministrationPresentationState<
  TSnapshot extends ProjectAdministrationSnapshotBase,
> = Readonly<{
  state: ProjectAdministrationState;
  scope: ProjectAdministrationScope;
  snapshot: TSnapshot | null;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
}>;

export function buildProjectAdministrationBase<
  TSnapshot extends ProjectAdministrationSnapshotBase,
>(
  routeId: string,
  input: ProjectAdministrationPresentationState<TSnapshot>,
  items: readonly ProjectAdministrationItem[],
): ProjectAdministrationViewModelBase {
  return Object.freeze({
    routeId,
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: input.snapshot?.allowedActions ?? Object.freeze([]),
    items: Object.freeze([...items]),
  });
}
