import { parseControlPlaneDistributionV2, PluginSnapshotReconcilerV2 } from './distribution';
import { RuntimeV2Error } from './errors';
import type { DataPlaneTargetV2, SnapshotApplyReceiptV2 } from './generated';
import {
  GenerationLeaseV2,
  LoaderV2,
  type PluginDefinitionV2,
  type GenerationPublicationResultV2,
  type RuntimeGenerationV2,
} from './runtime';
import { parseProfileSnapshotV2 } from './validate';

export type RendererDataPlaneTargetV2 = Extract<DataPlaneTargetV2, 'web' | 'desktop-renderer'>;

export interface RendererGenerationLeaseSnapshotV2 {
  readonly generation: RuntimeGenerationV2 | undefined;
}

export class RendererPluginRuntimeV2 {
  private readonly reconciler: PluginSnapshotReconcilerV2;

  constructor(target: RendererDataPlaneTargetV2, definitions: Iterable<PluginDefinitionV2>) {
    this.reconciler = new PluginSnapshotReconcilerV2(new LoaderV2(definitions, target));
  }

  readonly subscribe = (listener: () => void): (() => void) =>
    this.reconciler.manager.subscribe(listener);

  readonly getSnapshot = (): RuntimeGenerationV2 | undefined =>
    this.reconciler.manager.getSnapshot();

  get lastPublication(): GenerationPublicationResultV2 | undefined {
    return this.reconciler.manager.lastPublication;
  }

  acquire(generation?: RuntimeGenerationV2): GenerationLeaseV2 {
    return this.reconciler.manager.acquire(generation);
  }

  async bootstrap(value: unknown): Promise<void> {
    const snapshot = await parseProfileSnapshotV2(value);
    await this.reconciler.bootstrap(snapshot);
  }

  async apply(value: unknown): Promise<SnapshotApplyReceiptV2> {
    const distribution = await parseControlPlaneDistributionV2(value);
    return this.reconciler.apply(distribution);
  }

  async replaceBaseline(value: unknown): Promise<void> {
    const snapshot = await parseProfileSnapshotV2(value);
    await this.reconciler.replaceBaseline(snapshot);
  }

  async close(): Promise<void> {
    await this.reconciler.close();
  }
}

export class RendererGenerationLeaseStoreV2 {
  private readonly listeners = new Set<() => void>();
  private readonly leases = new Map<RuntimeGenerationV2, GenerationLeaseV2>();
  private readonly pendingReleases = new Set<Promise<void>>();
  private rootActive = false;
  private deactivation: Promise<void> | undefined;
  private rootIdentity: object = {};
  private runtimeUnsubscribe: (() => void) | undefined;
  private snapshot: RendererGenerationLeaseSnapshotV2;

  constructor(private readonly runtime: RendererPluginRuntimeV2) {
    this.snapshot = generationLeaseSnapshotV2(runtime.getSnapshot());
  }

  activateRoot(): void {
    if (this.rootActive) {
      throw new RuntimeV2Error(
        'renderer_root_already_active',
        'renderer generation lease store already owns a React root'
      );
    }
    this.deactivation = undefined;
    this.rootIdentity = {};
    this.rootActive = true;
    this.runtimeUnsubscribe = this.runtime.subscribe(this.capture);
    try {
      this.capture();
    } catch (error) {
      this.detach();
      this.rootActive = false;
      throw error;
    }
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.assertRootActive();
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): RendererGenerationLeaseSnapshotV2 => {
    this.assertRootActive();
    return this.snapshot;
  };

  acquireGeneration(generation: RuntimeGenerationV2): GenerationLeaseV2 {
    this.assertRootActive();
    if (!this.leases.has(generation)) {
      throw new RuntimeV2Error(
        'renderer_generation_not_renderable',
        'generation is not retained by the active renderer root'
      );
    }
    return this.runtime.acquire(generation);
  }

  async commit(snapshot: RendererGenerationLeaseSnapshotV2): Promise<void> {
    this.assertRootActive();
    if (snapshot !== this.snapshot) return;
    await this.releaseExcept(snapshot.generation);
  }

  deactivateRoot(): Promise<void> {
    if (this.deactivation) return this.deactivation;
    if (!this.rootActive) return Promise.resolve();
    this.rootActive = false;
    this.listeners.clear();
    this.detach();
    const releases = new Set(this.pendingReleases);
    releases.add(this.releaseExcept(undefined));
    this.pendingReleases.clear();
    this.deactivation = drainRendererReleasesV2([...releases]);
    return this.deactivation;
  }

  private readonly capture = (): void => {
    if (!this.rootActive) return;
    const generation = this.runtime.getSnapshot();
    if (generation !== undefined && !this.leases.has(generation)) {
      this.leases.set(generation, this.runtime.acquire());
    }
    if (this.snapshot.generation === generation) return;
    this.snapshot = generationLeaseSnapshotV2(generation);
    const identity = this.rootIdentity;
    const errors: unknown[] = [];
    for (const listener of [...this.listeners]) {
      if (!this.rootActive || this.rootIdentity !== identity) break;
      try {
        listener();
      } catch (error) {
        errors.push(error);
      }
    }
    if (errors.length > 0) throw new AggregateError(errors, 'Renderer generation observers failed');
  };

  private assertRootActive(): void {
    if (!this.rootActive) {
      throw new RuntimeV2Error(
        'renderer_root_inactive',
        'activate the renderer generation lease store before rendering the React root'
      );
    }
  }

  private detach(): void {
    this.runtimeUnsubscribe?.();
    this.runtimeUnsubscribe = undefined;
  }

  private releaseExcept(retained: RuntimeGenerationV2 | undefined): Promise<void> {
    const releases: Promise<void>[] = [];
    for (const [generation, lease] of this.leases) {
      if (generation === retained) continue;
      this.leases.delete(generation);
      releases.push(lease.release());
    }
    if (releases.length === 0) return Promise.resolve();
    const pending = drainRendererReleasesV2(releases);
    this.pendingReleases.add(pending);
    void pending.finally(() => this.pendingReleases.delete(pending)).catch(() => undefined);
    return pending;
  }
}

function generationLeaseSnapshotV2(
  generation: RuntimeGenerationV2 | undefined
): RendererGenerationLeaseSnapshotV2 {
  return Object.freeze({ generation });
}

async function drainRendererReleasesV2(releases: readonly Promise<void>[]): Promise<void> {
  const results = await Promise.allSettled(releases);
  const errors = results.flatMap((result) => (result.status === 'rejected' ? [result.reason] : []));
  if (errors.length > 0)
    throw new AggregateError(errors, 'Renderer generation lease cleanup failed');
}
