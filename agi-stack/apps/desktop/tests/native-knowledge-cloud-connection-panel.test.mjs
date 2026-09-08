import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = '/tmp/agistack-desktop-test-dist/src';
const { I18nProvider } = require(`${root}/i18n.js`);
const { NativeKnowledgeCloudConnectionPanel } = require(
  `${root}/features/project-knowledge/NativeKnowledgeCloudConnectionPanel.js`,
);
const { nativeKnowledgeCloudConnectionEnUS, nativeKnowledgeCloudConnectionZhCN } = require(
  `${root}/features/project-knowledge/nativeKnowledgeCloudConnectionMessages.js`,
);
const noop = async () => {};
const controller = {
  refresh: noop,
  login: noop,
  changePassword: noop,
  disconnect: noop,
  selectTenant: noop,
  selectProject: noop,
  enroll: noop,
  bind: noop,
};
const empty = {
  phase: 'idle',
  connection: null,
  tenants: [],
  projects: [],
  selectedTenantId: null,
  selectedProjectId: null,
  enrollment: null,
  bound: false,
  error: null,
};
const connected = {
  ...empty,
  phase: 'ready',
  connection: {
    authority: 'https://cloud.example/api/v1',
    actor_id: 'cloud-user',
    connection_revision: 'private-revision',
  },
  tenants: [{ id: 'tenant-1', name: 'Cloud tenant one' }],
  projects: [{ id: 'project-1', tenant_id: 'tenant-1', name: 'Cloud project one' }],
  selectedTenantId: 'tenant-1',
  selectedProjectId: 'project-1',
};
const render = (model, disabled = false) =>
  renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(NativeKnowledgeCloudConnectionPanel, { model, controller, disabled }),
    ),
  );

test('disconnected form uses the declared cloud preset and never includes prefilled credentials', () => {
  const html = render(empty);
  assert.match(html, /http:\/\/127\.0\.0\.1:8000/);
  assert.match(html, /type="password"[^>]*value=""/);
  assert.match(html, /Your local workspace stays active/);
  assert.doesNotMatch(html, /adminpassword|admin@|localStorage|sessionStorage/);
});

test('connected projection displays observed names and IDs but no connection revision or credential form', () => {
  const html = render(connected);
  assert.match(html, /cloud-user/);
  assert.match(html, /Cloud tenant one \(tenant-1\)/);
  assert.match(html, /Cloud project one \(project-1\)/);
  assert.doesNotMatch(html, /private-revision|type="password"/);
});

test('enrollment is explicit and association requires enabled enrollment', () => {
  const eligible = render({ ...connected, enrollment: { enabled: false, can_enroll: true } });
  assert.match(eligible, />Enable cloud project synchronization<\/button>/);
  assert.doesNotMatch(eligible, />Associate this local project<\/button>/);
  const forbidden = render({ ...connected, enrollment: { enabled: false, can_enroll: false } });
  assert.match(forbidden, /Ask a cloud project administrator/);
  assert.doesNotMatch(forbidden, />Enable cloud project synchronization<\/button>/);
  const enabled = render({ ...connected, enrollment: { enabled: true, can_enroll: false } });
  assert.match(enabled, />Associate this local project<\/button>/);
});

test('in-flight authentication can be disconnected while the outer operation lock disables the panel', () => {
  const html = render({ ...empty, phase: 'authenticating' });
  assert.match(html, /<fieldset disabled="">/);
  assert.match(html, /<button type="button">Disconnect cloud account<\/button>/);
  assert.match(render(empty, true), /<fieldset[^>]*disabled=""/);
});

test('forced password change presents a separate form without a competing login action', () => {
  const html = render({ ...empty, phase: 'password_change_required' });
  assert.match(html, /Current password/);
  assert.match(html, /New password/);
  assert.match(html, /Change password and continue/);
  assert.doesNotMatch(html, /Connect cloud account<\/button>/);
});

test('bound state describes a manual next step and both locales cover every panel message', () => {
  const html = render({
    ...connected,
    enrollment: { enabled: true, can_enroll: true },
    bound: true,
  });
  assert.match(html, /Start pull or push manually/);
  assert.doesNotMatch(html, />Associate this local project<\/button>/);
  assert.deepEqual(
    Object.keys(nativeKnowledgeCloudConnectionEnUS).sort(),
    Object.keys(nativeKnowledgeCloudConnectionZhCN).sort(),
  );
});
