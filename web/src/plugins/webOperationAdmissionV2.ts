import {
  WEB_RENDERER_HOST_SERVICE_V2,
  type GenerationLeaseV2,
  type RendererPluginRuntimeV2,
  type RuntimeGenerationV2,
} from '@agistack/plugin-runtime';

export interface WebOperationContextV2 {
  readonly signal: AbortSignal;
  readonly generation: RuntimeGenerationV2;
  readonly owner: object;
  check(): void;
  runChild<T>(work: (operation: WebOperationContextV2) => Promise<T>): Promise<T>;
}
export interface WebOperationAvailabilityV2 {
  readonly owner: object;
  readonly available: boolean;
}
export interface WebOperationOptionsV2 {
  readonly signal?: AbortSignal;
  readonly parent?: WebOperationContextV2;
}
interface OperationState {
  readonly lease: GenerationLeaseV2;
  readonly controller: AbortController;
  readonly children: Set<Promise<unknown>>;
  active: boolean;
  cleanupFailed?: boolean;
  cleanupFailure?: unknown;
}
const operationStates = new WeakMap<WebOperationContextV2, OperationState>();
const cancelled = () => new DOMException('Web operation cancelled', 'AbortError');

/** The kernel owns admission; business transports never acquire a different generation mid-call. */
export class WebOperationAdmissionV2 {
  private enabled = false;
  private owner: object = Object.freeze({});
  private generation: RuntimeGenerationV2 | undefined;
  private closed = false;
  private closing: Promise<void> | undefined;
  private readonly pending = new Map<OperationState, Promise<unknown>>();
  private readonly unsubscribe: () => void;
  private readonly listeners = new Set<() => void>();
  private availability: WebOperationAvailabilityV2 = Object.freeze({
    owner: this.owner,
    available: false,
  });

  readonly getSnapshot = (): WebOperationAvailabilityV2 => this.availability;
  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private publishAvailability(): void {
    const available = this.enabled && !this.closed && this.generation !== undefined;
    if (this.availability.owner === this.owner && this.availability.available === available) return;
    this.availability = Object.freeze({ owner: this.owner, available });
    for (const listener of [...this.listeners]) listener();
  }

  constructor(
    private readonly runtime: Pick<RendererPluginRuntimeV2, 'acquire' | 'getSnapshot' | 'subscribe'>
  ) {
    this.generation = runtime.getSnapshot();
    this.unsubscribe = runtime.subscribe(() => this.refreshGeneration());
  }

  setEnabled(enabled: boolean): void {
    if (this.closed && enabled) throw new Error('web_operation_admission_closed');
    if (this.enabled === enabled) return;
    this.enabled = enabled;
    if (!enabled) this.invalidate();
    else this.publishAvailability();
  }

  invalidate(): void {
    this.owner = Object.freeze({});
    for (const state of this.pending.keys()) state.controller.abort();
    this.publishAvailability();
  }

  close(): Promise<void> {
    if (this.closing) return this.closing;
    this.closed = true;
    this.setEnabled(false);
    this.unsubscribe();
    const states = [...this.pending.keys()];
    this.closing = Promise.allSettled([...this.pending.values()]).then(() => {
      const failures = states
        .filter((state) => state.cleanupFailed)
        .map((state) => state.cleanupFailure);
      if (failures.length > 0) throw new AggregateError(failures, 'Web operation cleanup failed');
    });
    return this.closing;
  }

  private refreshGeneration(): void {
    const current = this.runtime.getSnapshot();
    if (current === this.generation) return;
    this.generation = current;
    this.owner = Object.freeze({});
    for (const state of this.pending.keys()) {
      if (state.lease.generation !== current) state.controller.abort();
    }
    this.publishAvailability();
  }

  run<T>(
    work: (operation: WebOperationContextV2) => Promise<T>,
    options: WebOperationOptionsV2 = {}
  ): Promise<T> {
    try {
      this.refreshGeneration();
      if (options.signal?.aborted) throw cancelled();
      if (!this.enabled) throw new Error('web_operation_generation_unavailable');
      const parent = options.parent ? operationStates.get(options.parent) : undefined;
      if (options.parent) {
        if (!parent || !this.pending.has(parent)) throw new Error('web_operation_parent_invalid');
        options.parent.check();
      }
      const lease = parent ? parent.lease.fork() : this.runtime.acquire();
      const controller = new AbortController();
      const sources = [options.signal, options.parent?.signal].filter(
        (value): value is AbortSignal => value !== undefined
      );
      const abort = () => controller.abort();
      for (const source of sources) {
        if (source.aborted) controller.abort();
        source.addEventListener('abort', abort, { once: true });
      }
      const state: OperationState = { lease, controller, children: new Set(), active: true };
      const context: WebOperationContextV2 = Object.freeze({
        signal: controller.signal,
        generation: lease.generation,
        owner: options.parent?.owner ?? this.owner,
        check: () => {
          if (!state.active || controller.signal.aborted) throw cancelled();
        },
        runChild: <R>(child: (operation: WebOperationContextV2) => Promise<R>) =>
          this.run(child, { parent: context }),
      });
      operationStates.set(context, state);
      const task = Promise.resolve().then(async () => {
        let failed = false;
        let failure: unknown;
        let result!: T;
        try {
          context.check();
          // An enabled production host is structural authority, not a URL/intent classifier.
          const host = lease.generation.resolve<{ target: string }>(
            WEB_RENDERER_HOST_SERVICE_V2,
            { kind: 'root' },
            { version: '1.0.0' }
          );
          if (host.target !== 'web') throw new Error('web_operation_host_invalid');
          result = await work(context);
          context.check();
        } catch (error) {
          failed = true;
          failure = error;
        }
        state.active = false;
        // Children admitted before the parent returned still own their pinned leases.
        await Promise.allSettled([...state.children]);
        try {
          await lease.release();
          if (!failed && controller.signal.aborted) {
            failed = true;
            failure = cancelled();
          }
        } catch (error) {
          state.cleanupFailed = true;
          state.cleanupFailure = error;
          if (failed && failure instanceof DOMException && failure.name === 'AbortError') {
            failure = new AggregateError([failure, error], 'Web operation cleanup failed');
          } else if (!failed) {
            failed = true;
            failure = controller.signal.aborted
              ? new AggregateError([cancelled(), error], 'Web operation cleanup failed')
              : error;
          }
        } finally {
          for (const source of sources) source.removeEventListener('abort', abort);
          this.pending.delete(state);
        }
        if (failed) throw failure;
        return result;
      });
      this.pending.set(state, task);
      if (parent) {
        parent.children.add(task);
        void task.finally(() => parent.children.delete(task)).catch(() => undefined);
      }
      return task;
    } catch (error) {
      return Promise.reject(error);
    }
  }
}

let installed: WebOperationAdmissionV2 | undefined;
const availabilityListeners = new Set<() => void>();
const unavailable: WebOperationAvailabilityV2 = Object.freeze({
  owner: Object.freeze({}),
  available: false,
});
export function getWebOperationAvailabilityV2(): WebOperationAvailabilityV2 {
  return installed?.getSnapshot() ?? unavailable;
}
export function subscribeWebOperationAvailabilityV2(listener: () => void): () => void {
  availabilityListeners.add(listener);
  return () => availabilityListeners.delete(listener);
}
function notifyAvailability(): void {
  for (const listener of [...availabilityListeners]) listener();
}
export function installWebOperationAdmissionV2(admission: WebOperationAdmissionV2): () => void {
  if (installed) throw new Error('web_operation_admission_already_installed');
  installed = admission;
  const unsubscribe = admission.subscribe(notifyAvailability);
  notifyAvailability();
  return () => {
    unsubscribe();
    if (installed === admission) {
      installed = undefined;
      notifyAvailability();
    }
  };
}
export function runWebOperationV2<T>(
  work: (operation: WebOperationContextV2) => Promise<T>,
  options?: WebOperationOptionsV2
): Promise<T> {
  if (!installed) return Promise.reject(new Error('web_operation_generation_unavailable'));
  return installed.run(work, options);
}
