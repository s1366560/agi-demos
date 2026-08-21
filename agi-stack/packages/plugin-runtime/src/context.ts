import { RuntimeV2Error } from './errors';
import type {
  EventContractV2,
  PluginContractV2,
  ScopeKindV2,
  ScopeV2,
  ServiceProvidedV2,
} from './generated';
import { jsonSchemaValidationIssueV2 } from './schema';

export type AsyncDisposerV2 = () => void | Promise<void>;
export type EffectResultV2 =
  | void
  | AsyncDisposerV2
  | Iterable<AsyncDisposerV2>
  | AsyncIterable<AsyncDisposerV2>;
export type FiberPhaseV2 = 'pending' | 'loading' | 'active' | 'unloading' | 'disposed' | 'failed';

export interface ProvideOptionsV2 {
  readonly label?: string;
  readonly version?: string;
}

export interface ResolveOptionsV2 {
  readonly isolation?: string;
  readonly version?: string;
}

export interface EffectRecordV2 {
  readonly label: string;
  disposer?: AsyncDisposerV2;
  error?: string;
}

export interface ServiceRecordV2 {
  readonly service: string;
  readonly version: string;
  readonly value: unknown;
  readonly scope: ScopeV2;
  readonly isolation?: string;
  readonly ownerEntryId: string;
}

type EventNextV2 = (value?: unknown) => Promise<unknown>;
type EventHandlerV2 = (payload: unknown, next?: EventNextV2) => unknown | Promise<unknown>;

export interface EventRecordV2 {
  readonly event: string;
  readonly handler: EventHandlerV2;
  readonly scope: ScopeV2;
  readonly ownerEntryId: string;
}

export class EffectStackV2 {
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
        this.add(assertDisposer(disposer, `${label}[${index}]`), `${label}[${index}]`);
        index += 1;
      }
      return;
    }
    if (isIterable(result)) {
      let index = 0;
      for (const disposer of result) {
        this.add(assertDisposer(disposer, `${label}[${index}]`), `${label}[${index}]`);
        index += 1;
      }
      return;
    }
    throw new RuntimeV2Error('invalid_effect', `${label} returned an unsupported effect`);
  }

  async dispose(): Promise<void> {
    for (const record of [...this.records].reverse()) await disposeRecord(record);
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
    private readonly contract: PluginContractV2,
    private readonly eventContracts: ReadonlyMap<string, EventContractV2>,
    private readonly inject: Readonly<Record<string, string>>,
    private readonly isolation: Readonly<Record<string, string>>,
    private readonly interceptors: Readonly<
      Record<string, ReadonlyArray<(value: unknown) => unknown>>
    > = {}
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
      this.contract,
      this.eventContracts,
      options.inject ?? this.inject,
      this.isolation,
      this.interceptors
    );
  }

  isolate(service: string, label: string): ContextV2 {
    return this.copy({ isolation: { ...this.isolation, [service]: label } });
  }

  intercept(service: string, interceptor: (value: unknown) => unknown): ContextV2 {
    return this.copy({
      interceptors: {
        ...this.interceptors,
        [service]: [...(this.interceptors[service] ?? []), interceptor],
      },
    });
  }

  provide(service: string, value: unknown, options: ProvideOptionsV2 = {}): AsyncDisposerV2 {
    this.effects.ensureActive();
    const provision = resolveProvision(this.contract, service, options.version, this.entryId);
    const record: ServiceRecordV2 = {
      service,
      version: provision.version,
      value,
      scope: this.scope,
      ...(this.isolation[service] === undefined ? {} : { isolation: this.isolation[service] }),
      ownerEntryId: this.entryId,
    };
    if (this.services.some((item) => sameServiceIdentity(item, record))) {
      throw new RuntimeV2Error(
        'service_conflict',
        `service ${service}@${provision.version} already has a provider`
      );
    }
    this.services.push(record);
    return this.effects.add(
      () => removeIdentity(this.services, record),
      options.label ?? `provide:${service}`
    );
  }

  require<T>(alias: string, version?: string): T {
    const requirement = this.contract.services.requires.find((item) => item.alias === alias);
    if (!requirement) {
      throw new RuntimeV2Error(
        'undeclared_require',
        `entry ${this.entryId} did not declare require ${alias}`
      );
    }
    if (version !== undefined && version !== requirement.version) {
      throw new RuntimeV2Error(
        'require_version_mismatch',
        `entry ${this.entryId} declared ${requirement.service}@${requirement.version}`
      );
    }
    const service = this.inject[alias];
    if (service === undefined) {
      throw new RuntimeV2Error(
        'missing_required_inject',
        `entry ${this.entryId} did not inject ${alias}`
      );
    }
    if (service !== requirement.service) {
      throw new RuntimeV2Error(
        'inject_service_mismatch',
        `entry ${this.entryId} alias ${alias} must inject ${requirement.service}`
      );
    }
    let value = resolveServiceV2(
      this.services,
      service,
      requirement.version,
      this.scope,
      this.isolation[service]
    );
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
    if (!this.contract.events.handles.some((item) => item.event === event)) {
      throw new RuntimeV2Error(
        'undeclared_event_handler',
        `entry ${this.entryId} did not declare handler ${event}`
      );
    }
    const record: EventRecordV2 = {
      event,
      handler,
      scope: this.scope,
      ownerEntryId: this.entryId,
    };
    this.events.push(record);
    return this.effects.add(() => removeIdentity(this.events, record), `event:${event}`);
  }

  async dispatch(event: string, payload: unknown): Promise<unknown> {
    const declaration = this.contract.events.emits.find((item) => item.event === event);
    if (!declaration) {
      throw new RuntimeV2Error(
        'undeclared_event_dispatch',
        `entry ${this.entryId} did not declare dispatch ${event}`
      );
    }
    validateEventValue(declaration, payload, 'invalid_event_payload');
    const listeners = this.listeners(event);
    switch (declaration.mode) {
      case 'emit':
        return dispatchMany(declaration, listeners, payload, true);
      case 'serial':
        return dispatchMany(declaration, listeners, payload, false);
      case 'bail':
        return dispatchBail(declaration, listeners, payload);
      case 'waterfall': {
        const result = await dispatchWaterfall(listeners, payload);
        validateEventValue(declaration, result, 'invalid_event_result', true);
        return result;
      }
    }
  }

  private listeners(event: string): ReadonlyArray<EventRecordV2> {
    if (!this.eventContracts.has(event)) return [];
    return this.events.filter(
      (item) => item.event === event && scopeContains(item.scope, this.scope)
    );
  }

  private copy(options: {
    readonly isolation?: Readonly<Record<string, string>>;
    readonly interceptors?: Readonly<Record<string, ReadonlyArray<(value: unknown) => unknown>>>;
  }): ContextV2 {
    return new ContextV2(
      this.entryId,
      this.scope,
      this.services,
      this.events,
      this.effects,
      this.contract,
      this.eventContracts,
      this.inject,
      options.isolation ?? this.isolation,
      options.interceptors ?? this.interceptors
    );
  }
}

export function resolveServiceV2(
  services: ReadonlyArray<ServiceRecordV2>,
  service: string,
  version: string,
  scope: ScopeV2,
  isolation?: string
): unknown {
  const candidates = services
    .filter(
      (item) =>
        item.service === service &&
        item.version === version &&
        item.isolation === isolation &&
        scopeContains(item.scope, scope)
    )
    .sort((left, right) => scopeRank(right.scope) - scopeRank(left.scope));
  const first = candidates[0];
  if (!first) {
    throw new RuntimeV2Error('missing_service', `service ${service}@${version} is unavailable`);
  }
  const rank = scopeRank(first.scope);
  if (candidates.filter((item) => scopeRank(item.scope) === rank).length > 1) {
    throw new RuntimeV2Error(
      'ambiguous_service',
      `service ${service}@${version} has multiple providers`
    );
  }
  return first.value;
}

async function dispatchMany(
  declaration: EventContractV2,
  listeners: ReadonlyArray<EventRecordV2>,
  payload: unknown,
  concurrent: boolean
): Promise<unknown[]> {
  const results: unknown[] = [];
  if (concurrent)
    results.push(...(await Promise.all(listeners.map((item) => item.handler(payload)))));
  else for (const item of listeners) results.push(await item.handler(payload));
  results.forEach((result) =>
    validateEventValue(declaration, result, 'invalid_event_result', true)
  );
  return results;
}

async function dispatchBail(
  declaration: EventContractV2,
  listeners: ReadonlyArray<EventRecordV2>,
  payload: unknown
): Promise<unknown> {
  let result: unknown = null;
  for (const item of listeners) {
    result = await item.handler(payload);
    if (result !== undefined && result !== null) break;
  }
  if (result === undefined) result = null;
  validateEventValue(declaration, result, 'invalid_event_result', true);
  return result;
}

async function dispatchWaterfall(
  listeners: ReadonlyArray<EventRecordV2>,
  payload: unknown
): Promise<unknown> {
  const dispatch = async (index: number, current: unknown): Promise<unknown> => {
    const listener = listeners[index];
    if (!listener) return current;
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

function validateEventValue(
  declaration: EventContractV2,
  value: unknown,
  code: 'invalid_event_payload' | 'invalid_event_result',
  result = false
): void {
  const issue = jsonSchemaValidationIssueV2(
    result ? declaration.result_schema : declaration.payload_schema,
    value
  );
  if (issue) throw new RuntimeV2Error(code, `event ${declaration.event}: ${issue}`);
}

function resolveProvision(
  contract: PluginContractV2,
  service: string,
  version: string | undefined,
  entryId: string
): ServiceProvidedV2 {
  const provisions = contract.services.provides.filter((item) => item.service === service);
  if (provisions.length === 0) {
    throw new RuntimeV2Error(
      'undeclared_provide',
      `entry ${entryId} did not declare provide ${service}`
    );
  }
  if (version !== undefined) {
    const exact = provisions.find((item) => item.version === version);
    if (!exact) {
      throw new RuntimeV2Error(
        'provide_version_mismatch',
        `entry ${entryId} declared another version of ${service}`
      );
    }
    return exact;
  }
  const provision = provisions[0];
  if (!provision || provisions.length !== 1) {
    throw new RuntimeV2Error(
      'ambiguous_provided_contract',
      `entry ${entryId} has multiple declared versions of ${service}`
    );
  }
  return provision;
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

function sameServiceIdentity(left: ServiceRecordV2, right: ServiceRecordV2): boolean {
  return (
    left.service === right.service &&
    left.version === right.version &&
    left.isolation === right.isolation &&
    sameScope(left.scope, right.scope)
  );
}

function assertDisposer(value: unknown, label: string): AsyncDisposerV2 {
  if (typeof value !== 'function') {
    throw new RuntimeV2Error('invalid_effect', `${label} is not a disposer`);
  }
  return value as AsyncDisposerV2;
}

function removeIdentity<T>(items: T[], target: T): void {
  const index = items.indexOf(target);
  if (index >= 0) items.splice(index, 1);
}

function isIterable(value: unknown): value is Iterable<unknown> {
  return typeof (value as { [Symbol.iterator]?: unknown })?.[Symbol.iterator] === 'function';
}

function isAsyncIterable(value: unknown): value is AsyncIterable<unknown> {
  return (
    typeof (value as { [Symbol.asyncIterator]?: unknown })?.[Symbol.asyncIterator] === 'function'
  );
}
