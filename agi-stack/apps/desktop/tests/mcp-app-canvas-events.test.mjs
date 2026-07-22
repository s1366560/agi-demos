import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  applyMCPAppCanvasStreamEvent,
  closeMCPAppCanvasTab,
  emptyMCPAppCanvasState,
  selectMCPAppCanvasTab,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/mcpAppCanvasEventModel.js');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentSource = readFileSync(
  new URL('../src/features/chat/DesktopMCPAppCanvas.tsx', import.meta.url),
  'utf8',
);
const qaSource = readFileSync(new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url), 'utf8');

test('mcp_app_result opens an interactive canvas tab from a nested server event', () => {
  const result = applyMCPAppCanvasStreamEvent(emptyMCPAppCanvasState(), {
    type: 'agent_event',
    data: {
      event_type: 'mcp_app_result',
      data: {
        app_id: 'release-dashboard',
        tool_name: 'show_release_dashboard',
        server_name: 'release-tools',
        resource_uri: 'ui://release/dashboard',
        resource_html: '<!doctype html><title>Release dashboard</title>',
        tool_input: { release: '2026.07' },
        tool_result: { content: [{ type: 'text', text: 'ready' }] },
        structured_content: { passed: 18, failed: 0 },
        ui_metadata: { title: 'Release dashboard', prefersBorder: true },
        project_id: 'project-cloud',
      },
    },
  });

  assert.equal(result.handled, true);
  assert.equal(result.action, 'open');
  assert.equal(result.state.activeTabId, 'mcp-app-ui://release/dashboard');
  assert.equal(result.state.openRevision, 1);
  assert.deepEqual(result.state.tabs, [
    {
      id: 'mcp-app-ui://release/dashboard',
      appId: 'release-dashboard',
      title: 'Release dashboard',
      toolName: 'show_release_dashboard',
      serverName: 'release-tools',
      resourceUri: 'ui://release/dashboard',
      resourceHtml: '<!doctype html><title>Release dashboard</title>',
      toolInput: { release: '2026.07' },
      toolResult: {
        content: [{ type: 'text', text: 'ready' }],
        structuredContent: { passed: 18, failed: 0 },
      },
      uiMetadata: { title: 'Release dashboard', prefersBorder: true },
      projectId: 'project-cloud',
    },
  ]);
});

test('repeated app results replace one stable tab and preserve immutable state', () => {
  const first = applyMCPAppCanvasStreamEvent(emptyMCPAppCanvasState(), {
    type: 'mcp_app_result',
    data: {
      app_id: 'release-dashboard',
      tool_name: 'show_release_dashboard',
      resource_uri: 'ui://release/dashboard',
      resource_html: '<p>First</p>',
    },
  }).state;
  const second = applyMCPAppCanvasStreamEvent(first, {
    type: 'mcp_app_result',
    data: {
      app_id: 'release-dashboard',
      tool_name: 'show_release_dashboard',
      resource_uri: 'ui://release/dashboard',
      resource_html: '<p>Second</p>',
    },
  }).state;

  assert.notEqual(first, second);
  assert.equal(first.tabs[0].resourceHtml, '<p>First</p>');
  assert.equal(second.tabs.length, 1);
  assert.equal(second.tabs[0].resourceHtml, '<p>Second</p>');
  assert.equal(second.openRevision, 2);
});

test('selection and close choose a stable fallback without mutating unrelated tabs', () => {
  let state = emptyMCPAppCanvasState();
  for (const [appId, resourceUri] of [
    ['app-one', 'ui://apps/one'],
    ['app-two', 'ui://apps/two'],
  ]) {
    state = applyMCPAppCanvasStreamEvent(state, {
      type: 'mcp_app_result',
      data: {
        app_id: appId,
        tool_name: appId,
        resource_uri: resourceUri,
        resource_html: `<p>${appId}</p>`,
      },
    }).state;
  }

  state = selectMCPAppCanvasTab(state, 'mcp-app-ui://apps/one');
  assert.equal(state.activeTabId, 'mcp-app-ui://apps/one');
  const closed = closeMCPAppCanvasTab(state, 'mcp-app-ui://apps/one');
  assert.deepEqual(closed.tabs.map((tab) => tab.appId), ['app-two']);
  assert.equal(closed.activeTabId, 'mcp-app-ui://apps/two');
});

test('non-UI and malformed MCP results are consumed without opening an empty canvas', () => {
  const nonUi = applyMCPAppCanvasStreamEvent(emptyMCPAppCanvasState(), {
    type: 'mcp_app_result',
    data: { app_id: 'echo', tool_name: 'echo', tool_result: 'hello' },
  });
  assert.equal(nonUi.handled, true);
  assert.equal(nonUi.action, null);
  assert.equal(nonUi.state.tabs.length, 0);

  const unrelated = applyMCPAppCanvasStreamEvent(emptyMCPAppCanvasState(), {
    type: 'assistant_message',
    data: {},
  });
  assert.equal(unrelated.handled, false);
});

test('Desktop consumes MCP App results into an official sandboxed renderer and Browser QA', () => {
  assert.match(appSource, /applyMCPAppCanvasStreamEvent\(nextMCPAppCanvas, event\)/);
  assert.doesNotMatch(
    appSource,
    /const mcpAppCanvasResult[\s\S]{0,180}mcpAppCanvasResult\.handled\) return existing/,
  );
  assert.match(appSource, /const openMCPAppResult = useCallback/);
  assert.match(appSource, /setReviewTab\('apps'\)/);
  assert.match(componentSource, /import\('@mcp-ui\/client'\)/);
  assert.match(componentSource, /sandbox=\{sandboxConfig\}/);
  assert.doesNotMatch(componentSource, /dangerouslySetInnerHTML/);
  assert.match(qaSource, /mcp-app-events/);
  assert.match(qaSource, /Release verification dashboard/);
});
