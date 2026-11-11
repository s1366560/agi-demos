function traceCapabilitySnapshot(message: string): void {
  if (typeof process !== 'undefined' && process.env.NODE_ENV === 'production') return;
  console.info(message);
}

export function requireActiveWorkbenchSnapshotV2(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException('Workbench snapshot cancelled', 'AbortError');
}

export async function settleWorkbenchSnapshotBranchesV2<T extends readonly unknown[]>(
  branches: T,
  signal?: AbortSignal,
  names?: readonly string[],
): Promise<{ -readonly [P in keyof T]: Awaited<T[P]> }> {
  const started = performance.now();
  const observed = branches.map((branch, index) => {
    const name = names?.[index] ?? String(index);
    return Promise.resolve(branch).then(
      (value) => {
        traceCapabilitySnapshot(
          `[desktop-capability-snapshot] ${name} ok ${Math.round(performance.now() - started)}ms`,
        );
        return value;
      },
      (error: unknown) => {
        traceCapabilitySnapshot(
          `[desktop-capability-snapshot] ${name} fail ${Math.round(performance.now() - started)}ms`,
        );
        throw error;
      },
    );
  }) as unknown as T;
  const results = await Promise.allSettled(observed);
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
