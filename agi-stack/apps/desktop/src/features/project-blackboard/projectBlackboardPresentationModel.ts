import type {
  ProjectBlackboardAuthority,
  ProjectBlackboardScope,
  ProjectBlackboardSnapshot,
} from './projectBlackboardClient';
import type { WorkspaceCollaborationClient } from '../workspace/workspaceCollaborationClient';

export type ProjectBlackboardPresentationInput =
  | Readonly<{
      kind: 'loading';
      scope: ProjectBlackboardScope;
      scopeSwitch: boolean;
    }>
  | Readonly<{ kind: 'snapshot'; snapshot: ProjectBlackboardSnapshot }>
  | Readonly<{
      kind: 'failure';
      scope: ProjectBlackboardScope;
      state: 'error' | 'forbidden' | 'unavailable';
      reasonCode: string;
      retryable: boolean;
    }>;

export type ProjectBlackboardViewModel = Readonly<{
  state:
    | 'loading'
    | 'scope_switch'
    | 'ready'
    | 'degraded'
    | 'error'
    | 'forbidden'
    | 'unavailable';
  scope: ProjectBlackboardScope;
  authority: ProjectBlackboardAuthority;
  reasonCode: string | null;
  retryVisible: boolean;
  initialSurface: 'goals' | 'status';
  collaborationClient: WorkspaceCollaborationClient | null;
}>;

export function buildProjectBlackboardPresentation(
  input: ProjectBlackboardPresentationInput,
): ProjectBlackboardViewModel {
  if (input.kind === 'snapshot') {
    return Object.freeze({
      state: input.snapshot.availability === 'degraded' ? 'degraded' : 'ready',
      scope: input.snapshot.scope,
      authority: input.snapshot.authority,
      reasonCode: input.snapshot.reasonCode,
      retryVisible: false,
      initialSurface: input.snapshot.initialSurface === 'status' ? 'status' : 'goals',
      collaborationClient: input.snapshot.collaborationClient,
    });
  }
  if (input.kind === 'loading') {
    return terminalModel(
      input.scope,
      input.scopeSwitch ? 'scope_switch' : 'loading',
      null,
      false,
    );
  }
  return terminalModel(
    input.scope,
    input.state,
    input.reasonCode,
    input.retryable,
  );
}

function terminalModel(
  scope: ProjectBlackboardScope,
  state: Extract<
    ProjectBlackboardViewModel['state'],
    'loading' | 'scope_switch' | 'error' | 'forbidden' | 'unavailable'
  >,
  reasonCode: string | null,
  retryVisible: boolean,
): ProjectBlackboardViewModel {
  return Object.freeze({
    state,
    scope,
    authority: scope.authority,
    reasonCode,
    retryVisible,
    initialSurface: scope.authority === 'local' ? 'status' : 'goals',
    collaborationClient: null,
  });
}
