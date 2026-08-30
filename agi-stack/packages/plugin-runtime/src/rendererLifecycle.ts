import { RuntimeV2Error } from './errors';
import type { SnapshotApplyReceiptV2 } from './generated';
import type { RendererPluginRuntimeV2 } from './renderer';
import type { RuntimeGenerationV2 } from './runtime';

export type RendererGenerationStatusV2 = 'loading' | 'empty' | 'ready' | 'degraded' | 'error';

export interface RendererGenerationStatusSnapshotV2 {
  readonly status: RendererGenerationStatusV2;
  readonly error: unknown | undefined;
}

export type RendererPluginGenerationStateV2 =
  | Readonly<{ status: 'loading'; generation: undefined; error: undefined }>
  | Readonly<{ status: 'empty'; generation: undefined; error: undefined }>
  | Readonly<{
      status: 'ready';
      generation: RuntimeGenerationV2;
      error: undefined;
    }>
  | Readonly<{
      status: 'degraded';
      generation: RuntimeGenerationV2;
      error: unknown;
    }>
  | Readonly<{ status: 'error'; generation: undefined; error: unknown }>;

export type RendererPluginDistributionSourceV2 = (signal: AbortSignal) => Promise<unknown | null>;

export type RendererPluginDistributionApplyV2 = (
  payload: unknown
) => Promise<SnapshotApplyReceiptV2 | undefined>;

export interface StartRendererGenerationPollingOptionsV2 {
  readonly runtime: RendererPluginRuntimeV2;
  readonly source: RendererPluginDistributionSourceV2;
  readonly apply?: RendererPluginDistributionApplyV2;
  readonly statusStore: RendererGenerationStatusStoreV2;
  readonly bootstrap?: () => Promise<void>;
  readonly pollIntervalMs: number;
}

const LOADING_STATE_V2: RendererPluginGenerationStateV2 = Object.freeze({
  status: 'loading',
  generation: undefined,
  error: undefined,
});
const EMPTY_STATE_V2: RendererPluginGenerationStateV2 = Object.freeze({
  status: 'empty',
  generation: undefined,
  error: undefined,
});

export class RendererGenerationStatusStoreV2 {
  private readonly listeners = new Set<() => void>();
  private snapshot: RendererGenerationStatusSnapshotV2 = statusSnapshotV2('loading', undefined);

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): RendererGenerationStatusSnapshotV2 => this.snapshot;

  begin(hasGeneration: boolean): void {
    if (hasGeneration && this.snapshot.status === 'degraded') return;
    this.publish(hasGeneration ? 'ready' : 'loading', undefined);
  }

  settle(hasGeneration: boolean): void {
    this.publish(hasGeneration ? 'ready' : 'empty', undefined);
  }

  fail(error: unknown, hasGeneration: boolean): void {
    this.publish(hasGeneration ? 'degraded' : 'error', error);
  }

  private publish(status: RendererGenerationStatusV2, error: unknown | undefined): void {
    if (this.snapshot.status === status && Object.is(this.snapshot.error, error)) return;
    this.snapshot = statusSnapshotV2(status, error);
    for (const listener of this.listeners) listener();
  }
}

export function projectRendererPluginGenerationStateV2(
  enabled: boolean,
  generation: RuntimeGenerationV2 | undefined,
  status: RendererGenerationStatusSnapshotV2
): RendererPluginGenerationStateV2 {
  if (!enabled) return EMPTY_STATE_V2;
  if (generation !== undefined) {
    if (status.status === 'degraded' || status.status === 'error') {
      return Object.freeze({
        status: 'degraded',
        generation,
        error: status.error,
      });
    }
    return Object.freeze({ status: 'ready', generation, error: undefined });
  }
  if (status.status === 'loading') return LOADING_STATE_V2;
  if (status.status === 'empty' || status.status === 'ready') return EMPTY_STATE_V2;
  return Object.freeze({
    status: 'error',
    generation: undefined,
    error: status.error,
  });
}

export function startRendererGenerationPollingV2(
  options: StartRendererGenerationPollingOptionsV2
): () => void {
  const controller = new AbortController();
  let stopped = false;
  let inFlight: Promise<void> | null = null;

  options.statusStore.begin(options.runtime.getSnapshot() !== undefined);

  const refresh = (): void => {
    if (stopped || inFlight !== null) return;
    const request = refreshRendererGenerationV2(options, controller.signal, () => stopped).catch(
      (error: unknown) => {
        if (stopped) return;
        options.statusStore.fail(error, options.runtime.getSnapshot() !== undefined);
      }
    );
    inFlight = request;
    void request.finally(() => {
      if (inFlight === request) inFlight = null;
    });
  };

  refresh();
  const timer = setInterval(refresh, options.pollIntervalMs);
  return () => {
    stopped = true;
    controller.abort();
    clearInterval(timer);
  };
}

async function refreshRendererGenerationV2(
  options: StartRendererGenerationPollingOptionsV2,
  signal: AbortSignal,
  isStopped: () => boolean
): Promise<void> {
  if (options.bootstrap !== undefined && options.runtime.getSnapshot() === undefined) {
    await options.bootstrap();
  }
  if (isStopped()) return;

  const payload = await options.source(signal);
  if (isStopped()) return;
  if (payload !== null) {
    const receipt = await applyRendererDistributionV2(options, payload);
    if (receipt?.status === 'nack') {
      throw new RuntimeV2Error(
        receipt.error_code ?? 'renderer_generation_apply_nack',
        receipt.error_message ?? 'renderer generation publication was rejected'
      );
    }
  }
  if (isStopped()) return;
  options.statusStore.settle(options.runtime.getSnapshot() !== undefined);
}

async function applyRendererDistributionV2(
  options: StartRendererGenerationPollingOptionsV2,
  payload: unknown
): Promise<SnapshotApplyReceiptV2 | undefined> {
  if (options.apply !== undefined) return options.apply(payload);
  return options.runtime.apply(payload);
}

function statusSnapshotV2(
  status: RendererGenerationStatusV2,
  error: unknown | undefined
): RendererGenerationStatusSnapshotV2 {
  return Object.freeze({ status, error });
}
