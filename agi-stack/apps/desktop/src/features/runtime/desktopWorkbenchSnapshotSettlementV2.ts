import type { DesktopCapabilitySnapshot } from './capabilitySnapshot';

function traceCapabilitySnapshot(message: string): void {
  const env = (globalThis as { process?: { env?: { NODE_ENV?: string } } }).process?.env
    ?.NODE_ENV;
  if (env === 'production') return;
  console.info(message);
}

export async function runCriticalWorkbenchSnapshotPhase<TCritical, TRemaining>(input: {
  critical: () => Promise<TCritical>;
  remaining: (critical: TCritical) => Promise<TRemaining>;
  project: (critical: TCritical, remaining: TRemaining | undefined) => DesktopCapabilitySnapshot;
  observe?: (snapshot: DesktopCapabilitySnapshot) => void;
}): Promise<DesktopCapabilitySnapshot> {
  const critical = await input.critical();
  input.observe?.(input.project(critical, undefined));
  const remaining = await input.remaining(critical);
  return input.project(critical, remaining);
}

export function requireActiveWorkbenchSnapshotV2(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException('Workbench snapshot cancelled', 'AbortError');
}

export async function settleWorkbenchSnapshotBranchesLimitedV2<
  const T extends readonly (() => Promise<unknown>)[],
>(
  start: T,
  limit: number,
  signal?: AbortSignal,
  names?: readonly string[],
): Promise<{ -readonly [Index in keyof T]: Awaited<ReturnType<T[Index]>> }> {
  const results: unknown[] = new Array(start.length);
  let cursor = 0;
  let failure: unknown;
  const worker = async () => {
    while (cursor < start.length && failure === undefined) {
      requireActiveWorkbenchSnapshotV2(signal);
      const index = cursor;
      cursor += 1;
      const started = performance.now();
      const name = names?.[index] ?? String(index);
      try {
        results[index] = await start[index]();
        traceCapabilitySnapshot(
          `[desktop-capability-snapshot] ${name} ok ${Math.round(performance.now() - started)}ms`,
        );
      } catch (error) {
        traceCapabilitySnapshot(
          `[desktop-capability-snapshot] ${name} fail ${Math.round(performance.now() - started)}ms`,
        );
        failure ??= error;
      }
    }
  };
  const workers = Array.from({ length: Math.min(Math.max(limit, 1), start.length) }, () => worker());
  await Promise.all(workers);
  requireActiveWorkbenchSnapshotV2(signal);
  if (failure !== undefined) throw failure;
  return results as { -readonly [Index in keyof T]: Awaited<ReturnType<T[Index]>> };
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
