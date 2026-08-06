import type {
  ProjectKnowledgeScope,
  ProjectKnowledgeSnapshotBase,
} from './projectKnowledgeClient';

export type ProjectKnowledgeItem = Readonly<{
  id: string;
  title: string;
  detail: string | null;
  kind: string;
}>;
export type ProjectKnowledgeViewModel = Readonly<{
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
  scope: ProjectKnowledgeScope;
  reasonCode: string | null;
  retryVisible: boolean;
  allowedActions: readonly string[];
  items: readonly ProjectKnowledgeItem[];
  total: number;
}>;
export type ProjectKnowledgePresentationInput<TSnapshot extends ProjectKnowledgeSnapshotBase> =
  | Readonly<{ kind: 'loading'; scope: ProjectKnowledgeScope; scopeSwitch: boolean }>
  | Readonly<{ kind: 'snapshot'; snapshot: TSnapshot }>
  | Readonly<{
      kind: 'failure';
      scope: ProjectKnowledgeScope;
      state: 'error' | 'forbidden' | 'unavailable';
      reasonCode: string;
      retryable: boolean;
    }>;

export function buildProjectKnowledgePresentation<TSnapshot extends ProjectKnowledgeSnapshotBase>(
  routeId: string,
  input: ProjectKnowledgePresentationInput<TSnapshot>,
  project: (
    snapshot: TSnapshot,
  ) => Readonly<{ items: readonly ProjectKnowledgeItem[]; total: number }>,
): ProjectKnowledgeViewModel {
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
    });
  }
  return Object.freeze({
    routeId,
    state:
      input.kind === 'loading'
        ? input.scopeSwitch
          ? 'scope_switch'
          : 'loading'
        : input.state,
    scope: input.scope,
    reasonCode: input.kind === 'failure' ? input.reasonCode : null,
    retryVisible: input.kind === 'failure' && input.retryable,
    allowedActions: Object.freeze([]),
    items: Object.freeze([]),
    total: 0,
  });
}
