import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { buildWorkbenchSlots } = require('/tmp/agistack-desktop-test-dist/src/fullHost/workbenchCatalog.js');
const {
  assembleWorkbenchHeader,
  combineWorkbenchLinks,
  desktopHostLinks,
  headerItemActive,
  installedWorkbenchLinks,
  isShellRoot,
  selectWorkbenchSurface,
  shellLanding,
  workbenchHeaderGroups,
} = require('/tmp/agistack-desktop-test-dist/src/fullHost/workbenchModel.js');
const {
  groupWorkbenchHeader,
  layoutWorkbenchHeader,
} = require('/tmp/agistack-desktop-test-dist/agi-stack/packages/plugin-slots/src/workbenchHeader.js');

const tenantMenus = [
  ['tenant-extensions-integrations', ['acp', 'mcp-servers', 'plugins', 'providers', 'templates', 'webhooks']],
  ['tenant-agent-building', ['agent-bindings', 'agent-definitions', 'agent-configuration', 'evolution', 'patterns', 'skills']],
  ['tenant-core-operations', ['agent-workspace', 'analytics', 'overview', 'projects', 'tasks', 'workspaces']],
  ['tenant-governance-management', ['audit-logs', 'billing', 'dead-letter-queue', 'decision-records', 'events', 'org-settings', 'settings', 'trust-policies', 'users']],
  ['tenant-runtime-infrastructure', ['clusters', 'deploy', 'genes', 'instance-templates', 'instances', 'pool', 'runtimes']],
];
const projectMenus = [
  ['project-workspace', ['blackboard', 'overview', 'team', 'workspaces']],
  ['project-configuration', ['channels', 'cron-jobs', 'maintenance', 'schema', 'settings']],
  ['project-knowledge-base', ['communities', 'entities', 'graph', 'memories']],
  ['project-discovery', ['search']],
];

function installedLike(slots, projectId) {
  return slots.map((slot) => ({
    id: slot.id,
    label: slot.label,
    path: slot.path,
    ...(projectId ? { projectId } : {}),
  }));
}

function menus(items) {
  return groupWorkbenchHeader(items).map((group) => [group.id, group.items.map((item) => item.id)]);
}

test('desktop header groups match the original cloud workbench', () => {
  for (const context of ['tenant', 'project']) {
    const slots = buildWorkbenchSlots('t', context === 'project' ? 'p' : null, context);
    const header = layoutWorkbenchHeader(
      installedLike(slots, context === 'project' ? 'p' : undefined),
      slots,
      context,
    );
    assert.deepEqual(menus(header), context === 'tenant' ? tenantMenus : projectMenus);
  }
});

test('a signed page opens its original section from any declared route', () => {
  const page = {
    id: 'tenant-instances',
    title: 'Instances',
    routes: ['/tenant/:tenantId/environments/instances', '/tenant/:tenantId/instances'],
    targets: ['desktop-renderer'],
  };
  const links = installedWorkbenchLinks([{ projectId: null, pluginId: 'memstack-environments', page }], 't');
  const header = layoutWorkbenchHeader(links, buildWorkbenchSlots('t', null, 'tenant'), 'tenant');
  assert.deepEqual(
    header.map((item) => item.id),
    ['instances'],
  );
  assert.equal(header[0].path.split('?')[0], '/tenant/t/instances');
  assert.match(header[0].path, /businessPackage=memstack-environments/);
});

test('slot contributions and nested routes stay out of the header', () => {
  const entries = [
    {
      projectId: null,
      pluginId: 'memstack-environments',
      page: {
        id: 'tenant-instances',
        title: 'Instances',
        routes: ['/tenant/:tenantId/instances'],
        targets: ['desktop-renderer'],
      },
    },
    {
      projectId: null,
      pluginId: 'memstack-environments',
      page: {
        id: 'create-instance',
        title: 'Create instance',
        routes: ['/tenant/:tenantId/instances/create'],
        targets: ['desktop-renderer'],
      },
    },
    {
      projectId: 'p',
      pluginId: 'memstack-environments',
      page: {
        id: 'agent-code',
        title: 'Code',
        routes: ['/tenant/:tenantId/project/:projectId/sandbox'],
        targets: ['desktop-renderer'],
        contributes_to: 'memstack-agent/code@1',
      },
    },
  ];
  const header = assembleWorkbenchHeader(entries, 't', null, '/tenant/t/instances');
  assert.equal(header.some((item) => item.id.includes('create-instance') || item.id.includes('agent-code')), false);
  assert.equal(header.some((item) => item.id === 'instances'), true);
});

test('host destinations keep the original section paths', () => {
  const links = desktopHostLinks('t', 'p');
  const slots = buildWorkbenchSlots('t', null, 'tenant');
  for (const link of links) {
    const path = link.path.split('?')[0];
    assert.equal(slots.some((slot) => slot.path.split('?')[0] === path), true);
  }
  const grouped = workbenchHeaderGroups(
    layoutWorkbenchHeader(combineWorkbenchLinks([], 't', null), slots, 'tenant'),
  );
  const governance = grouped.find((group) => group.id === 'tenant-governance-management');
  assert.deepEqual(
    governance.items.map((item) => item.id),
    ['audit-logs', 'org-settings', 'settings', 'users'],
  );
});

test('nested routes keep their section active and package extras do not', () => {
  const slots = buildWorkbenchSlots('t', null, 'tenant');
  const instances = slots.find((slot) => slot.id === 'instances');
  const organization = slots.find((slot) => slot.id === 'org-settings');
  assert.equal(headerItemActive(instances, '/tenant/t/instances/create'), true);
  assert.equal(headerItemActive(organization, '/tenant/t/org-settings/clusters'), true);
  assert.equal(headerItemActive(organization, '/tenant/t/billing'), false);
  const extra = {
    id: 'release/skills',
    label: 'Agent skills',
    path: '/agent/skills?tenant=t&packageScope=tenant&businessPackage=memstack-agent',
    context: 'tenant',
    displayRole: 'top-nav',
    groupId: 'tenant-extensions-integrations',
    groupLabel: 'nav.extensionsIntegrations',
    relativePath: '/agent/skills?tenant=t&packageScope=tenant&businessPackage=memstack-agent',
    routeFamily: 'tenant',
  };
  assert.equal(headerItemActive(extra, '/agent/skills'), true);
  assert.equal(headerItemActive(extra, '/tenant/t/plugins'), false);
});

test('the shell lands on projects and lets signed clusters replace organization settings', () => {
  assert.equal(shellLanding('t'), '/tenant/t/projects');
  assert.equal(isShellRoot('', 't'), true);
  assert.equal(isShellRoot('/tenant/t', 't'), true);
  assert.equal(selectWorkbenchSurface('/tenant/t/plugins', 't', true), 'market');
  assert.equal(selectWorkbenchSurface('/tenant/t/users', 't', false), 'host');
  assert.equal(selectWorkbenchSurface('/tenant/t/org-settings/info', 't', false), 'host');
  assert.equal(selectWorkbenchSurface('/tenant/t/org-settings/clusters', 't', true), 'page');
  assert.equal(selectWorkbenchSurface('/tenant/t/billing', 't', true), 'page');
  assert.equal(selectWorkbenchSurface('/tenant/t/project/p/memories', 't', true), 'page');
});
