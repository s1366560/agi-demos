export type MCPAppCanvasTab = {
  id: string;
  appId: string | null;
  title: string;
  toolName: string;
  serverName: string | null;
  resourceUri: string | null;
  resourceHtml: string | null;
  toolInput: Record<string, unknown> | null;
  toolResult: unknown;
  uiMetadata: Record<string, unknown>;
  projectId: string | null;
};

export type MCPAppCanvasState = {
  tabs: MCPAppCanvasTab[];
  activeTabId: string | null;
  openRevision: number;
};

export type MCPAppCanvasStreamEventResult = {
  handled: boolean;
  action: 'open' | null;
  state: MCPAppCanvasState;
};

type MCPAppResultEvent = {
  data: Record<string, unknown>;
};

export function emptyMCPAppCanvasState(): MCPAppCanvasState {
  return { tabs: [], activeTabId: null, openRevision: 0 };
}

export function applyMCPAppCanvasStreamEvent(
  state: MCPAppCanvasState,
  event: unknown,
): MCPAppCanvasStreamEventResult {
  const parsed = readMCPAppResultEvent(event);
  if (!parsed) return { handled: false, action: null, state };

  const uiMetadata = recordValue(parsed.data.ui_metadata) ?? {};
  const resourceHtml = nonEmptyString(parsed.data, 'resource_html', 'resourceHtml');
  const resourceUri =
    nonEmptyString(parsed.data, 'resource_uri', 'resourceUri') ??
    nonEmptyString(uiMetadata, 'resourceUri', 'resource_uri');
  if (!resourceHtml && !resourceUri) return { handled: true, action: null, state };

  const appId = nonEmptyString(parsed.data, 'app_id', 'appId');
  const toolName = nonEmptyString(parsed.data, 'tool_name', 'toolName') ?? '';
  const identity = resourceUri ?? appId;
  if (!identity) return { handled: true, action: null, state };

  const structuredContent = parsed.data.structured_content ?? parsed.data.structuredContent;
  const rawToolResult = parsed.data.tool_result ?? parsed.data.toolResult;
  const toolResult =
    structuredContent === undefined
      ? rawToolResult
      : {
          ...(recordValue(rawToolResult) ?? {}),
          structuredContent,
        };
  const tab: MCPAppCanvasTab = {
    id: `mcp-app-${identity}`,
    appId,
    title: nonEmptyString(uiMetadata, 'title') ?? toolName,
    toolName,
    serverName:
      nonEmptyString(parsed.data, 'server_name', 'serverName') ??
      nonEmptyString(uiMetadata, 'server_name', 'serverName'),
    resourceUri,
    resourceHtml,
    toolInput: recordValue(parsed.data.tool_input ?? parsed.data.toolInput),
    toolResult,
    uiMetadata: { ...uiMetadata },
    projectId:
      nonEmptyString(parsed.data, 'project_id', 'projectId') ??
      nonEmptyString(uiMetadata, 'project_id', 'projectId'),
  };
  const existingIndex = state.tabs.findIndex((candidate) => candidate.id === tab.id);
  const tabs =
    existingIndex < 0
      ? [...state.tabs, tab]
      : state.tabs.map((candidate, index) => (index === existingIndex ? tab : candidate));
  return {
    handled: true,
    action: 'open',
    state: {
      tabs,
      activeTabId: tab.id,
      openRevision: state.openRevision + 1,
    },
  };
}

export function selectMCPAppCanvasTab(
  state: MCPAppCanvasState,
  tabId: string,
): MCPAppCanvasState {
  if (state.activeTabId === tabId || !state.tabs.some((candidate) => candidate.id === tabId)) {
    return state;
  }
  return { ...state, activeTabId: tabId };
}

export function closeMCPAppCanvasTab(
  state: MCPAppCanvasState,
  tabId: string,
): MCPAppCanvasState {
  const tabs = state.tabs.filter((candidate) => candidate.id !== tabId);
  if (tabs.length === state.tabs.length) return state;
  return {
    ...state,
    tabs,
    activeTabId:
      state.activeTabId === tabId ? (tabs[tabs.length - 1]?.id ?? null) : state.activeTabId,
  };
}

function readMCPAppResultEvent(event: unknown): MCPAppResultEvent | null {
  const root = recordValue(event);
  if (!root) return null;
  const queue = [root];
  const seen = new Set<Record<string, unknown>>();
  while (queue.length) {
    const current = queue.shift();
    if (!current || seen.has(current)) continue;
    seen.add(current);
    const type = nonEmptyString(current, 'type', 'event_type');
    if (type === 'mcp_app_result') {
      return { data: recordValue(current.data) ?? recordValue(current.payload) ?? current };
    }
    for (const key of ['data', 'payload']) {
      const nested = recordValue(current[key]);
      if (nested) queue.push(nested);
    }
  }
  return null;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function nonEmptyString(record: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return null;
}
