import assert from 'node:assert/strict';
import { copyFileSync, mkdirSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const require = createRequire(import.meta.url);
const compiledProjectDirectory =
  '/tmp/agistack-desktop-test-dist/src/features/project';
const projectDirectory = dirname(
  fileURLToPath(
    new URL('../src/features/project/ProjectOverviewPage.tsx', import.meta.url),
  ),
);

const {
  buildProjectOverviewPresentation,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/project/projectOverviewPresentationModel.js'
);

mkdirSync(compiledProjectDirectory, { recursive: true });
copyFileSync(
  new URL('../src/features/project/ProjectOverviewPage.css', import.meta.url),
  `${compiledProjectDirectory}/ProjectOverviewPage.css`,
);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  ProjectOverviewPage,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/project/ProjectOverviewPage.js'
);

const pageSource = readFileSync(`${projectDirectory}/ProjectOverviewPage.tsx`, 'utf8');
const stylesheet = readFileSync(`${projectDirectory}/ProjectOverviewPage.css`, 'utf8');
const globalStylesheet = readFileSync(
  new URL('../src/styles.css', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(
  new URL('../src/i18n.tsx', import.meta.url),
  'utf8',
);
const messagesSource = readFileSync(
  new URL(
    '../src/features/project/locales/projectOverviewMessages.ts',
    import.meta.url,
  ),
  'utf8',
);

const cloudScope = {
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
};
const localScope = {
  authority: 'local',
  tenantId: 'local-tenant',
  projectId: 'local-project',
};

const cloudSnapshot = {
  scope: cloudScope,
  project: {
    id: 'project-1',
    tenant_id: 'tenant-1',
    name: 'Desktop parity',
    description: 'Native Cloud overview',
    created_at: '2026-07-30T00:00:00Z',
    updated_at: '2026-07-30T01:00:00Z',
  },
  stats: {
    memory_count: 8,
    storage_used: 1024,
    storage_limit: 8192,
    active_nodes: 4,
    collaborators: 3,
  },
  latestMemories: [
    {
      id: 'memory-1',
      project_id: 'project-1',
      title: 'Parity contract',
      content: 'Project Overview uses explicit Cloud authority.',
      content_type: 'text',
      status: 'ACTIVE',
      metadata: {},
      created_at: '2026-07-30T00:30:00Z',
      updated_at: null,
    },
  ],
  latestMemoriesTotal: 1,
};

const localSnapshot = {
  scope: localScope,
  capability: {
    availability: 'degraded',
    reasonCode: 'local_project_overview_timeline_projection_only',
    serviceVersion: '0.1.0',
    contractVersion: '3.0.0',
    allowedActions: ['view'],
    scope: {
      tenantId: 'local-tenant',
      projectId: 'local-project',
      workspaceId: null,
      instanceId: null,
    },
    authorityRevision: 7,
  },
  backfillCursor: null,
  project: {
    availability: 'available',
    reasonCode: null,
    value: {
      id: 'local-project',
      tenantId: 'local-tenant',
      name: 'Local research',
      description: 'On-device project',
      agentConversationMode: 'workspace',
      createdAt: '2026-07-30T00:00:00Z',
    },
  },
  conversationCount: {
    availability: 'available',
    reasonCode: null,
    value: 2,
  },
  recentKnowledgeItems: {
    availability: 'degraded',
    reasonCode: 'local_project_overview_timeline_projection_only',
    source: 'desktop_timeline',
    total: 1,
    value: [
      {
        id: 'knowledge-1',
        conversationId: 'conversation-1',
        title: 'Local evidence',
        content: 'Projected from the local desktop timeline.',
        resultType: 'message',
        source: 'desktop_timeline',
        createdAt: '2026-07-30T00:15:00Z',
        tags: ['desktop'],
      },
    ],
  },
  activeNodes: {
    availability: 'unavailable',
    reasonCode: 'local_project_graph_projection_unavailable',
    value: null,
  },
  storageQuota: {
    availability: 'not_applicable',
    reasonCode: 'local_project_storage_quota_not_applicable',
    value: null,
  },
  collaborators: {
    availability: 'not_applicable',
    reasonCode: 'local_project_collaboration_governance_not_applicable',
    value: null,
  },
};

function render(input, onRetry = () => {}) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(ProjectOverviewPage, {
        model: buildProjectOverviewPresentation(input),
        onRetry,
      }),
    ),
  );
}

test('Cloud presentation exposes project, stats, and latest memories', () => {
  const model = buildProjectOverviewPresentation({
    kind: 'cloud-ready',
    snapshot: cloudSnapshot,
  });

  assert.equal(model.state, 'ready');
  assert.equal(model.authority, 'cloud');
  assert.equal(model.project?.name, 'Desktop parity');
  assert.deepEqual(
    model.summaryFields.map((field) => [
      field.id,
      field.availability,
      field.value,
      field.secondaryValue,
    ]),
    [
      ['memory_count', 'available', 8, null],
      ['storage', 'available', 1024, 8192],
      ['active_nodes', 'available', 4, null],
      ['collaborators', 'available', 3, null],
    ],
  );
  assert.equal(model.recent.kind, 'memories');
  assert.equal(model.recent.items[0]?.title, 'Parity contract');
  assert.equal(model.retryVisible, false);

  const markup = render({ kind: 'cloud-ready', snapshot: cloudSnapshot });
  assert.match(markup, /Desktop parity/);
  assert.match(markup, /Latest memories/);
  assert.match(markup, /Parity contract/);
  assert.match(markup, /Project memories/);
  assert.match(markup, /Storage/);
  assert.match(markup, /Graph nodes/);
  assert.match(markup, /Collaborators/);
});

test('Cloud ready state keeps an explicit empty latest-memory collection', () => {
  const snapshot = {
    ...cloudSnapshot,
    latestMemories: [],
    latestMemoriesTotal: 0,
  };
  const model = buildProjectOverviewPresentation({
    kind: 'cloud-ready',
    snapshot,
  });

  assert.equal(model.state, 'ready');
  assert.equal(model.recent.kind, 'memories');
  assert.deepEqual(model.recent.items, []);

  const markup = render({ kind: 'cloud-ready', snapshot });
  assert.match(markup, /No recent memories/);
  assert.doesNotMatch(markup, /Project not found/);
});

test('Local degraded presentation uses knowledge semantics and preserves field authority', () => {
  const model = buildProjectOverviewPresentation({
    kind: 'local-ready',
    snapshot: localSnapshot,
  });

  assert.equal(model.state, 'degraded');
  assert.equal(model.authority, 'local');
  assert.equal(model.reasonCode, 'local_project_overview_timeline_projection_only');
  assert.equal(model.recent.kind, 'knowledge_items');
  assert.equal(model.recent.items[0]?.title, 'Local evidence');
  assert.deepEqual(
    model.summaryFields.map((field) => [
      field.id,
      field.availability,
      field.reasonCode,
      field.value,
    ]),
    [
      ['conversation_count', 'available', null, 2],
      [
        'active_nodes',
        'unavailable',
        'local_project_graph_projection_unavailable',
        null,
      ],
      [
        'storage_quota',
        'not_applicable',
        'local_project_storage_quota_not_applicable',
        null,
      ],
      [
        'collaborators',
        'not_applicable',
        'local_project_collaboration_governance_not_applicable',
        null,
      ],
    ],
  );

  const markup = render({ kind: 'local-ready', snapshot: localSnapshot });
  assert.match(markup, /Degraded local projection/);
  assert.match(markup, /Recent knowledge items/);
  assert.match(markup, /Local evidence/);
  assert.match(markup, /Unavailable/);
  assert.match(markup, /Not applicable/);
  assert.match(markup, /local_project_graph_projection_unavailable/);
  assert.match(markup, /local_project_storage_quota_not_applicable/);
  assert.match(markup, /local_project_collaboration_governance_not_applicable/);
  assert.doesNotMatch(markup, /Latest memories/);
  assert.doesNotMatch(markup, />0 B</);
  assert.doesNotMatch(markup, />0<\/strong>/);
});

test('loading and scope switch states never retain stale project data', () => {
  const loading = buildProjectOverviewPresentation({
    kind: 'loading',
    scope: cloudScope,
    scopeSwitch: false,
  });
  const switching = buildProjectOverviewPresentation({
    kind: 'loading',
    scope: {
      ...cloudScope,
      projectId: 'project-2',
    },
    scopeSwitch: true,
  });

  assert.equal(loading.state, 'loading');
  assert.equal(switching.state, 'scope_switch');
  assert.equal(loading.project, null);
  assert.equal(switching.project, null);
  assert.deepEqual(switching.summaryFields, []);
  assert.deepEqual(switching.recent.items, []);

  const loadingMarkup = render({
    kind: 'loading',
    scope: cloudScope,
    scopeSwitch: false,
  });
  const switchingMarkup = render({
    kind: 'loading',
    scope: { ...cloudScope, projectId: 'project-2' },
    scopeSwitch: true,
  });
  assert.match(loadingMarkup, /Loading project overview/);
  assert.match(loadingMarkup, /aria-busy="true"/);
  assert.match(switchingMarkup, /Switching project scope/);
  assert.match(switchingMarkup, /project-2/);
  assert.doesNotMatch(switchingMarkup, /Desktop parity/);
});

test('empty, forbidden, unavailable, and error states remain distinct', () => {
  const cases = [
    {
      input: { kind: 'empty', scope: cloudScope },
      state: 'empty',
      expected: /Project not found/,
      retry: true,
    },
    {
      input: {
        kind: 'forbidden',
        scope: cloudScope,
        reasonCode: 'project_overview_forbidden',
      },
      state: 'forbidden',
      expected: /Project access denied/,
      retry: false,
    },
    {
      input: {
        kind: 'unavailable',
        scope: localScope,
        reasonCode: 'local_project_overview_store_unavailable',
        retryable: true,
      },
      state: 'unavailable',
      expected: /Project overview unavailable/,
      retry: true,
    },
    {
      input: {
        kind: 'error',
        scope: cloudScope,
        reasonCode: 'project_overview_load_failed',
        detail: 'Authority timed out.',
        retryable: true,
      },
      state: 'error',
      expected: /Project overview could not be loaded/,
      retry: true,
    },
  ];

  for (const expectedCase of cases) {
    const model = buildProjectOverviewPresentation(expectedCase.input);
    assert.equal(model.state, expectedCase.state);
    assert.equal(model.retryVisible, expectedCase.retry);
    const markup = render(expectedCase.input);
    assert.match(markup, expectedCase.expected);
    assert.equal(markup.includes('Retry</button>'), expectedCase.retry);
    assert.doesNotMatch(markup, /project-overview-summary-grid/);
  }
});

test('error retry is an explicit user action', () => {
  let retryCount = 0;
  const markup = render(
    {
      kind: 'error',
      scope: cloudScope,
      reasonCode: 'project_overview_load_failed',
      detail: 'Authority timed out.',
      retryable: true,
    },
    () => {
      retryCount += 1;
    },
  );

  assert.match(markup, /Retry<\/button>/);
  assert.equal(retryCount, 0);
  assert.match(pageSource, /onClick=\{onRetry\}/);
});

test('page uses Desktop tokens, responsive layout, reduced motion, and bilingual i18n', () => {
  assert.match(pageSource, /useI18n\(\)/);
  assert.doesNotMatch(pageSource, /antd|@\/pages|web\/src/);
  assert.match(stylesheet, /var\(--desktop-surface-3\)/);
  assert.match(stylesheet, /var\(--desktop-border\)/);
  assert.match(stylesheet, /@media \(max-width:/);
  assert.match(stylesheet, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(stylesheet, /:focus-visible/);
  const referencedTokens = new Set(
    [...stylesheet.matchAll(/var\((--desktop-[a-z0-9-]+)/g)].map(
      (match) => match[1],
    ),
  );
  for (const token of referencedTokens) {
    assert.match(globalStylesheet, new RegExp(`${token}\\s*:`));
  }
  assert.match(i18nSource, /import \{[\s\S]*projectOverviewEnUS,[\s\S]*projectOverviewZhCN/);
  assert.match(i18nSource, /\.\.\.projectOverviewEnUS/);
  assert.match(i18nSource, /\.\.\.projectOverviewZhCN/);

  for (const key of [
    'projectOverview.loading.title',
    'projectOverview.scopeSwitch.title',
    'projectOverview.cloud.latestMemories',
    'projectOverview.local.recentKnowledgeItems',
    'projectOverview.state.forbidden.title',
    'projectOverview.state.unavailable.title',
    'projectOverview.availability.degraded',
    'projectOverview.reasonCode',
  ]) {
    assert.equal(messagesSource.split(`'${key}'`).length, 3);
  }
});
