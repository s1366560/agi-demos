import {
  RendererGenerationStatusStoreV2,
  RendererPluginRuntimeV2,
  WebPublicViewReconcilerV2,
  startRendererGenerationPollingV2,
} from '@agistack/plugin-runtime';

/** One runtime serializes identity retirement before admitting its replacement view. */
export class WebPublicViewIdentityV2 {
  private epoch = 0;
  private stop: (() => void) | undefined;
  private reconciler: WebPublicViewReconcilerV2 | undefined;
  private tail: Promise<void> = Promise.resolve();
  private ready = false;
  private requested = false;
  private readonly listeners = new Set<() => void>();

  constructor(
    private readonly runtime: RendererPluginRuntimeV2,
    private readonly status: RendererGenerationStatusStoreV2,
    private readonly admit: (ready: boolean) => void,
    private readonly closeFailed: (error: unknown) => void
  ) {}

  readonly getSnapshot = (): boolean => this.ready;
  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  replace(
    source?: (signal: AbortSignal) => Promise<unknown | null>,
    interval = 30_000
  ): Promise<void> {
    const epoch = ++this.epoch;
    this.requested = source !== undefined;
    this.stop?.();
    this.stop = undefined;
    this.publish(false);
    this.status.begin(false);
    const previous = this.reconciler;
    this.reconciler = undefined;
    const next = this.tail.then(async () => {
      if (previous) await previous.close();
      if (epoch !== this.epoch || !source) return;
      const reconciler = new WebPublicViewReconcilerV2(this.runtime);
      this.reconciler = reconciler;
      this.stop = startRendererGenerationPollingV2({
        runtime: this.runtime,
        source,
        statusStore: this.status,
        pollIntervalMs: interval,
        apply: async (payload) => {
          await reconciler.apply(payload);
          if (epoch === this.epoch) this.publish(true);
          return undefined;
        },
      });
    });
    this.tail = next.catch((error: unknown) => {
      this.closeFailed(error);
      if (epoch === this.epoch || !this.requested) this.status.fail(error, false);
    });
    return this.tail;
  }

  private publish(ready: boolean): void {
    this.admit(ready);
    if (this.ready === ready) return;
    this.ready = ready;
    for (const listener of this.listeners) listener();
  }
}
