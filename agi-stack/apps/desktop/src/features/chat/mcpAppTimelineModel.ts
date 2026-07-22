import type { AgentTimelineItem } from '../../types';

export type MCPAppTimelineStatus = 'registered' | 'ready' | 'error';

export type MCPAppTimelineGroup = {
  id: string;
  startItemId: string;
  itemIds: string[];
  items: AgentTimelineItem[];
  appId: string;
  title: string;
  status: MCPAppTimelineStatus;
  serverName: string;
  toolName: string;
  source: string;
  resourceUri: string;
  projectId: string;
  interactive: boolean;
  toolInput: unknown;
  toolResult: unknown;
  structuredContent: unknown;
  error: string;
  resultItem: AgentTimelineItem | null;
};

export type MCPAppTimelineGrouping = {
  groups: MCPAppTimelineGroup[];
  claimedItemIds: string[];
};

const mcpAppEventTypes = new Set(['mcp_app_registered', 'mcp_app_result']);

export function isMCPAppTimelineEvent(item: AgentTimelineItem): boolean {
  return mcpAppEventTypes.has(item.type);
}

export function groupMCPAppTimelineItems(
  items: readonly AgentTimelineItem[],
): MCPAppTimelineGrouping {
  const groups: MCPAppTimelineGroup[] = [];
  const claimedIndexes = new Set<number>();

  for (let index = 0; index < items.length; index += 1) {
    const first = items[index];
    if (!first || claimedIndexes.has(index) || !isMCPAppTimelineEvent(first)) continue;

    const groupedIndexes = [index];
    const groupedItems = [first];
    if (first.type === 'mcp_app_registered') {
      for (let cursor = index + 1; cursor < items.length; cursor += 1) {
        const candidate = items[cursor];
        if (!candidate || claimedIndexes.has(cursor) || !isMCPAppTimelineEvent(candidate)) {
          continue;
        }
        if (!compatibleMCPAppEvent(first, candidate)) continue;
        if (candidate.type === 'mcp_app_registered') break;
        groupedIndexes.push(cursor);
        groupedItems.push(candidate);
        break;
      }
    }

    groupedIndexes.forEach((claimedIndex) => claimedIndexes.add(claimedIndex));
    groups.push(buildMCPAppTimelineGroup(groupedItems));
  }

  return {
    groups,
    claimedItemIds: items.flatMap((item, index) => (claimedIndexes.has(index) ? [item.id] : [])),
  };
}

type MCPAppIdentity = {
  appId: string;
  resourceUri: string;
  serverName: string;
  toolName: string;
};

function compatibleMCPAppEvent(
  current: AgentTimelineItem,
  candidate: AgentTimelineItem,
): boolean {
  const known = mcpAppIdentity(current);
  const incoming = mcpAppIdentity(candidate);
  if (known.appId && incoming.appId) return known.appId === incoming.appId;
  if (known.resourceUri && incoming.resourceUri) {
    return known.resourceUri === incoming.resourceUri;
  }
  if (known.serverName && known.toolName && incoming.serverName && incoming.toolName) {
    return known.serverName === incoming.serverName && known.toolName === incoming.toolName;
  }
  return identityEmpty(known) && identityEmpty(incoming);
}

function identityEmpty(identity: MCPAppIdentity): boolean {
  return !identity.appId && !identity.resourceUri && !identity.serverName && !identity.toolName;
}

function mcpAppIdentity(item: AgentTimelineItem): MCPAppIdentity {
  return {
    appId: eventString(item, ['app_id', 'appId']),
    resourceUri:
      eventString(item, ['resource_uri', 'resourceUri']) ||
      eventNestedString(item, ['ui_metadata', 'uiMetadata'], ['resource_uri', 'resourceUri']),
    serverName:
      eventString(item, ['server_name', 'serverName']) ||
      eventNestedString(item, ['ui_metadata', 'uiMetadata'], ['server_name', 'serverName']),
    toolName: eventString(item, ['tool_name', 'toolName']),
  };
}

function buildMCPAppTimelineGroup(items: AgentTimelineItem[]): MCPAppTimelineGroup {
  const first = items[0] as AgentTimelineItem;
  const last = items[items.length - 1] as AgentTimelineItem;
  const resultItem = items.find((item) => item.type === 'mcp_app_result') ?? null;
  const registrationItem = items.find((item) => item.type === 'mcp_app_registered') ?? null;
  const identity = mcpAppIdentity(resultItem ?? registrationItem ?? first);
  const registrationIdentity = registrationItem ? mcpAppIdentity(registrationItem) : null;
  const title = latestValue(items, (item) => eventTitle(item));
  const error = latestValue(items, (item) => eventString(item, ['error']));
  const hasError = items.some(
    (item) => eventBoolean(item, ['is_error', 'isError']) === true,
  );
  const resourceHtml = resultItem
    ? eventString(resultItem, ['resource_html', 'resourceHtml'])
    : '';

  return {
    id: `mcp-app-group:${first.id}:${last.id}`,
    startItemId: first.id,
    itemIds: items.map((item) => item.id),
    items,
    appId: identity.appId || registrationIdentity?.appId || '',
    title: title || identity.toolName || identity.appId || registrationIdentity?.appId || '',
    status: error || hasError ? 'error' : resultItem ? 'ready' : 'registered',
    serverName: identity.serverName || registrationIdentity?.serverName || '',
    toolName: identity.toolName || registrationIdentity?.toolName || '',
    source: registrationItem ? eventString(registrationItem, ['source']) : '',
    resourceUri: identity.resourceUri || registrationIdentity?.resourceUri || '',
    projectId: latestValue(items, (item) => eventString(item, ['project_id', 'projectId'])),
    interactive: Boolean(identity.resourceUri || registrationIdentity?.resourceUri || resourceHtml),
    toolInput: resultItem ? eventValue(resultItem, ['tool_input', 'toolInput']) : undefined,
    toolResult: resultItem ? eventValue(resultItem, ['tool_result', 'toolResult']) : undefined,
    structuredContent: resultItem
      ? eventValue(resultItem, ['structured_content', 'structuredContent'])
      : undefined,
    error,
    resultItem,
  };
}

function eventTitle(item: AgentTimelineItem): string {
  return (
    eventString(item, ['title']) ||
    eventNestedString(item, ['ui_metadata', 'uiMetadata'], ['title'])
  );
}

function eventRecords(item: AgentTimelineItem): Record<string, unknown>[] {
  const records: Record<string, unknown>[] = [item];
  for (const value of [item.payload, item.data, item.metadata]) {
    if (isRecord(value)) records.push(value);
  }
  return records;
}

function eventString(item: AgentTimelineItem, keys: readonly string[]): string {
  for (const record of eventRecords(item)) {
    const value = recordString(record, keys);
    if (value) return value;
  }
  return '';
}

function eventBoolean(item: AgentTimelineItem, keys: readonly string[]): boolean | null {
  for (const record of eventRecords(item)) {
    for (const key of keys) {
      if (typeof record[key] === 'boolean') return record[key];
    }
  }
  return null;
}

function eventNestedString(
  item: AgentTimelineItem,
  parentKeys: readonly string[],
  keys: readonly string[],
): string {
  for (const record of eventRecords(item)) {
    for (const parentKey of parentKeys) {
      const nested = record[parentKey];
      if (!isRecord(nested)) continue;
      const value = recordString(nested, keys);
      if (value) return value;
    }
  }
  return '';
}

function eventValue(item: AgentTimelineItem, keys: readonly string[]): unknown {
  for (const record of eventRecords(item)) {
    for (const key of keys) {
      if (key in record && record[key] !== undefined) return record[key];
    }
  }
  return undefined;
}

function recordString(record: Record<string, unknown>, keys: readonly string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function latestValue(
  items: readonly AgentTimelineItem[],
  read: (item: AgentTimelineItem) => string,
): string {
  let latest = read(items[0] as AgentTimelineItem);
  for (let index = 1; index < items.length; index += 1) {
    const next = read(items[index] as AgentTimelineItem);
    if (next) latest = next;
  }
  return latest;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
