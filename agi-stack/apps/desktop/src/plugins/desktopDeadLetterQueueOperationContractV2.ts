import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  DeadLetterQueueQuery,
  DeadLetterQueueScope,
} from '../features/governance/deadLetterQueueClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopDeadLetterQueueBaseInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: DeadLetterQueueScope;
  signal?: AbortSignal;
}>;
export type PreparedDesktopDeadLetterQueueBaseV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: DeadLetterQueueScope;
  signal?: AbortSignal;
}>;

const CONFIG_KEYS = new Set([
  'apiBaseUrl',
  'deviceAuthorizationBaseUrl',
  'apiKey',
  'localApiToken',
  'tenantId',
  'projectId',
  'workspaceId',
  'mode',
  'workspaceRoot',
]);
const SCOPE_KEYS = new Set(['authority', 'tenantId']);
const QUERY_KEYS = new Set(['status', 'eventType', 'errorType', 'routingKey', 'limit', 'offset']);
const STATUSES = new Set(['all', 'pending', 'retrying', 'discarded', 'expired', 'resolved']);

export function prepareDesktopDeadLetterQueueBaseV2(
  input: DesktopDeadLetterQueueBaseInputV2,
): PreparedDesktopDeadLetterQueueBaseV2 {
  if (!record(input) || !exactOrOptional(input, new Set(['config', 'scope']), new Set(['signal'])))
    throw invalid();
  const config = cloneConfig(input.config);
  const scope = cloneScope(input.scope, config);
  if (input.signal !== undefined && !abortSignal(input.signal)) throw invalid();
  return Object.freeze({
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function prepareDesktopDeadLetterQueueQueryV2(
  value: DeadLetterQueueQuery | undefined,
): Required<DeadLetterQueueQuery> {
  const query = value ?? {};
  if (!record(query) || !allowed(query, QUERY_KEYS)) throw invalid();
  const status = query.status ?? 'all';
  if (!STATUSES.has(status)) throw invalid();
  return Object.freeze({
    status,
    eventType: filter(query.eventType),
    errorType: filter(query.errorType),
    routingKey: filter(query.routingKey),
    limit: integer(query.limit ?? 50, 1, 100),
    offset: integer(query.offset ?? 0, 0, Number.MAX_SAFE_INTEGER),
  });
}

export function prepareDesktopDeadLetterQueueIdV2(value: string): string {
  return identifier(value);
}
export function prepareDesktopDeadLetterQueueIdsV2(value: readonly string[]): readonly string[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 100) throw invalid();
  const ids = value.map(identifier);
  if (new Set(ids).size !== ids.length) throw invalid();
  return Object.freeze(ids);
}
export function prepareDesktopDeadLetterQueueReasonV2(value: string): string {
  if (typeof value !== 'string') throw invalid();
  const result = value.trim();
  if (!result || result.length > 500) throw invalid();
  return result;
}
export function prepareDesktopDeadLetterQueueHoursV2(
  value: number,
  kind: 'expired' | 'resolved',
): number {
  return integer(value, 1, kind === 'expired' ? 720 : 168);
}

export function cloneDesktopDeadLetterQueueConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!record(config) || !exact(config, CONFIG_KEYS)) throw invalid();
  const copy = { ...config } as DesktopRuntimeConfig;
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !canonical(copy.apiBaseUrl) ||
    !canonical(copy.tenantId)
  )
    throw invalid();
  return Object.freeze(copy);
}

function cloneConfig(value: DesktopRuntimeConfig): DesktopRuntimeConfig {
  return cloneDesktopDeadLetterQueueConfigV2(value);
}
function cloneScope(
  value: DeadLetterQueueScope,
  config: DesktopRuntimeConfig,
): DeadLetterQueueScope {
  if (
    !record(value) ||
    !exact(value, SCOPE_KEYS) ||
    (value.authority !== 'cloud' && value.authority !== 'local') ||
    identifier(value.tenantId) !== config.tenantId
  )
    throw invalid();
  return Object.freeze({ authority: value.authority, tenantId: value.tenantId });
}
function filter(value: unknown): string {
  if (value === undefined) return '';
  if (typeof value !== 'string' || value.length > 200) throw invalid();
  return value.trim();
}
function identifier(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !value ||
    value !== value.trim() ||
    value.length > 256 ||
    !/^[A-Za-z0-9](?:[A-Za-z0-9._:-]*[A-Za-z0-9])?$/u.test(value)
  )
    throw invalid();
  return value;
}
function integer(value: unknown, min: number, max: number): number {
  if (!Number.isSafeInteger(value) || (value as number) < min || (value as number) > max)
    throw invalid();
  return value as number;
}
function canonical(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}
function abortSignal(value: unknown): value is AbortSignal {
  return (
    record(value) &&
    typeof value.aborted === 'boolean' &&
    typeof value.addEventListener === 'function'
  );
}
function allowed(value: Record<string, unknown>, keys: ReadonlySet<string>): boolean {
  return Object.keys(value).every((key) => keys.has(key));
}
function exact(value: Record<string, unknown>, keys: ReadonlySet<string>): boolean {
  return Object.keys(value).length === keys.size && allowed(value, keys);
}
function exactOrOptional(
  value: Record<string, unknown>,
  required: ReadonlySet<string>,
  optional: ReadonlySet<string>,
): boolean {
  return (
    [...required].every((key) => Object.hasOwn(value, key)) &&
    Object.keys(value).every((key) => required.has(key) || optional.has(key))
  );
}
function record(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}
function invalid(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_dead_letter_queue_operation_input_invalid',
    'desktop dead letter queue operation input is invalid',
  );
}
