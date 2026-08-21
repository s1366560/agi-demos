import {
  ContextV2,
  EffectStackV2,
  resolveServiceV2,
  type AsyncDisposerV2,
  type EffectRecordV2,
  type EffectResultV2,
  type EventRecordV2,
  type FiberPhaseV2,
  type ProvideOptionsV2,
  type ResolveOptionsV2,
  type ServiceRecordV2,
} from './context';
import { RuntimeV2Error } from './errors';
import type {
  DataPlaneTargetV2,
  EventContractV2,
  PluginContractV2,
  PluginModuleV2,
  ProfileEntryV2,
  ProfileSnapshotV2,
  ScopeV2,
} from './generated';
import {
  entryOrderV2,
  eventContractCatalogV2,
  generatedTargetCatalogV2,
  preflightEntriesV2,
  validateGeneratedCatalogDigestV2,
  validateTargetModulesV2,
} from './preflight';

export {
  ContextV2,
  type AsyncDisposerV2,
  type EffectResultV2,
  type FiberPhaseV2,
  type ProvideOptionsV2,
  type ResolveOptionsV2,
} from './context';
export { RuntimeV2Error } from './errors';

export type TargetCatalogV2 = Readonly<Record<string, string>>;

export interface PluginDefinitionV2 {
  readonly moduleRef: string;
  readonly contractDigest: string;
  readonly apply: (
    context: ContextV2,
    config: Readonly<Record<string, unknown>>
  ) => EffectResultV2 | Promise<EffectResultV2>;
}

export class FiberV2 {
  phase: FiberPhaseV2 = 'pending';
  error?: unknown;
  readonly context: ContextV2;
  private readonly effects: EffectStackV2;

  constructor(
    readonly entry: ProfileEntryV2,
    private readonly definition: PluginDefinitionV2,
    contract: PluginContractV2,
    eventContracts: ReadonlyMap<string, EventContractV2>,
    services: ServiceRecordV2[],
    events: EventRecordV2[]
  ) {
    this.effects = new EffectStackV2(() => this.phase);
    this.context = new ContextV2(
      entry.entry_id,
      entry.scope,
      services,
      events,
      this.effects,
      contract,
      eventContracts,
      entry.inject,
      entry.isolate
    );
  }

  async start(): Promise<void> {
    if (this.phase !== 'pending') {
      throw new RuntimeV2Error('invalid_fiber_transition', `cannot start from ${this.phase}`);
    }
    this.phase = 'loading';
    try {
      const result = await this.definition.apply(this.context, this.entry.config);
      await this.effects.addResult(result, 'apply');
      this.phase = 'active';
    } catch (error) {
      this.error = error;
      this.phase = 'failed';
      await this.effects.dispose();
      throw error;
    }
  }

  async dispose(): Promise<void> {
    if (this.phase === 'disposed' || this.phase === 'unloading') return;
    if (this.phase === 'pending') {
      this.phase = 'disposed';
      return;
    }
    this.phase = 'unloading';
    await this.effects.dispose();
    this.phase = 'disposed';
  }

  diagnostics(): ReadonlyArray<Readonly<EffectRecordV2>> {
    return this.effects.records;
  }
}

export class RuntimeGenerationV2 {
  leaseCount = 0;
  retired = false;
  disposed = false;

  constructor(
    readonly snapshot: ProfileSnapshotV2,
    readonly fibers: ReadonlyArray<FiberV2>,
    private readonly services: ServiceRecordV2[]
  ) {}

  resolve<T>(service: string, scope: ScopeV2, options: ResolveOptionsV2 = {}): T {
    if (this.disposed) throw new RuntimeV2Error('disposed_generation', 'generation is disposed');
    return resolveServiceV2(
      this.services,
      service,
      options.version ?? '1.0.0',
      scope,
      options.isolation
    ) as T;
  }

  async dispose(): Promise<void> {
    if (this.disposed) return;
    for (const fiber of [...this.fibers].reverse()) await fiber.dispose();
    this.disposed = true;
  }
}

export class LoaderV2 {
  private readonly definitions = new Map<string, PluginDefinitionV2>();
  private readonly targetCatalog: ReadonlyMap<string, string>;
  private readonly usesGeneratedCatalog: boolean;

  constructor(
    definitions: Iterable<PluginDefinitionV2> = [],
    private readonly target: DataPlaneTargetV2 = 'web',
    targetCatalog?: TargetCatalogV2
  ) {
    this.usesGeneratedCatalog = targetCatalog === undefined;
    this.targetCatalog =
      targetCatalog === undefined
        ? generatedTargetCatalogV2(target)
        : new Map(Object.entries(targetCatalog));
    for (const definition of definitions) this.registerModule(definition);
  }

  registerModule(definition: PluginDefinitionV2): void {
    if (this.definitions.has(definition.moduleRef)) {
      throw new RuntimeV2Error(
        'duplicate_module_definition',
        `module ${definition.moduleRef} is already registered`
      );
    }
    this.definitions.set(definition.moduleRef, definition);
  }

  async stage(snapshot: ProfileSnapshotV2): Promise<RuntimeGenerationV2> {
    if (this.usesGeneratedCatalog) await validateGeneratedCatalogDigestV2();
    const modulesByKey = await validateTargetModulesV2(snapshot, this.target, this.targetCatalog);
    const entries = enabledTargetEntries(snapshot, this.target);
    const definitions = new Map<string, PluginDefinitionV2>();
    const modules = new Map<string, PluginModuleV2>();
    for (const entry of entries.values()) {
      const definition = this.definitions.get(entry.module_ref);
      if (!definition) {
        throw new RuntimeV2Error(
          'missing_module_definition',
          `entry ${entry.entry_id} module ${entry.module_ref} is unavailable`
        );
      }
      const module = modulesByKey.get(`${entry.plugin_ref}\0${entry.module_ref}`);
      if (!module) {
        throw new RuntimeV2Error(
          'missing_module_definition',
          `entry ${entry.entry_id} module ${entry.module_ref} is unavailable`
        );
      }
      if (definition.contractDigest !== module.contract_digest) {
        throw new RuntimeV2Error(
          'contract_digest_mismatch',
          `runtime module ${entry.module_ref} contract digest differs from manifest`
        );
      }
      if (entry.parent_entry_id !== null && !entries.has(entry.parent_entry_id)) {
        throw new RuntimeV2Error(
          'inactive_parent_entry',
          `entry ${entry.entry_id} parent is disabled`
        );
      }
      definitions.set(entry.entry_id, definition);
      modules.set(entry.entry_id, module);
    }
    return activateGeneration(snapshot, entries, definitions, modules);
  }
}

export function projectSnapshotEntriesV2(
  snapshot: ProfileSnapshotV2,
  target: DataPlaneTargetV2
): ReadonlyArray<ProfileEntryV2> {
  const moduleTargets = new Map(
    snapshot.manifests.flatMap((manifest) =>
      manifest.modules.map(
        (module) => [`${manifest.plugin_id}\0${module.module_ref}`, module.targets] as const
      )
    )
  );
  return snapshot.entries.filter((entry) =>
    moduleTargets.get(`${entry.plugin_ref}\0${entry.module_ref}`)?.includes(target)
  );
}

export class GenerationLeaseV2 {
  private released = false;

  constructor(
    readonly generation: RuntimeGenerationV2,
    private readonly manager: GenerationManagerV2
  ) {}

  async release(): Promise<void> {
    if (this.released) return;
    this.released = true;
    await this.manager.release(this.generation);
  }
}

export class GenerationManagerV2 {
  current: RuntimeGenerationV2 | undefined;
  private readonly subscribers = new Set<() => void>();

  async publish(generation: RuntimeGenerationV2): Promise<void> {
    const previous = this.current;
    this.current = generation;
    this.notify();
    if (previous) {
      previous.retired = true;
      if (previous.leaseCount === 0) await previous.dispose();
    }
  }

  acquire(): GenerationLeaseV2 {
    const generation = this.current;
    if (!generation) {
      throw new RuntimeV2Error('generation_unavailable', 'no generation is published');
    }
    generation.leaseCount += 1;
    return new GenerationLeaseV2(generation, this);
  }

  subscribe(listener: () => void): () => void {
    this.subscribers.add(listener);
    return () => this.subscribers.delete(listener);
  }

  getSnapshot = (): RuntimeGenerationV2 | undefined => this.current;

  async close(): Promise<void> {
    const current = this.current;
    this.current = undefined;
    this.notify();
    if (current) {
      current.retired = true;
      if (current.leaseCount === 0) await current.dispose();
    }
  }

  async release(generation: RuntimeGenerationV2): Promise<void> {
    generation.leaseCount -= 1;
    if (generation.leaseCount < 0) {
      throw new RuntimeV2Error('lease_underflow', 'generation lease count underflow');
    }
    if (generation.retired && generation.leaseCount === 0) await generation.dispose();
  }

  private notify(): void {
    for (const listener of this.subscribers) listener();
  }
}

function enabledTargetEntries(
  snapshot: ProfileSnapshotV2,
  target: DataPlaneTargetV2
): Map<string, ProfileEntryV2> {
  return new Map(
    projectSnapshotEntriesV2(snapshot, target)
      .filter((entry) => entry.enabled)
      .map((entry) => [entry.entry_id, entry])
  );
}

async function activateGeneration(
  snapshot: ProfileSnapshotV2,
  entries: ReadonlyMap<string, ProfileEntryV2>,
  definitions: ReadonlyMap<string, PluginDefinitionV2>,
  modules: ReadonlyMap<string, PluginModuleV2>
): Promise<RuntimeGenerationV2> {
  preflightEntriesV2(entries, modules);
  const order = entryOrderV2(entries, modules);
  const eventContracts = eventContractCatalogV2(modules.values());
  const services: ServiceRecordV2[] = [];
  const events: EventRecordV2[] = [];
  const fibers: FiberV2[] = [];
  try {
    for (const entryId of order) {
      const entry = requiredValue(entries, entryId, 'entry');
      const definition = requiredValue(definitions, entryId, 'entry definition');
      const module = requiredValue(modules, entryId, 'entry module');
      const fiber = new FiberV2(
        entry,
        definition,
        module.contract,
        eventContracts,
        services,
        events
      );
      fibers.push(fiber);
      await fiber.start();
    }
  } catch (error) {
    for (const fiber of [...fibers].reverse()) await fiber.dispose();
    throw error;
  }
  return new RuntimeGenerationV2(snapshot, fibers, services);
}

function requiredValue<K, V>(values: ReadonlyMap<K, V>, key: K, label: string): V {
  const value = values.get(key);
  if (value === undefined) throw new RuntimeV2Error('entry_order_invalid', `${label} is missing`);
  return value;
}
