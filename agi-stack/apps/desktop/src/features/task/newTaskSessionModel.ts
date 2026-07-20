import type {
  CreateTaskSessionRequest,
  DesktopRuntimeConfig,
  RuntimeNodeState,
  WorkspaceAuthorityCollection,
  WorkspaceSummary,
} from '../../types';
import { canonicalJsonSha256 } from '../session/canonicalJsonDigest';
import type { NewTaskDefinition } from './newTaskPlanModel';

export const NEW_WORKSPACE_VALUE = '__new_workspace__';

const TASK_SESSION_CREATION_ATTEMPT_KEY_PREFIX =
  'memstack.desktop.task-session-creation.v1:';
const SHA256_FINGERPRINT_PATTERN = /^sha256:[a-f0-9]{64}$/;

export type TaskSessionCreationAttempt = {
  schemaVersion: 1;
  fingerprint: string;
  idempotencyKey: string;
  createdAt: number;
};

export type TaskSessionCreationStorage = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
};

export function resolveNewTaskWorkspaceAuthority(
  projectState: RuntimeNodeState | undefined,
  workspaces: WorkspaceSummary[],
): WorkspaceAuthorityCollection<WorkspaceSummary> {
  if (!projectState) return { status: 'unavailable', items: workspaces, error: null };
  if (projectState.loading) return { status: 'loading', items: workspaces, error: null };
  if (projectState.error) {
    return { status: 'error', items: workspaces, error: projectState.error };
  }
  return { status: 'ready', items: workspaces, error: null };
}

export function canUseNewTaskWorkspaceSelection(
  authority: WorkspaceAuthorityCollection<WorkspaceSummary>,
  workspaceSelection: string,
): boolean {
  if (authority.status !== 'ready') return false;
  if (workspaceSelection === NEW_WORKSPACE_VALUE) return true;
  return authority.items.some((workspace) => workspace.id === workspaceSelection);
}

export function newTaskWorkspaceLabel(
  sessionWorkspace: WorkspaceSummary | null,
  selectedWorkspace: WorkspaceSummary | null,
  workspaceSelection: string,
  newWorkspaceLabel: string,
): string {
  return (
    sessionWorkspace?.name ||
    sessionWorkspace?.title ||
    selectedWorkspace?.name ||
    selectedWorkspace?.title ||
    (workspaceSelection === NEW_WORKSPACE_VALUE ? newWorkspaceLabel : workspaceSelection)
  );
}

export function resolveTaskSessionConflictWorkspace(
  workspaces: WorkspaceSummary[],
  taskTitle: string,
): WorkspaceSummary | null {
  const expectedName = taskTitle.trim();
  if (!expectedName) return null;
  const matches = workspaces.filter(
    (workspace) =>
      workspace.is_archived === false && workspace.name === expectedName,
  );
  return matches.length === 1 ? matches[0] : null;
}

export function taskSessionCreationAttempt(
  current: TaskSessionCreationAttempt | null,
  fingerprint: string,
  createIdempotencyKey: () => string,
  createdAt = Date.now(),
): TaskSessionCreationAttempt {
  if (current?.fingerprint === fingerprint) return current;
  return {
    schemaVersion: 1,
    fingerprint,
    idempotencyKey: createIdempotencyKey(),
    createdAt,
  };
}

export function taskSessionCreationFingerprint(
  config: Pick<
    DesktopRuntimeConfig,
    'apiBaseUrl' | 'mode' | 'tenantId' | 'projectId'
  >,
  actorId: string | null | undefined,
  definition: NewTaskDefinition,
  workspaceSelection: string,
): string {
  const apiBaseUrl = normalizeTaskSessionApiBaseUrl(config.apiBaseUrl);
  const normalizedActorId = actorId?.trim() ?? '';
  if (
    !apiBaseUrl ||
    !normalizedActorId ||
    !config.tenantId.trim() ||
    !config.projectId.trim()
  ) {
    return '';
  }
  const request = buildLocalTaskSessionRequest(
    definition,
    workspaceSelection,
    'fingerprint-placeholder',
  );
  const digest = canonicalJsonSha256({
    runtime: {
      apiBaseUrl,
      mode: config.mode,
      tenantId: config.tenantId.trim(),
      projectId: config.projectId.trim(),
      actorId: normalizedActorId,
    },
    workspace: request.workspace,
    conversation: request.conversation,
    initial_message: request.initial_message,
  });
  return digest ? `sha256:${digest}` : '';
}

export function browserTaskSessionCreationStorage(): TaskSessionCreationStorage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function writeTaskSessionCreationAttempt(
  storage: TaskSessionCreationStorage | null,
  attempt: TaskSessionCreationAttempt,
): boolean {
  if (!storage || !isValidTaskSessionCreationAttempt(attempt)) return false;
  try {
    const serialized = JSON.stringify(attempt);
    const key = taskSessionCreationAttemptStorageKey(attempt.fingerprint);
    storage.setItem(key, serialized);
    return storage.getItem(key) === serialized;
  } catch {
    return false;
  }
}

export function readTaskSessionCreationAttempt(
  storage: TaskSessionCreationStorage | null,
  fingerprint: string,
): TaskSessionCreationAttempt | null {
  if (!storage || !SHA256_FINGERPRINT_PATTERN.test(fingerprint)) return null;
  const key = taskSessionCreationAttemptStorageKey(fingerprint);
  try {
    const serialized = storage.getItem(key);
    if (!serialized) return null;
    const candidate = JSON.parse(serialized) as Partial<TaskSessionCreationAttempt>;
    if (
      !isValidTaskSessionCreationAttempt(candidate) ||
      candidate.fingerprint !== fingerprint
    ) {
      storage.removeItem(key);
      return null;
    }
    return candidate;
  } catch {
    try {
      storage.removeItem(key);
    } catch {
      // Recovery remains fail-closed when corrupt storage cannot be removed.
    }
    return null;
  }
}

export function clearTaskSessionCreationAttempt(
  storage: TaskSessionCreationStorage | null,
  fingerprint: string,
): boolean {
  if (!storage || !SHA256_FINGERPRINT_PATTERN.test(fingerprint)) return false;
  try {
    const key = taskSessionCreationAttemptStorageKey(fingerprint);
    storage.removeItem(key);
    return storage.getItem(key) === null;
  } catch {
    return false;
  }
}

export function buildLocalTaskSessionRequest(
  definition: NewTaskDefinition,
  workspaceSelection: string,
  idempotencyKey: string,
): CreateTaskSessionRequest {
  const title = definition.title.trim();
  const objective = definition.objective.trim();
  const workspaceRoot = definition.workspaceRoot?.trim() ?? '';
  const workspace =
    workspaceSelection === NEW_WORKSPACE_VALUE
      ? {
          kind: 'create' as const,
          name: title,
          description: objective,
          metadata: { source: 'desktop' },
          use_case: definition.kind,
          collaboration_mode: 'multi_agent_shared' as const,
          ...(definition.kind === 'programming' && workspaceRoot
            ? { sandbox_code_root: workspaceRoot }
            : {}),
        }
      : {
          kind: 'existing' as const,
          workspace_id: workspaceSelection,
        };

  return {
    idempotency_key: idempotencyKey,
    workspace,
    conversation: {
      title,
      capability_mode: definition.kind === 'programming' ? 'code' : 'work',
    },
    initial_message: { content: objective },
  };
}

function normalizeTaskSessionApiBaseUrl(value: string): string {
  try {
    const url = new URL(value.trim());
    if (
      (url.protocol !== 'http:' && url.protocol !== 'https:') ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      return '';
    }
    const path = url.pathname.replace(/\/+$/, '') || '/';
    return `${url.origin.toLowerCase()}${path}`;
  } catch {
    return '';
  }
}

function taskSessionCreationAttemptStorageKey(fingerprint: string): string {
  return `${TASK_SESSION_CREATION_ATTEMPT_KEY_PREFIX}${fingerprint}`;
}

function isValidTaskSessionCreationAttempt(
  value: Partial<TaskSessionCreationAttempt>,
): value is TaskSessionCreationAttempt {
  return (
    value.schemaVersion === 1 &&
    typeof value.fingerprint === 'string' &&
    SHA256_FINGERPRINT_PATTERN.test(value.fingerprint) &&
    typeof value.idempotencyKey === 'string' &&
    value.idempotencyKey.trim().length > 0 &&
    value.idempotencyKey.length <= 255 &&
    Number.isSafeInteger(value.createdAt) &&
    (value.createdAt as number) > 0
  );
}
