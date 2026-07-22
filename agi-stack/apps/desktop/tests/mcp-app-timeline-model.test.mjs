import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { groupMCPAppTimelineItems, isMCPAppTimelineEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/mcpAppTimelineModel.js',
);

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const chatPanelSource = readFileSync(
  new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
  'utf8',
);
const chatTimelineSource = readFileSync(
  new URL('../src/features/chat/ChatTimeline.tsx', import.meta.url),
  'utf8',
);
const qaSource = readFileSync(new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url), 'utf8');
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

test('registered and result events become one inspectable MCP App lifecycle', () => {
  const items = [
    mcpEvent('app-registered', 'mcp_app_registered', {
      app_id: 'release-dashboard',
      server_name: 'release-tools',
      tool_name: 'show_release_dashboard',
      source: 'agent_developed',
      resource_uri: 'ui://release/dashboard',
      title: 'Release dashboard',
    }),
    {
      id: 'agent-thought',
      type: 'thought',
      eventTimeUs: 2,
      eventCounter: 2,
      content: 'Waiting for the interactive result.',
    },
    mcpEvent('app-result', 'mcp_app_result', {
      app_id: 'release-dashboard',
      server_name: 'release-tools',
      tool_name: 'show_release_dashboard',
      resource_uri: 'ui://release/dashboard',
      ui_metadata: { title: 'Release dashboard' },
      tool_input: { release: '2026.07' },
      tool_result: { content: [{ type: 'text', text: 'ready' }] },
      structured_content: { checks: 18, failures: 0 },
      project_id: 'project-cloud',
    }),
  ];

  assert.deepEqual(groupMCPAppTimelineItems(items), {
    groups: [
      {
        id: 'mcp-app-group:app-registered:app-result',
        startItemId: 'app-registered',
        itemIds: ['app-registered', 'app-result'],
        items: [items[0], items[2]],
        appId: 'release-dashboard',
        title: 'Release dashboard',
        status: 'ready',
        serverName: 'release-tools',
        toolName: 'show_release_dashboard',
        source: 'agent_developed',
        resourceUri: 'ui://release/dashboard',
        projectId: 'project-cloud',
        interactive: true,
        toolInput: { release: '2026.07' },
        toolResult: { content: [{ type: 'text', text: 'ready' }] },
        structuredContent: { checks: 18, failures: 0 },
        error: '',
        resultItem: items[2],
      },
    ],
    claimedItemIds: ['app-registered', 'app-result'],
  });
});

test('standalone and repeated MCP App results remain separate executions', () => {
  const first = mcpEvent('app-result-1', 'mcp_app_result', {
    app_id: 'release-dashboard',
    resource_uri: 'ui://release/dashboard',
    ui_metadata: { title: 'Release dashboard' },
  });
  const second = mcpEvent('app-result-2', 'mcp_app_result', {
    app_id: 'release-dashboard',
    resource_uri: 'ui://release/dashboard',
    ui_metadata: { title: 'Release dashboard' },
    error: 'Renderer unavailable',
  });

  const grouping = groupMCPAppTimelineItems([first, second]);
  assert.deepEqual(
    grouping.groups.map((group) => ({ itemIds: group.itemIds, status: group.status })),
    [
      { itemIds: ['app-result-1'], status: 'ready' },
      { itemIds: ['app-result-2'], status: 'error' },
    ],
  );
});

test('MCP App grouping fails closed across different structured identities', () => {
  const grouping = groupMCPAppTimelineItems([
    mcpEvent('app-register-a', 'mcp_app_registered', {
      app_id: 'app-a',
      title: 'App A',
    }),
    mcpEvent('app-result-b', 'mcp_app_result', {
      app_id: 'app-b',
      ui_metadata: { title: 'App B' },
      resource_uri: 'ui://apps/b',
    }),
  ]);

  assert.deepEqual(
    grouping.groups.map((group) => group.itemIds),
    [['app-register-a'], ['app-result-b']],
  );
});

test('MCP App event detection uses only the protocol event types', () => {
  assert.equal(isMCPAppTimelineEvent(mcpEvent('app-1', 'mcp_app_registered', {})), true);
  assert.equal(isMCPAppTimelineEvent(mcpEvent('app-2', 'mcp_app_result', {})), true);
  assert.equal(
    isMCPAppTimelineEvent({
      id: 'thought-like-app',
      type: 'thought',
      eventTimeUs: 1,
      eventCounter: 1,
      content: 'mcp_app_result',
    }),
    false,
  );
});

test('Desktop preserves live MCP App evidence and exposes a reopenable timeline card', () => {
  const cardSource = readFileSync(
    new URL('../src/features/chat/MCPAppTimelineCard.tsx', import.meta.url),
    'utf8',
  );
  assert.doesNotMatch(
    appSource,
    /const mcpAppCanvasResult[\s\S]{0,180}mcpAppCanvasResult\.handled\) return existing/,
  );
  assert.match(appSource, /onOpenMCPAppResult=/);
  assert.match(chatPanelSource, /onOpenMCPAppResult/);
  assert.match(chatTimelineSource, /kind: 'mcp_app_group'/);
  assert.match(chatTimelineSource, /groupMCPAppTimelineItems/);
  assert.match(chatTimelineSource, /<MCPAppTimelineCard/);
  assert.match(cardSource, /className="mcp-app-timeline-card"/);
  assert.match(cardSource, /mcp-app-structured-content/);
  assert.match(cardSource, /onOpen/);
  assert.match(qaSource, /mcp-app-events/);
  assert.match(qaSource, /mcpAppTimelineItems/);
  assert.equal(
    i18nSource.split("'chat.mcpAppTimelineTitle'").length - 1,
    2,
    'MCP App timeline labels must cover both locales',
  );
});

function mcpEvent(id, type, payload) {
  return { id, type, eventTimeUs: 1, eventCounter: 1, payload };
}
