import type { ProfileEntryV2, ProfileSnapshotV2, ScopeKindV2, ScopeV2 } from './generated';

export type AsyncDisposerV2 = () => void | Promise<void>;
export type EffectResultV2 =
  | void
  | AsyncDisposerV2
  | Iterable<AsyncDisposerV2>
  | AsyncIterable<AsyncDisposerV2>;
export type FiberPhaseV2 = 'pending' | 'loading' | 'active' | 'unloading' | 'disposed' | 'failed';

export interface PluginDefinitionV2 {
  readonly moduleRef: string;
  readonly provides?: ReadonlyArray<string>;
  readonly apply: (
    context: ContextV2,
    config: Readonly<Record<string, unknown>>
  ) => EffectResultV2 | Promise<EffectResultV2>;
}

interface EffectRecordV2 {
  readonly label: string;
  disposer?: AsyncDisposerV2;
  error?: string;
}

interface ServiceRecordV2 {
  readonly service: string;
  readonly value: unknown;
  readonly scope: ScopeV2;
  readonly isolation?: string;
  readonly ownerEntryId: string;
}

type EventNextV2 = (value?: unknown) => Promise<unknown>;
type EventHandlerV2 = (payload: unknown, next?: EventNextV2) => unknown | Promise<unknown>;

interface EventRecordV2 {
  readonly event: string;
  readonly handler: EventHandlerV2;
  readonly scope: ScopeV2;
  readonly ownerEntryId: string;
}

export class RuntimeV2Error extends Error {
  constructor(
    readonly code: string,
    message: string
  ) {
    super(message);
    this.name = 'RuntimeV2Error';
  }
}

class EffectStackV2 {
  readonly records: EffectRecordV2[] = [];

  constructor(private readonly phase: () => FiberPhaseV2) {}

  add(disposer: AsyncDisposerV2, label: string): AsyncDisposerV2 {
    this.ensureActive();
    const record: EffectRecordV2 = { label, disposer };
    this.records.push(record);
    return async () => disposeRecord(record);
  }

  async addResult(result: EffectResultV2, label: string): Promise<void> {
    this.ensureActive();
    if (result === undefined) return;
    if (typeof result === 'function') {
      this.add(result, label);
      return;
    }
    if (isAsyncIterable(result)) {
      let index = 0;
      for await (const disposer of result) {
        this.add(disposer, `${label}[${index}]`);
        index += 1;
      }
      return;
    }
    if (isIterable(result)) {
      let index = 0;
      for (const disposer of result) {
        this.add(disposer, `${label}[${index}]`);
        index += 1;
      }
      return;
    }
    throw new RuntimeV2Error('invalid_effect', `${label} returned an unsupported effect`);
  }

  async dispose(): Promise<void> {
    for (const record of [...this.records].reverse()) {
      await disposeRecord(record);
    }
  }

  ensureActive(): void {
    if (this.phase() !== 'loading' && this.phase() !== 'active') {
      throw new RuntimeV2Error('inactive_effect', 'inactive context cannot register an effect');
    }
  }
}

export class ContextV2 {
  constructor(
    readonly entryId: string,
    readonly scope: ScopeV2,
    private readonly services: ServiceRecordV2[],
    private readonly events: EventRecordV2[],
    private readonly effects: EffectStackV2,
    private readonly inject: Readonly<Record<string, string>>,
    private readonly isolation: Readonly<Record<string, string>>,
    private readonly interceptors: Readonly<
      Record<string, ReadonlyArray<(value: unknown) => unknown>>
    > = {},
    private readonly privileged = false
  ) {}

  extend(options: {
    readonly entryId?: string;
    readonly scope?: ScopeV2;
    readonly inject?: Readonly<Record<string, string>>;
  }): ContextV2 {
    return new ContextV2(
      options.entryId ?? this.entryId,
      options.scope ?? this.scope,
      this.services,
      this.events,
      this.effects,
      options.inject ?? this.inject,
      this.isolation,
      this.interceptors,
      this.privileged
    );
  }

  isolate(service: string, label: string): ContextV2 {
    return new ContextV2(
      this.entryId,
      this.scope,
      this.services,
      this.events,
      this.effects,
      this.inject,
      { ...this.isolation, [service]: label },
      this.interceptors,
      this.privileged
    );
  }

  intercept(service: string, interceptor: (value: unknown) => unknown): ContextV2 {
    return new ContextV2(
      this.entryId,
      this.scope,
      this.services,
      this.events,
      this.effects,
      this.inject,
      this.isolation,
      {
        ...this.interceptors,
        [service]: [...(this.interceptors[service] ?? []), interceptor],
      },
      this.privileged
    );
  }

  provide(service: string, value: unknown, label = `provide:${service}`): AsyncDisposerV2 {
    this.effects.ensureActive();
    const record: ServiceRecordV2 = {
      service,
      value,
      scope: this.scope,
      ...(this.isolation[service] === undefined ? {} : { isolation: this.isolation[service] }),
      ownerEntryId: this.entryId,
    };
    if (
      this.services.some(
        (item) =>
          item.service === record.service &&
          sameScope(item.scope, record.scope) &&
          item.isolation === record.isolation
      )
    ) {
      throw new RuntimeV2Error('service_conflict', `service ${service} already has a provider`);
    }
    this.services.push(record);
    return this.effects.add(() => removeIdentity(this.services, record), label);
  }

  get<T>(alias: string, defaultValue?: T): T | undefined {
    try {
      return this.require<T>(alias);
    } catch (error) {
      if (error instanceof RuntimeV2Error && error.code === 'missing_service') return defaultValue;
      throw error;
    }
  }

  require<T>(alias: string): T {
    const service = this.privileged ? (this.inject[alias] ?? alias) : this.inject[alias];
    if (service === undefined) {
      throw new RuntimeV2Error(
        'undeclared_inject',
        `entry ${this.entryId} did not inject ${alias}`
      );
    }
    let value = resolveService(this.services, service, this.scope, this.isolation[service]);
    for (const interceptor of this.interceptors[service] ?? []) value = interceptor(value);
    return value as T;
  }

  async effect(
    setup: () => EffectResultV2 | Promise<EffectResultV2>,
    label: string
  ): Promise<void> {
    this.effects.ensureActive();
    await this.effects.addResult(await setup(), label);
  }

  on(event: string, handler: EventHandlerV2): AsyncDisposerV2 {
    this.effects.ensureActive();
    const record: EventRecordV2 = {
      event,
      handler,
      scope: this.scope,
      ownerEntryId: this.entryId,
    };
    this.events.push(record);
    return this.effects.add(() => removeIdentity(this.events, record), `event:${event}`);
  }

  async emit(event: string, payload: unknown): Promise<ReadonlyArray<unknown>> {
    return Promise.all(this.listeners(event).map((item) => item.handler(payload)));
  }

  async serial(event: string, payload: unknown): Promise<ReadonlyArray<unknown>> {
    const results: unknown[] = [];
    for (const item of this.listeners(event)) results.push(await item.handler(payload));
    return results;
  }

  async bail(event: string, payload: unknown): Promise<unknown> {
    for (const item of this.listeners(event)) {
      const result = await item.handler(payload);
      if (result !== undefined && result !== null) return result;
    }
    return undefined;
  }

  async waterfall(event: string, payload: unknown): Promise<unknown> {
    const listeners = this.listeners(event);
    const dispatch = async (index: number, current: unknown): Promise<unknown> => {
      const listener = listeners[index];
      if (listener === undefined) return current;
      let called = false;
      const next: EventNextV2 = async (nextValue = current) => {
        if (called) {
          throw new RuntimeV2Error('waterfall_next_reused', 'waterfall next() called twice');
        }
        called = true;
        return dispatch(index + 1, nextValue);
      };
      return listener.handler(current, next);
    };
    return dispatch(0, payload);
  }

  private listeners(event: string): ReadonlyArray<EventRecordV2> {
    return this.events.filter(
      (item) => item.event === event && scopeContains(item.scope, this.scope)
    );
  }
}

export class FiberV2 {
  phase: FiberPhaseV2 = 'pending';
  error?: unknown;
  readonly context: ContextV2;
  private readonly effects: EffectStackV2;

  constructor(
    readonly entry: ProfileEntryV2,
    private readonly definition: PluginDefinitionV2,
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
      entry.inject as Readonly<Record<string, string>>,
      entry.isolate as Readonly<Record<string, string>>
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

  resolve<T>(service: string, scope: ScopeV2, isolation?: string): T {
    if (this.disposed) throw new RuntimeV2Error('disposed_generation', 'generation is disposed');
    return resolveService(this.services, service, scope, isolation) as T;
  }

  async dispose(): Promise<void> {
    if (this.disposed) return;
    for (const fiber of [...this.fibers].reverse()) await fiber.dispose();
    this.disposed = true;
  }
}

export class LoaderV2 {
  private readonly definitions = new Map<string, PluginDefinitionV2>();

  constructor(definitions: Iterable<PluginDefinitionV2> = []) {
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
    const entries = new Map(
      snapshot.entries.filter((entry) => entry.enabled).map((entry) => [entry.entry_id, entry])
    );
    const definitions = new Map<string, PluginDefinitionV2>();
    for (const entry of entries.values()) {
      const definition = this.definitions.get(entry.module_ref);
      if (!definition) {
        throw new RuntimeV2Error(
          'missing_module_definition',
          `entry ${entry.entry_id} module ${entry.module_ref} is unavailable`
        );
      }
      if (entry.parent_entry_id !== null && !entries.has(entry.parent_entry_id)) {
        throw new RuntimeV2Error(
          'inactive_parent_entry',
          `entry ${entry.entry_id} parent is disabled`
        );
      }
      definitions.set(entry.entry_id, definition);
    }
    const order = entryOrder(entries, definitions);
    const services: ServiceRecordV2[] = [];
    const events: EventRecordV2[] = [];
    const fibers: FiberV2[] = [];
    try {
      for (const entryId of order) {
        const entry = entries.get(entryId);
        const definition = definitions.get(entryId);
        if (!entry || !definition) {
          throw new RuntimeV2Error('entry_order_invalid', `entry order references ${entryId}`);
        }
        const fiber = new FiberV2(entry, definition, services, events);
        fibers.push(fiber);
        await fiber.start();
      }
    } catch (error) {
      for (const fiber of [...fibers].reverse()) await fiber.dispose();
      throw error;
    }
    return new RuntimeGenerationV2(snapshot, fibers, services);
  }
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

async function disposeRecord(record: EffectRecordV2): Promise<void> {
  const disposer = record.disposer;
  if (!disposer) return;
  delete record.disposer;
  try {
    await disposer();
  } catch (error) {
    record.error = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  }
}

function resolveService(
  services: ReadonlyArray<ServiceRecordV2>,
  service: string,
  scope: ScopeV2,
  isolation?: string
): unknown {
  const candidates = services
    .filter(
      (item) =>
        item.service === service && item.isolation === isolation && scopeContains(item.scope, scope)
    )
    .sort((left, right) => scopeRank(right.scope) - scopeRank(left.scope));
  const first = candidates[0];
  if (!first) throw new RuntimeV2Error('missing_service', `service ${service} is unavailable`);
  const rank = scopeRank(first.scope);
  if (candidates.filter((item) => scopeRank(item.scope) === rank).length > 1) {
    throw new RuntimeV2Error('ambiguous_service', `service ${service} has multiple providers`);
  }
  return first.value;
}

function entryOrder(
  entries: ReadonlyMap<string, ProfileEntryV2>,
  definitions: ReadonlyMap<string, PluginDefinitionV2>
): ReadonlyArray<string> {
  const dependencies = new Map<string, Set<string>>(
    Array.from(entries.keys(), (entryId) => [entryId, new Set<string>()])
  );
  for (const [entryId, entry] of entries) {
    const ownDependencies = dependencies.get(entryId);
    if (!ownDependencies) throw new RuntimeV2Error('entry_order_invalid', entryId);
    if (entry.parent_entry_id !== null) ownDependencies.add(entry.parent_entry_id);
    for (const service of Object.values(entry.inject)) {
      const providers = Array.from(definitions.entries())
        .filter(
          ([providerId, definition]) =>
            (definition.provides ?? []).includes(service as string) &&
            scopeContains(requiredEntry(entries, providerId).scope, entry.scope) &&
            requiredEntry(entries, providerId).isolate[service as string] ===
              entry.isolate[service as string]
        )
        .map(([providerId]) => providerId)
        .sort(
          (left, right) =>
            scopeRank(requiredEntry(entries, right).scope) -
            scopeRank(requiredEntry(entries, left).scope)
        );
      const first = providers[0];
      if (!first) {
        throw new RuntimeV2Error(
          'missing_inject_provider',
          `entry ${entryId} injects missing service ${service}`
        );
      }
      const rank = scopeRank(requiredEntry(entries, first).scope);
      if (
        providers.filter((provider) => scopeRank(requiredEntry(entries, provider).scope) === rank)
          .length !== 1
      ) {
        throw new RuntimeV2Error(
          'ambiguous_inject_provider',
          `entry ${entryId} has ambiguous service ${service}`
        );
      }
      if (first !== entryId) ownDependencies.add(first);
    }
  }

  const ordered: string[] = [];
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (entryId: string): void => {
    if (visited.has(entryId)) return;
    if (visiting.has(entryId)) {
      throw new RuntimeV2Error('entry_dependency_cycle', `entry cycle includes ${entryId}`);
    }
    visiting.add(entryId);
    for (const dependency of [...(dependencies.get(entryId) ?? [])].sort()) visit(dependency);
    visiting.delete(entryId);
    visited.add(entryId);
    ordered.push(entryId);
  };
  for (const entryId of [...entries.keys()].sort()) visit(entryId);
  return ordered;
}

function requiredEntry(
  entries: ReadonlyMap<string, ProfileEntryV2>,
  entryId: string
): ProfileEntryV2 {
  const entry = entries.get(entryId);
  if (!entry) throw new RuntimeV2Error('entry_order_invalid', entryId);
  return entry;
}

function scopeRank(scope: ScopeV2): number {
  const ranks: Record<ScopeKindV2, number> = {
    root: 0,
    tenant: 1,
    project: 2,
    session: 3,
  };
  return ranks[scope.kind];
}

function scopeContains(parent: ScopeV2, child: ScopeV2): boolean {
  return (
    scopeRank(parent) <= scopeRank(child) &&
    (parent.tenant_id == null || parent.tenant_id === child.tenant_id) &&
    (parent.project_id == null || parent.project_id === child.project_id) &&
    (parent.session_id == null || parent.session_id === child.session_id)
  );
}

function sameScope(left: ScopeV2, right: ScopeV2): boolean {
  return (
    left.kind === right.kind &&
    left.tenant_id === right.tenant_id &&
    left.project_id === right.project_id &&
    left.session_id === right.session_id
  );
}

function removeIdentity<T>(items: T[], target: T): void {
  const index = items.indexOf(target);
  if (index >= 0) items.splice(index, 1);
}

function isIterable(value: unknown): value is Iterable<AsyncDisposerV2> {
  return typeof (value as { [Symbol.iterator]?: unknown })?.[Symbol.iterator] === 'function';
}

function isAsyncIterable(value: unknown): value is AsyncIterable<AsyncDisposerV2> {
  return (
    typeof (value as { [Symbol.asyncIterator]?: unknown })?.[Symbol.asyncIterator] === 'function'
  );
}
