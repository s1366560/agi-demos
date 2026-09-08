import type { NativeMemoriesAuthority } from './nativeMemoriesController';
import type {
  NativeKnowledgeClient,
  NativeKnowledgeCommand,
  NativeKnowledgeOperation,
  NativeKnowledgeScope,
} from './nativeKnowledgeContracts';

/** One immutable renderer binding; an obsolete binding can never publish a late response. */
export function createNativeKnowledgeUiSession(
  client: NativeKnowledgeClient,
  input: NativeMemoriesAuthority,
) {
  const authority = Object.freeze({
    ...input,
    scope: Object.freeze({ ...input.scope }),
  });
  const allowedActions: readonly string[] = Object.freeze(
    authority.available &&
      authority.scope.authority === 'local' &&
      authority.userId &&
      authority.sessionId &&
      authority.generationDigest &&
      Number.isSafeInteger(authority.contextRevision) &&
      Number(authority.contextRevision) >= 0
      ? [...input.allowedActions]
      : [],
  );
  let epoch = 0;
  let stopped = false;
  let active: AbortController | null = null;
  const allowed = (operation: NativeKnowledgeOperation) =>
    !stopped && allowedActions.includes(operation);
  const cancel = () => {
    epoch += 1;
    active?.abort();
    active = null;
  };
  const begin = () => {
    cancel();
    active = new AbortController();
    return { epoch, signal: active.signal };
  };
  const current = (request: ReturnType<typeof begin>) =>
    !stopped && request.epoch === epoch && !request.signal.aborted;
  const execute = async <C extends NativeKnowledgeCommand>(
    command: C,
    request: ReturnType<typeof begin>,
    expectedScope?: NativeKnowledgeScope,
  ) => {
    if (!allowed(command.operation)) throw Object.assign(new Error('forbidden'), { status: 403 });
    if (
      !expectedScope &&
      [
        'create',
        'update',
        'delete',
        'sync_link',
        'resolve_pull',
        'resolve_push',
        'resume_resolution',
        'reconcile_resolution',
      ].includes(command.operation)
    ) {
      throw Object.assign(new Error('project_knowledge_scope_conflict'), {
        status: 409,
      });
    }
    const boundScope =
      expectedScope ??
      (await client.observeScope(authority.scope, {
        expectedActorId: authority.userId!,
        signal: request.signal,
      }));
    if (!current(request)) throw new Error('request_cancelled');
    if (
      boundScope.tenant_id !== authority.scope.tenantId ||
      boundScope.project_id !== authority.scope.projectId ||
      boundScope.context_revision !== authority.contextRevision ||
      boundScope.digest !== authority.generationDigest
    ) {
      throw Object.assign(new Error('project_knowledge_scope_conflict'), {
        status: 409,
      });
    }
    const response = await client.execute(authority.scope, command, {
      signal: request.signal,
      expectedScope: boundScope,
    });
    if (!current(request)) throw new Error('request_cancelled');
    if (
      response.scope.tenant_id !== authority.scope.tenantId ||
      response.scope.project_id !== authority.scope.projectId ||
      response.scope.context_revision !== authority.contextRevision ||
      response.scope.profile_id !== boundScope.profile_id ||
      response.scope.generation !== boundScope.generation ||
      response.scope.digest !== boundScope.digest
    ) {
      throw Object.assign(new Error('project_knowledge_scope_conflict'), {
        status: 409,
      });
    }
    return response;
  };
  return Object.freeze({
    allowedActions,
    allowed,
    begin,
    current,
    execute,
    cancel,
    stop: () => {
      stopped = true;
      cancel();
    },
    activate: () => {
      stopped = false;
    },
  });
}

export function nativeKnowledgeUiFailure(error: unknown) {
  const status = error && typeof error === 'object' && 'status' in error ? error.status : 0;
  const message = error instanceof Error ? error.message : '';
  if (
    [
      'project_knowledge_scope_conflict',
      'knowledge_generation_mismatch',
      'knowledge_scope_mismatch',
    ].includes(message)
  )
    return 'contextChanged' as const;
  if (status === 409) return 'conflict' as const;
  if ([400, 401, 403, 404, 422].includes(Number(status))) return 'failed' as const;
  return 'uncertain' as const;
}
