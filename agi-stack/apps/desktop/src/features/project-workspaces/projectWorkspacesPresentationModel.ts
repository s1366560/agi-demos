import type {
  ProjectWorkspacesAuthority,
  ProjectWorkspacesScope,
  ProjectWorkspacesSnapshot,
} from './projectWorkspacesClient';

export type ProjectWorkspacesPresentationInput =
  | Readonly<{
      kind: 'loading';
      scope: ProjectWorkspacesScope;
      scopeSwitch: boolean;
    }>
  | Readonly<{ kind: 'snapshot'; snapshot: ProjectWorkspacesSnapshot }>
  | Readonly<{
      kind: 'failure';
      scope: ProjectWorkspacesScope;
      state: 'error' | 'forbidden' | 'unavailable';
      reasonCode: string;
      retryable: boolean;
    }>;

export type ProjectWorkspacesViewModel = Readonly<{
  state:
    | 'loading'
    | 'scope_switch'
    | 'ready'
    | 'degraded'
    | 'empty'
    | 'error'
    | 'forbidden'
    | 'unavailable';
  scope: ProjectWorkspacesScope;
  authority: ProjectWorkspacesAuthority;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  workspaces: ProjectWorkspacesSnapshot['workspaces'];
}>;

export function buildProjectWorkspacesPresentation(
  input: ProjectWorkspacesPresentationInput,
): ProjectWorkspacesViewModel {
  if (input.kind === 'loading') {
    return terminalModel(
      input.scope,
      input.scopeSwitch ? 'scope_switch' : 'loading',
      null,
      false,
    );
  }
  if (input.kind === 'failure') {
    return terminalModel(
      input.scope,
      input.state,
      input.reasonCode,
      input.retryable,
    );
  }
  const { snapshot } = input;
  return Object.freeze({
    state:
      snapshot.availability === 'degraded'
        ? 'degraded'
        : snapshot.workspaces.length === 0
          ? 'empty'
          : 'ready',
    scope: snapshot.scope,
    authority: snapshot.authority,
    reasonCode: snapshot.reasonCode,
    retryVisible: false,
    busyAction: null,
    allowedActions: snapshot.allowedActions,
    workspaces: snapshot.workspaces,
  });
}

export function withProjectWorkspacesBusyAction(
  model: ProjectWorkspacesViewModel,
  busyAction: string | null,
): ProjectWorkspacesViewModel {
  return Object.freeze({ ...model, busyAction });
}

function terminalModel(
  scope: ProjectWorkspacesScope,
  state: Extract<
    ProjectWorkspacesViewModel['state'],
    'loading' | 'scope_switch' | 'error' | 'forbidden' | 'unavailable'
  >,
  reasonCode: string | null,
  retryVisible: boolean,
): ProjectWorkspacesViewModel {
  return Object.freeze({
    state,
    scope,
    authority: scope.authority,
    reasonCode,
    retryVisible,
    busyAction: null,
    allowedActions: Object.freeze([]),
    workspaces: Object.freeze([]),
  });
}
