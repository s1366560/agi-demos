export function requireActiveWorkbenchSnapshotV2(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException('Workbench snapshot cancelled', 'AbortError');
}

export async function settleWorkbenchSnapshotBranchesV2<T extends readonly unknown[]>(
  branches: T,
  signal?: AbortSignal,
): Promise<{ -readonly [P in keyof T]: Awaited<T[P]> }> {
  const results = await Promise.allSettled(branches);
  requireActiveWorkbenchSnapshotV2(signal);
  const rejected = results.find((result) => result.status === 'rejected');
  if (rejected?.status === 'rejected') throw rejected.reason;
  return results.map((result) => (result as PromiseFulfilledResult<unknown>).value) as {
    -readonly [P in keyof T]: Awaited<T[P]>;
  };
}

export function createWorkbenchSnapshotOperationTrackerV2() {
  const pending = new Set<Promise<unknown>>();
  let signal: AbortSignal | undefined;
  let active = false;
  let consumed = false;
  return {
    begin(nextSignal?: AbortSignal) {
      if (consumed) throw new Error('desktop_workbench_snapshot_binding_already_used');
      requireActiveWorkbenchSnapshotV2(nextSignal);
      signal = nextSignal;
      active = true;
      consumed = true;
    },
    wrap<T extends object>(operations: T): T {
      return Object.freeze(
        Object.fromEntries(
          Object.entries(operations).map(([name, method]) => [
            name,
            typeof method !== 'function'
              ? method
              : (...args: unknown[]) => {
                  if (!active)
                    return Promise.reject(new Error('desktop_workbench_snapshot_binding_inactive'));
                  try {
                    requireActiveWorkbenchSnapshotV2(signal);
                  } catch (error) {
                    return Promise.reject(error);
                  }
                  const operation = Promise.resolve().then(() => {
                    requireActiveWorkbenchSnapshotV2(signal);
                    return Reflect.apply(method, operations, args);
                  });
                  pending.add(operation);
                  void operation.then(
                    () => pending.delete(operation),
                    () => pending.delete(operation),
                  );
                  return operation;
                },
          ]),
        ),
      ) as T;
    },
    async drain() {
      while (pending.size) await Promise.allSettled([...pending]);
      active = false;
    },
  };
}
