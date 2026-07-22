import type { AgentTimelineItem } from '../../types';

export type SessionRuntimeResourceFamily = 'sandbox' | 'desktop' | 'terminal' | 'httpService';

export type SessionRuntimeResource = {
  key: string;
  family: SessionRuntimeResourceFamily;
  id: string;
  label: string;
  sandboxId: string | null;
  status: string;
  updatedAtUs: number;
  latestEventId: string;
  endpoint: string | null;
  websocketUrl: string | null;
  url: string | null;
  proxyUrl: string | null;
  wsProxyUrl: string | null;
  display: string | null;
  resolution: string | null;
  port: number | null;
  sessionId: string | null;
  pid: number | null;
  sourceType: string | null;
  autoOpen: boolean | null;
  errorMessage: string | null;
};

export type SessionRuntimeInfrastructureEvent = {
  id: string;
  type: string;
  family: SessionRuntimeResourceFamily;
  resourceKey: string;
  status: string;
  eventTimeUs: number;
  snapshot: SessionRuntimeResource;
};

export type SessionRuntimeInfrastructureModel = {
  activeSandbox: SessionRuntimeResource | null;
  resources: SessionRuntimeResource[];
  events: SessionRuntimeInfrastructureEvent[];
  summary: {
    events: number;
    resources: number;
    running: number;
    errors: number;
  };
};

const runtimeEventTypes = new Set([
  'sandbox_created',
  'sandbox_status',
  'sandbox_terminated',
  'desktop_started',
  'desktop_status',
  'desktop_stopped',
  'terminal_started',
  'terminal_status',
  'terminal_stopped',
  'http_service_started',
  'http_service_updated',
  'http_service_stopped',
  'http_service_error',
]);

const runningStatuses = new Set(['running', 'ready', 'connected']);
const familyOrder: Record<SessionRuntimeResourceFamily, number> = {
  sandbox: 0,
  desktop: 1,
  terminal: 2,
  httpService: 3,
};

export function isSessionRuntimeInfrastructureEvent(value: unknown): boolean {
  const root = recordValue(value);
  const type = stringValue(root?.type ?? root?.event_type);
  return Boolean(type && runtimeEventTypes.has(type));
}

export function buildSessionRuntimeInfrastructure(
  items: readonly AgentTimelineItem[],
): SessionRuntimeInfrastructureModel {
  const resources = new Map<string, SessionRuntimeResource>();
  const events: SessionRuntimeInfrastructureEvent[] = [];
  const seenEventIds = new Set<string>();

  for (const item of [...items].sort(compareTimelineItems)) {
    if (!isSessionRuntimeInfrastructureEvent(item) || seenEventIds.has(item.id)) continue;
    const next = readRuntimeEvent(item, resources);
    if (!next) continue;
    seenEventIds.add(item.id);
    resources.set(next.snapshot.key, next.snapshot);
    events.push(next);

    if (next.type === 'sandbox_terminated') {
      for (const [key, resource] of resources) {
        if (resource.family === 'sandbox' || resource.sandboxId !== next.snapshot.id) continue;
        resources.set(key, {
          ...resource,
          status: 'stopped',
          updatedAtUs: next.eventTimeUs,
        });
      }
    }
  }

  const resourceList = [...resources.values()].sort(compareResources);
  const activeSandbox =
    resourceList
      .filter((resource) => resource.family === 'sandbox')
      .sort((left, right) =>
        right.updatedAtUs - left.updatedAtUs || left.id.localeCompare(right.id),
      )[0] ?? null;

  return {
    activeSandbox,
    resources: resourceList,
    events,
    summary: {
      events: events.length,
      resources: resourceList.length,
      running: resourceList.filter((resource) => runningStatuses.has(resource.status)).length,
      errors: resourceList.filter((resource) => resource.status === 'error').length,
    },
  };
}

function readRuntimeEvent(
  item: AgentTimelineItem,
  resources: ReadonlyMap<string, SessionRuntimeResource>,
): SessionRuntimeInfrastructureEvent | null {
  const type = eventType(item);
  const family = eventFamily(type);
  if (!family) return null;
  const sandboxId = fieldString(item, 'sandbox_id', 'sandboxId');
  const id =
    family === 'httpService'
      ? fieldString(item, 'service_id', 'serviceId', 'id')
      : sandboxId;
  if (!id) return null;
  const resourceKey = `${family}:${id}`;
  const previous = resources.get(resourceKey) ?? null;
  const status = eventStatus(item, type);
  if (!status) return null;

  const name = fieldString(item, 'service_name', 'serviceName', 'name');
  if (family === 'httpService' && type === 'http_service_started' && !name) return null;
  const eventTimeUs = timelineTimeUs(item);
  const snapshot: SessionRuntimeResource = {
    key: resourceKey,
    family,
    id,
    label: name ?? previous?.label ?? defaultResourceLabel(family, id),
    sandboxId: family === 'sandbox' ? id : (sandboxId ?? previous?.sandboxId ?? null),
    status,
    updatedAtUs: eventTimeUs,
    latestEventId: item.id,
    endpoint: optionalString(item, previous, 'endpoint'),
    websocketUrl: optionalString(item, previous, 'websocketUrl', 'websocket_url', 'websocketUrl'),
    url: optionalString(
      item,
      previous,
      'url',
      ...(family === 'httpService' ? ['service_url', 'serviceUrl'] : ['url']),
    ),
    proxyUrl: optionalString(item, previous, 'proxyUrl', 'proxy_url', 'proxyUrl'),
    wsProxyUrl: optionalString(item, previous, 'wsProxyUrl', 'ws_proxy_url', 'wsProxyUrl'),
    display: optionalString(item, previous, 'display', 'display'),
    resolution: optionalString(item, previous, 'resolution', 'resolution'),
    port: optionalNumber(item, previous, 'port', 'port'),
    sessionId: optionalString(item, previous, 'sessionId', 'session_id', 'sessionId'),
    pid: optionalNumber(item, previous, 'pid', 'pid'),
    sourceType: optionalString(item, previous, 'sourceType', 'source_type', 'sourceType'),
    autoOpen: optionalBoolean(item, previous, 'autoOpen', 'auto_open', 'autoOpen'),
    errorMessage: optionalString(
      item,
      previous,
      'errorMessage',
      'error_message',
      'errorMessage',
      'error',
    ),
  };

  return {
    id: item.id,
    type,
    family,
    resourceKey,
    status,
    eventTimeUs,
    snapshot,
  };
}

function eventFamily(type: string): SessionRuntimeResourceFamily | null {
  if (type.startsWith('sandbox_')) return 'sandbox';
  if (type.startsWith('desktop_')) return 'desktop';
  if (type.startsWith('terminal_')) return 'terminal';
  if (type.startsWith('http_service_')) return 'httpService';
  return null;
}

function eventStatus(item: AgentTimelineItem, type: string): string | null {
  if (type === 'sandbox_created') return fieldString(item, 'status') ?? 'running';
  if (type === 'sandbox_status') return fieldString(item, 'status');
  if (type === 'sandbox_terminated') return 'terminated';
  if (type === 'desktop_started' || type === 'terminal_started') return 'running';
  if (type === 'desktop_stopped' || type === 'terminal_stopped') return 'stopped';
  if (type === 'desktop_status' || type === 'terminal_status') {
    const running = fieldBoolean(item, 'running');
    return running === null ? null : running ? 'running' : 'stopped';
  }
  if (type === 'http_service_started') return 'running';
  if (type === 'http_service_updated') return fieldString(item, 'status') ?? 'running';
  if (type === 'http_service_stopped') return fieldString(item, 'status') ?? 'stopped';
  if (type === 'http_service_error') return 'error';
  return null;
}

function defaultResourceLabel(family: SessionRuntimeResourceFamily, id: string): string {
  if (family === 'httpService') return id;
  return `${family} ${id}`;
}

function optionalString(
  item: AgentTimelineItem,
  previous: SessionRuntimeResource | null,
  previousKey: keyof SessionRuntimeResource,
  ...keys: string[]
): string | null {
  const value = fieldString(item, ...keys);
  return value ?? (previous?.[previousKey] as string | null | undefined) ?? null;
}

function optionalNumber(
  item: AgentTimelineItem,
  previous: SessionRuntimeResource | null,
  previousKey: keyof SessionRuntimeResource,
  ...keys: string[]
): number | null {
  const value = fieldNonNegativeNumber(item, ...keys);
  return value ?? (previous?.[previousKey] as number | null | undefined) ?? null;
}

function optionalBoolean(
  item: AgentTimelineItem,
  previous: SessionRuntimeResource | null,
  previousKey: keyof SessionRuntimeResource,
  ...keys: string[]
): boolean | null {
  const value = fieldBoolean(item, ...keys);
  return value ?? (previous?.[previousKey] as boolean | null | undefined) ?? null;
}

function compareResources(left: SessionRuntimeResource, right: SessionRuntimeResource): number {
  return (
    familyOrder[left.family] - familyOrder[right.family] ||
    left.updatedAtUs - right.updatedAtUs ||
    left.id.localeCompare(right.id)
  );
}

function eventType(item: AgentTimelineItem): string {
  const record = item as unknown as Record<string, unknown>;
  return stringValue(record.type ?? record.event_type) ?? '';
}

function fieldValue(item: AgentTimelineItem, ...keys: string[]): unknown {
  const itemRecord = item as unknown as Record<string, unknown>;
  const payload = recordValue(itemRecord.payload) ?? recordValue(itemRecord.data);
  for (const key of keys) {
    if (payload && key in payload) return payload[key];
    if (key in itemRecord) return itemRecord[key];
  }
  return undefined;
}

function fieldString(item: AgentTimelineItem, ...keys: string[]): string | null {
  return stringValue(fieldValue(item, ...keys));
}

function fieldNonNegativeNumber(item: AgentTimelineItem, ...keys: string[]): number | null {
  const value = fieldValue(item, ...keys);
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function fieldBoolean(item: AgentTimelineItem, ...keys: string[]): boolean | null {
  const value = fieldValue(item, ...keys);
  return typeof value === 'boolean' ? value : null;
}

function timelineTimeUs(item: AgentTimelineItem): number {
  const record = item as unknown as Record<string, unknown>;
  const value = record.eventTimeUs ?? record.event_time_us;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return typeof item.timestamp === 'number' && Number.isFinite(item.timestamp)
    ? item.timestamp * 1000
    : 0;
}

function compareTimelineItems(left: AgentTimelineItem, right: AgentTimelineItem): number {
  const timeDifference = timelineTimeUs(left) - timelineTimeUs(right);
  if (timeDifference) return timeDifference;
  const leftCounter = numberValue(left.eventCounter ?? left.event_counter) ?? 0;
  const rightCounter = numberValue(right.eventCounter ?? right.event_counter) ?? 0;
  return leftCounter - rightCounter || left.id.localeCompare(right.id);
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
