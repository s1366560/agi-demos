import type { ComputerUseOperation, ComputerUseSnapshot } from '../../api/computerUseClientV2';

type Request = {
  controller: AbortController;
  priority: number;
};

type ManagementCallbacks = {
  run: (operation: ComputerUseOperation, signal: AbortSignal) => Promise<ComputerUseSnapshot>;
  changed: (busy: boolean, stopping: boolean) => void;
  completed: (snapshot: ComputerUseSnapshot) => void;
  failed: (error: string) => void;
};

/** Safety stops may supersede requests; full Stop also supersedes recording export. */
export function createComputerUseManagement(callbacks: ManagementCallbacks) {
  let active: Request | null = null;
  let generation = 0;
  return {
    generation: () => generation,
    acceptsRefresh: (startedAt: number) => active === null && startedAt === generation,
    async manage(operation: ComputerUseOperation): Promise<void> {
      const stopping = operation.action === 'stop' || operation.action === 'stop_all';
      const priority = stopping ? 2 : operation.action === 'audio_stop' ? 1 : 0;
      if (active && priority <= active.priority) return;
      const previous = active;
      const request = { controller: new AbortController(), priority };
      active = request;
      generation++;
      previous?.controller.abort();
      callbacks.changed(true, stopping);
      try {
        const snapshot = await callbacks.run(operation, request.controller.signal);
        if (active === request && !request.controller.signal.aborted) callbacks.completed(snapshot);
      } catch (error) {
        if (active === request && !request.controller.signal.aborted)
          callbacks.failed(error instanceof Error ? error.message : 'cua_operation_failed');
      } finally {
        if (active === request) {
          active = null;
          generation++;
          callbacks.changed(false, false);
        }
      }
    },
    dispose() {
      const previous = active;
      active = null;
      generation++;
      previous?.controller.abort();
    },
  };
}

/** A pushed activity snapshot supersedes any earlier in-flight renderer refresh. */
export function createComputerUseSnapshotUpdates(callbacks: {
  completed: (snapshot: ComputerUseSnapshot) => void;
  failed: (error: unknown) => void;
}) {
  let revision = 0;
  let closed = false;
  return {
    refresh() {
      const started = revision;
      return {
        completed(snapshot: ComputerUseSnapshot) {
          if (!closed && started === revision) callbacks.completed(snapshot);
        },
        failed(error: unknown) {
          if (!closed && started === revision) callbacks.failed(error);
        },
      };
    },
    activity(snapshot: ComputerUseSnapshot) {
      if (closed) return;
      revision++;
      callbacks.completed(snapshot);
    },
    dispose() {
      closed = true;
      revision++;
    },
  };
}
