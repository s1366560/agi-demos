import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type {
  DeadLetterQueueBatchResult,
  DeadLetterQueueCleanupResult,
  DeadLetterQueueClient,
  DeadLetterQueueMessage,
  DeadLetterQueuePage,
  DeadLetterQueueQuery,
  DeadLetterQueueRequestOptions,
  DeadLetterQueueScope,
  DeadLetterQueueStats,
} from '../features/governance/deadLetterQueueClient';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopDeadLetterQueueHttpProjectionV2 } from './desktopDeadLetterQueueHttpProjectionV2';
import {
  cloneDesktopDeadLetterQueueConfigV2,
  prepareDesktopDeadLetterQueueBaseV2,
  prepareDesktopDeadLetterQueueHoursV2,
  prepareDesktopDeadLetterQueueIdsV2,
  prepareDesktopDeadLetterQueueIdV2,
  prepareDesktopDeadLetterQueueQueryV2,
  prepareDesktopDeadLetterQueueReasonV2,
  type DesktopDeadLetterQueueBaseInputV2,
  type PreparedDesktopDeadLetterQueueBaseV2,
} from './desktopDeadLetterQueueOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_DEAD_LETTER_QUEUE_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/dead-letter-queue-authority';
export const DESKTOP_DEAD_LETTER_QUEUE_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.dead-letter-queue-authority';
export const DESKTOP_DEAD_LETTER_QUEUE_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopDeadLetterQueueCapabilityV2 = Readonly<{
  availability: 'available' | 'not_applicable';
  reasonCode: string | null;
  allowedActions: readonly string[];
  authorityRevision: number | null;
}>;
export interface DesktopDeadLetterQueueAuthorityV2 {
  list(query: Required<DeadLetterQueueQuery>, signal?: AbortSignal): Promise<DeadLetterQueuePage>;
  get(id: string, signal?: AbortSignal): Promise<DeadLetterQueueMessage>;
  stats(signal?: AbortSignal): Promise<DeadLetterQueueStats>;
  retry(id: string, signal?: AbortSignal): Promise<void>;
  retryBatch(ids: readonly string[], signal?: AbortSignal): Promise<DeadLetterQueueBatchResult>;
  discard(id: string, reason: string, signal?: AbortSignal): Promise<void>;
  discardBatch(
    ids: readonly string[],
    reason: string,
    signal?: AbortSignal,
  ): Promise<DeadLetterQueueBatchResult>;
  cleanupExpired(hours: number, signal?: AbortSignal): Promise<DeadLetterQueueCleanupResult>;
  cleanupResolved(hours: number, signal?: AbortSignal): Promise<DeadLetterQueueCleanupResult>;
  probe(signal?: AbortSignal): Promise<DesktopDeadLetterQueueCapabilityV2>;
}
export interface DesktopDeadLetterQueueAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    scope: DeadLetterQueueScope,
  ): DesktopDeadLetterQueueAuthorityV2;
}
type WithId = DesktopDeadLetterQueueBaseInputV2 & Readonly<{ id: string }>;
type WithIds = DesktopDeadLetterQueueBaseInputV2 & Readonly<{ ids: readonly string[] }>;
type WithReason = WithId & Readonly<{ reason: string }>;
type WithBatchReason = WithIds & Readonly<{ reason: string }>;
type WithHours = DesktopDeadLetterQueueBaseInputV2 & Readonly<{ hours: number }>;
export interface DesktopDeadLetterQueueOperationsV2 {
  list(
    input: DesktopDeadLetterQueueBaseInputV2 & Readonly<{ query?: DeadLetterQueueQuery }>,
  ): Promise<DeadLetterQueuePage>;
  get(input: WithId): Promise<DeadLetterQueueMessage>;
  stats(input: DesktopDeadLetterQueueBaseInputV2): Promise<DeadLetterQueueStats>;
  retry(input: WithId): Promise<void>;
  retryBatch(input: WithIds): Promise<DeadLetterQueueBatchResult>;
  discard(input: WithReason): Promise<void>;
  discardBatch(input: WithBatchReason): Promise<DeadLetterQueueBatchResult>;
  cleanupExpired(input: WithHours): Promise<DeadLetterQueueCleanupResult>;
  cleanupResolved(input: WithHours): Promise<DeadLetterQueueCleanupResult>;
  probe(input: DesktopDeadLetterQueueBaseInputV2): Promise<DesktopDeadLetterQueueCapabilityV2>;
}

type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;
export class DesktopDeadLetterQueueAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;
  constructor(value: Rejection) {
    super(value.reasonCode);
    this.name = 'DesktopDeadLetterQueueAuthorityUnavailableErrorV2';
    this.reasonCode = value.reasonCode;
    this.runtimeCode = value.runtimeCode;
  }
}

export function applyDesktopDeadLetterQueueAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-vault-broker')
    throw new RuntimeV2Error(
      'desktop_dead_letter_queue_authority_config_invalid',
      'desktop dead letter queue authority requires desktop-vault-broker strategy',
    );
  context.provide(
    DESKTOP_DEAD_LETTER_QUEUE_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig, scope: DeadLetterQueueScope) {
        const client = createDesktopDeadLetterQueueHttpProjectionV2(configValue);
        return bind(client, scope);
      },
    }),
  );
}
export const desktopDeadLetterQueueAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_DEAD_LETTER_QUEUE_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopDeadLetterQueueAuthorityV2,
});

export function createDesktopDeadLetterQueueOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopDeadLetterQueueOperationsV2 {
  const execute = <T>(
    input: DesktopDeadLetterQueueBaseInputV2,
    callback: (
      authority: DesktopDeadLetterQueueAuthorityV2,
      base: PreparedDesktopDeadLetterQueueBaseV2,
    ) => Promise<T>,
  ) =>
    run(
      requireActions(resolve()),
      prepareDesktopDeadLetterQueueBaseV2({
        config: input.config,
        scope: input.scope,
        ...(input.signal === undefined ? {} : { signal: input.signal }),
      }),
      callback,
    );
  const operations: DesktopDeadLetterQueueOperationsV2 = {
    list(input) {
      const query = prepareDesktopDeadLetterQueueQueryV2(input.query);
      return execute(input, (a, b) => a.list(query, b.signal));
    },
    get(input) {
      const id = prepareDesktopDeadLetterQueueIdV2(input.id);
      return execute(input, (a, b) => a.get(id, b.signal));
    },
    stats(input) {
      return execute(input, (a, b) => a.stats(b.signal));
    },
    retry(input) {
      const id = prepareDesktopDeadLetterQueueIdV2(input.id);
      return execute(input, (a, b) => a.retry(id, b.signal));
    },
    retryBatch(input) {
      const ids = prepareDesktopDeadLetterQueueIdsV2(input.ids);
      return execute(input, (a, b) => a.retryBatch(ids, b.signal));
    },
    discard(input) {
      const id = prepareDesktopDeadLetterQueueIdV2(input.id);
      const reason = prepareDesktopDeadLetterQueueReasonV2(input.reason);
      return execute(input, (a, b) => a.discard(id, reason, b.signal));
    },
    discardBatch(input) {
      const ids = prepareDesktopDeadLetterQueueIdsV2(input.ids);
      const reason = prepareDesktopDeadLetterQueueReasonV2(input.reason);
      return execute(input, (a, b) => a.discardBatch(ids, reason, b.signal));
    },
    cleanupExpired(input) {
      const hours = prepareDesktopDeadLetterQueueHoursV2(input.hours, 'expired');
      return execute(input, (a, b) => a.cleanupExpired(hours, b.signal));
    },
    cleanupResolved(input) {
      const hours = prepareDesktopDeadLetterQueueHoursV2(input.hours, 'resolved');
      return execute(input, (a, b) => a.cleanupResolved(hours, b.signal));
    },
    probe(input) {
      return execute(input, (a, b) => a.probe(b.signal));
    },
  };
  return Object.freeze(operations);
}

export function createDesktopDeadLetterQueueClientV2(
  operations: DesktopDeadLetterQueueOperationsV2,
  config: DesktopRuntimeConfig,
): DeadLetterQueueClient {
  const frozen = cloneDesktopDeadLetterQueueConfigV2(config);
  return Object.freeze({
    listMessages: (scope, query, options) =>
      operations.list({ config: frozen, scope, ...signal(options), ...(query ? { query } : {}) }),
    getMessage: (scope, id, options) =>
      operations.get({ config: frozen, scope, id, ...signal(options) }),
    getStats: (scope, options) => operations.stats({ config: frozen, scope, ...signal(options) }),
    retryMessage: (scope, id, options) =>
      operations.retry({ config: frozen, scope, id, ...signal(options) }),
    retryMessages: (scope, ids, options) =>
      operations.retryBatch({ config: frozen, scope, ids, ...signal(options) }),
    discardMessage: (scope, id, reason, options) =>
      operations.discard({ config: frozen, scope, id, reason, ...signal(options) }),
    discardMessages: (scope, ids, reason, options) =>
      operations.discardBatch({ config: frozen, scope, ids, reason, ...signal(options) }),
    cleanupExpired: (scope, hours, options) =>
      operations.cleanupExpired({ config: frozen, scope, hours, ...signal(options) }),
    cleanupResolved: (scope, hours, options) =>
      operations.cleanupResolved({ config: frozen, scope, hours, ...signal(options) }),
  });
}

export function withDesktopDeadLetterQueueAuthorityOperationV2<T>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopDeadLetterQueueBaseInputV2,
  callback: (
    authority: DesktopDeadLetterQueueAuthorityV2,
    base: PreparedDesktopDeadLetterQueueBaseV2,
  ) => Promise<T>,
): Promise<T> {
  return run(actions, prepareDesktopDeadLetterQueueBaseV2(input), callback);
}

async function run<T>(
  actions: DesktopRendererGenerationActionsV2,
  base: PreparedDesktopDeadLetterQueueBaseV2,
  callback: (
    authority: DesktopDeadLetterQueueAuthorityV2,
    base: PreparedDesktopDeadLetterQueueBaseV2,
  ) => Promise<T>,
): Promise<T> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopDeadLetterQueueAuthorityServiceV2>({
      service: DESKTOP_DEAD_LETTER_QUEUE_AUTHORITY_SERVICE_V2,
      version: DESKTOP_DEAD_LETTER_QUEUE_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: base.scope.tenantId }),
    });
  if (admission.status === 'rejected')
    throw new DesktopDeadLetterQueueAuthorityUnavailableErrorV2(admission);
  let failed = false,
    active = true;
  try {
    return await admission.useService((candidate) =>
      callback(
        revocable(
          requireAuthority(requireService(candidate).bindOperation(base.config, base.scope)),
          () => active,
        ),
        base,
      ),
    );
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    active = false;
    try {
      await admission.release();
    } catch (error) {
      if (!failed) throw error;
    }
  }
}
function bind(
  client: DeadLetterQueueClient,
  scope: DeadLetterQueueScope,
): DesktopDeadLetterQueueAuthorityV2 {
  const authority: DesktopDeadLetterQueueAuthorityV2 = {
    list: (query, signal) => client.listMessages(scope, query, { signal }),
    get: (id, signal) => client.getMessage(scope, id, { signal }),
    stats: (signal) => client.getStats(scope, { signal }),
    retry: (id, signal) => client.retryMessage(scope, id, { signal }),
    retryBatch: (ids, signal) => client.retryMessages(scope, ids, { signal }),
    discard: (id, reason, signal) => client.discardMessage(scope, id, reason, { signal }),
    discardBatch: (ids, reason, signal) => client.discardMessages(scope, ids, reason, { signal }),
    cleanupExpired: (hours, signal) => client.cleanupExpired(scope, hours, { signal }),
    cleanupResolved: (hours, signal) => client.cleanupResolved(scope, hours, { signal }),
    async probe(signal) {
      try {
        const page = await client.listMessages(scope, { limit: 1, offset: 0 }, { signal });
        return Object.freeze({
          availability: 'available',
          reasonCode: null,
          allowedActions: Object.freeze([...page.allowedActions]),
          authorityRevision: page.authorityRevision,
        });
      } catch (error) {
        if (error instanceof Error && error.message === 'cloud_message_bus_dlq_not_applicable')
          return Object.freeze({
            availability: 'not_applicable',
            reasonCode: 'cloud_message_bus_dlq_not_applicable',
            allowedActions: Object.freeze([]),
            authorityRevision: null,
          });
        throw error;
      }
    },
  };
  return Object.freeze(authority);
}
function revocable(
  authority: DesktopDeadLetterQueueAuthorityV2,
  active: () => boolean,
): DesktopDeadLetterQueueAuthorityV2 {
  const invoke = async <T>(fn: () => Promise<T>): Promise<T> => {
    check(active);
    const result = await fn();
    check(active);
    return result;
  };
  const wrapped: DesktopDeadLetterQueueAuthorityV2 = {
    list: (q, s) => invoke(() => authority.list(q, s)),
    get: (id, s) => invoke(() => authority.get(id, s)),
    stats: (s) => invoke(() => authority.stats(s)),
    retry: (id, s) => invoke(() => authority.retry(id, s)),
    retryBatch: (ids, s) => invoke(() => authority.retryBatch(ids, s)),
    discard: (id, r, s) => invoke(() => authority.discard(id, r, s)),
    discardBatch: (ids, r, s) => invoke(() => authority.discardBatch(ids, r, s)),
    cleanupExpired: (h, s) => invoke(() => authority.cleanupExpired(h, s)),
    cleanupResolved: (h, s) => invoke(() => authority.cleanupResolved(h, s)),
    probe: (s) => invoke(() => authority.probe(s)),
  };
  return Object.freeze(wrapped);
}
function requireService(v: unknown): DesktopDeadLetterQueueAuthorityServiceV2 {
  if (!record(v) || Object.keys(v).length !== 1 || typeof v.bindOperation !== 'function')
    throw invalidService();
  return v as unknown as DesktopDeadLetterQueueAuthorityServiceV2;
}
function requireAuthority(v: unknown): DesktopDeadLetterQueueAuthorityV2 {
  const keys = [
    'list',
    'get',
    'stats',
    'retry',
    'retryBatch',
    'discard',
    'discardBatch',
    'cleanupExpired',
    'cleanupResolved',
    'probe',
  ];
  if (
    !record(v) ||
    Object.keys(v).length !== keys.length ||
    keys.some((k) => typeof v[k] !== 'function')
  )
    throw invalidService();
  return v as unknown as DesktopDeadLetterQueueAuthorityV2;
}
function requireActions(
  v: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (v) return v;
  throw new DesktopDeadLetterQueueAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}
function check(active: () => boolean): void {
  if (!active())
    throw new RuntimeV2Error(
      'desktop_dead_letter_queue_operation_released',
      'desktop dead letter queue operation released',
    );
}
function signal(o: DeadLetterQueueRequestOptions | undefined): { signal?: AbortSignal } {
  return o?.signal === undefined ? {} : { signal: o.signal };
}
function record(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}
function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_dead_letter_queue_service_invalid',
    'desktop dead letter queue authority service invalid',
  );
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (v) => v.module_ref === DESKTOP_DEAD_LETTER_QUEUE_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_dead_letter_queue_authority_catalog_missing',
      'desktop dead letter queue authority absent from catalog',
    );
  return entry.contract_digest;
}
