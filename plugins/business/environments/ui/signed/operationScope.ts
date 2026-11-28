// Each signed document and its capability port share a single release and authenticated scope.
const lifetime = new AbortController();
const scope = { owner: {}, available: true };
window.addEventListener('pagehide', () => lifetime.abort(), { once: true });
export const getWebOperationAvailabilityV2 = () => scope;
export function subscribeWebOperationAvailabilityV2(listener: () => void) {
  lifetime.signal.addEventListener('abort', listener);
  return () => lifetime.signal.removeEventListener('abort', listener);
}
export class WebOperationCleanupErrorV2 extends AggregateError {}
type Operation = {
  owner: object;
  signal: AbortSignal;
  check(): void;
  runChild<T>(work: (op: Operation) => Promise<T>): Promise<T>;
};
export async function runWebOperationV2<T>(
  work: (operation: Operation) => Promise<T>,
  options: { parent?: Operation; signal?: AbortSignal } = {}
): Promise<T> {
  const signals = [lifetime.signal, options.signal, options.parent?.signal].filter(
    (s): s is AbortSignal => !!s
  );
  const signal = AbortSignal.any(signals);
  const check = () => signal.throwIfAborted();
  const operation: Operation = {
    owner: scope.owner,
    signal,
    check,
    runChild: (child) => runWebOperationV2(child, { signal }),
  };
  check();
  return work(operation);
}
