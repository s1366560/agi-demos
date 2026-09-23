import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const jsx = (type, props) => ({ type, props });
function harness(overrides = {}) {
  let query = '';
  const module = { exports: {} };
  const calls = [];
  const management = {
    servers: [
      { id: 'a', name: 'Files', server_type: 'stdio', project_id: 'project-one', enabled: true, runtime_status: 'connected' },
      { id: 'b', name: 'Search', server_type: 'sse', project_id: 'project-two', enabled: false, runtime_status: 'disconnected' },
    ],
    loading: false, error: null, actionBusyId: null,
    openEdit: (server) => calls.push(['edit', server.id]),
    toggleServer: (server) => calls.push(['toggle', server.id]),
    testServer: (id) => calls.push(['test', id]),
    ...overrides,
  };
  const code = ts.transpileModule(readFileSync(new URL('../src/features/settings/MCPServerSettingsPage.tsx', import.meta.url), 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
  }).outputText;
  new Function('require', 'module', 'exports', code)((name) => {
    if (name === 'react') return { useState: () => [query, (value) => { query = value; }] };
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
    if (name.includes('react-icons')) return {};
    if (name === '../../i18n') return { useI18n: () => ({ t: (key) => key }) };
    if (name.endsWith('.css')) return {};
    if (name === './SettingsCorePages') return { SettingsPage: 'page' };
    if (name === './ManagedResourceViews') return { SettingsState: 'state' };
    throw new Error(`Unexpected dependency ${name}`);
  }, module, module.exports);
  return { calls, render: (canManage = true) => module.exports.MCPServerSettingsPage({ management, canManage }) };
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}

test('MCP catalog filters by name, project or transport and leaves source entries intact', () => {
  const h = harness();
  let tree = h.render();
  assert.equal(nodes(tree).filter((n) => n.type === 'article').length, 2);
  nodes(tree).find((n) => n.type === 'input').props.onChange({ target: { value: 'PROJECT-TWO' } });
  tree = h.render();
  assert.equal(nodes(tree).filter((n) => n.type === 'article').length, 1);
  assert.ok(nodes(tree).some((n) => n.props?.children === 'Search'));
  nodes(tree).find((n) => n.type === 'input').props.onChange({ target: { value: 'none' } });
  assert.ok(nodes(h.render()).some((n) => n.type === 'state' && n.props.text === 'settings.noMatches'));
  nodes(h.render()).find((n) => n.type === 'input').props.onChange({ target: { value: '' } });
  assert.equal(nodes(h.render()).filter((n) => n.type === 'article').length, 2);
});

test('MCP actions retain exact server identity and permission gates in separated action rows', () => {
  const h = harness();
  const buttons = nodes(h.render()).filter((n) => n.type === 'button');
  buttons.find((n) => n.props.children === 'common.edit').props.onClick();
  assert.deepEqual(h.calls, [['edit', 'a']]);
  assert.ok(nodes(h.render(false)).filter((n) => n.type === 'article').every((row) =>
    nodes(row).filter((n) => n.type === 'button').every((button) => button.props.disabled),
  ));
});

test('MCP catalog keeps loading and failed fetch states visible while searching', () => {
  assert.ok(nodes(harness({ loading: true }).render()).some((n) => n.props?.text === 'settings.mcpServers.loading'));
  assert.ok(nodes(harness({ error: 'Unavailable' }).render()).some((n) => n.type === 'state' && n.props.error && n.props.text === 'Unavailable'));
});


test('MCP supervisor status reflects observed health instead of enablement or cached tools', () => {
  for (const [runtime_status, expected] of [
    ['healthy', 'connected'], ['starting', 'connecting'], ['stopped', 'disconnected'],
    ['error', 'error'], ['connected', 'connected'], ['future-state', 'unknown'],
  ]) {
    const tree = harness({ servers: [{ id: 'plugin-mcp', name: 'Plugin tool', enabled: true, runtime_status, discovered_tools: [{ name: 'echo' }] }] }).render();
    assert.ok(nodes(tree).some((node) => node.props?.children === `settings.mcpServers.runtime.${expected}`), runtime_status);
  }
  const disabled = harness({ servers: [{ id: 'plugin-mcp', name: 'Plugin tool', enabled: false, runtime_status: 'healthy' }] }).render();
  assert.ok(nodes(disabled).some((node) => node.props?.children === 'settings.mcpServers.runtime.disabled'));
});
