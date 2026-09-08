import type { CloudMemoryRouteBinding } from './CloudMemoryRouteContext';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import type { ProjectMemory } from './projectMemoriesClient';
import { validCloudMemoryUiAuthority } from './cloudMemoryUiAuthority';

export function createProjectGraphMemoryReader(
  input: Readonly<{
    binding: CloudMemoryRouteBinding | null;
    scope: ProjectKnowledgeScope;
    contextRevision: number | null;
    memoryId: string;
  }>,
) {
  const sourceAuthority = input.binding?.authority;
  const authority = sourceAuthority
    ? Object.freeze({
        ...sourceAuthority,
        scope: Object.freeze({ ...sourceAuthority.scope }),
        allowedActions: Object.freeze([...sourceAuthority.allowedActions]),
      })
    : null;
  const scope = Object.freeze({ ...input.scope });
  const memoryId = input.memoryId;
  const client = input.binding?.client;
  const readable = Boolean(
    client &&
    authority &&
    validCloudMemoryUiAuthority(authority) &&
    authority.allowedActions.includes('view') &&
    authority.scope.authority === scope.authority &&
    authority.scope.tenantId === scope.tenantId &&
    authority.scope.projectId === scope.projectId &&
    authority.contextRevision === input.contextRevision &&
    memoryId,
  );
  type Model = Readonly<{
    state: 'idle' | 'loading' | 'ready' | 'unavailable';
    memory: ProjectMemory | null;
  }>;
  let model: Model = Object.freeze({ state: readable ? 'idle' : 'unavailable', memory: null });
  let request: AbortController | null = null;
  let stopped = false;
  const listeners = new Set<() => void>();
  const emit = (next: Model) => {
    model = Object.freeze(next);
    for (const listener of [...listeners]) listener();
  };
  const load = async () => {
    if (!readable || stopped || model.state === 'loading') return;
    const active = new AbortController();
    request?.abort();
    request = active;
    emit({ state: 'loading', memory: null });
    try {
      const response = await client!.execute(
        scope,
        { operation: 'get', id: memoryId },
        {
          expectedActorId: authority!.actorId!,
          expectedContextRevision: authority!.contextRevision!,
          signal: active.signal,
        },
      );
      if (stopped || request !== active || active.signal.aborted) return;
      if (response.result.id !== memoryId || response.result.projectId !== scope.projectId)
        throw new Error('project_graph_memory_scope_conflict');
      emit({ state: 'ready', memory: response.result });
    } catch {
      if (!stopped && request === active && !active.signal.aborted)
        emit({ state: 'unavailable', memory: null });
    }
  };
  return Object.freeze({
    getSnapshot: () => model,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    load,
    activate: () => {
      stopped = false;
    },
    stop: () => {
      stopped = true;
      request?.abort();
      request = null;
    },
  });
}
