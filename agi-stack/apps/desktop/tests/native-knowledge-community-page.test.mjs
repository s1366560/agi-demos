import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { createElement: h } = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = `${process.env.COMMUNITY_UI_DIST ?? '/tmp/agistack-desktop-test-dist'}/src`;
const { I18nProvider } = require(`${root}/i18n.js`);
const { NativeKnowledgeCommunitiesPage } = require(
  `${root}/features/project-knowledge/NativeKnowledgeCommunitiesPage.js`,
);
const { NativeKnowledgeCommunitiesRouteSurface } = require(
  `${root}/features/project-knowledge/NativeKnowledgeCommunitiesRouteSurface.js`,
);
const { NativeMemoriesRouteContextProvider } = require(
  `${root}/features/project-knowledge/NativeMemoriesRouteContext.js`,
);
const model = {
  phase: 'idle',
  allowedActions: [
    'community_active',
    'community_build',
    'community_audit',
    'create_community_build',
    'select_community_build',
    'process_community_one',
    'retry_community',
    'activate_community_build',
  ],
  active: {
    selection: {
      requested_build_id: 'build',
      active_build_id: 'active',
      revision: 1,
    },
    stale_build_id: null,
  },
  page: {
    build: { build_id: 'build' },
    status: {
      state: 'failed',
      ready_count: 0,
      failed_count: 1,
      insufficient_evidence_count: 0,
    },
    current_graph: true,
    offset: 0,
    limit: 20,
    total: 21,
    items: [
      {
        candidate_id: 'candidate',
        member_count: 2,
        job: { state: 'failed', attempt: 2, failure: 'execution_failed' },
        result: null,
      },
    ],
  },
  audit: null,
  command: null,
  workspaces: [],
  recoveryRequired: false,
  recoveredUnknown: false,
  outcome: null,
  error: null,
};
const controller = {
  refresh() {},
  review() {},
  confirm() {},
  cancel() {},
  loadAudit() {},
};
const render = (m) =>
  renderToStaticMarkup(
    h(I18nProvider, null, h(NativeKnowledgeCommunitiesPage, { model: m, controller })),
  );
test('community page renders state, pagination and explicit process/retry actions', () => {
  const html = render(model);
  for (const text of [
    'Local communities',
    'Process one candidate',
    'Queue failed candidate for retry',
    'Load workspaces',
    'Processing audit',
    '1–20 / 21',
  ])
    assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /nativeCommunity\./);
  assert.match(html, /disabled="">Activate completed build/);
});
test('community page hides writes for read-only authority and locks writes during uncertain outcome', () => {
  const readOnly = render({
    ...model,
    allowedActions: ['community_active', 'community_build'],
  });
  assert.doesNotMatch(readOnly, /<button[^>]*>Queue failed|<button[^>]*>Select build/);
  const uncertain = render({ ...model, recoveryRequired: true });
  assert.match(uncertain, /write outcome is unknown/);
  assert.match(uncertain, /disabled="">Select build/);
  assert.match(uncertain, /<button type="button">Refresh current state/);
});
test('community decision text is escaped and insufficient evidence stays explicit', () => {
  const html = render({
    ...model,
    page: {
      ...model.page,
      items: [
        {
          ...model.page.items[0],
          result: {
            submission: {
              decision: {
                status: 'insufficient_evidence',
                rationale: '<script>no evidence</script>',
                evidence: [],
              },
            },
          },
        },
      ],
    },
  });
  assert.match(html, /Insufficient evidence/);
  assert.match(html, /&lt;script&gt;no evidence/);
  assert.doesNotMatch(html, /<script>/);
});
test('community route rejects mismatched tenant before rendering candidate data', () => {
  const html = renderToStaticMarkup(
    h(
      I18nProvider,
      null,
      h(
        NativeMemoriesRouteContextProvider,
        {
          value: {
            authority: {
              available: true,
              scope: {
                authority: 'local',
                tenantId: 'private',
                projectId: 'project',
              },
            },
          },
        },
        h(NativeKnowledgeCommunitiesRouteSurface, {
          context: { tenantId: 'other', projectId: 'project' },
        }),
      ),
    ),
  );
  assert.doesNotMatch(html, /Local communities|private/);
});

test('native community loader reaches local page without invoking unavailable generic binding', async () => {
  const { createProjectCommunitiesRouteModuleLoader } = require(
    `${root}/features/project-knowledge/projectCommunitiesRouteModule.js`,
  );
  const module = await createProjectCommunitiesRouteModuleLoader({
    createBinding() {
      throw Error('generic_binding_must_not_run');
    },
  })();
  const binding = {
    authority: {
      available: true,
      scope: { authority: 'local', tenantId: 'tenant', projectId: 'project' },
      allowedActions: [],
      userId: 'user',
      sessionId: 'session',
      contextRevision: 1,
      generationDigest: 'digest',
    },
  };
  const html = renderToStaticMarkup(
    h(
      I18nProvider,
      null,
      h(
        NativeMemoriesRouteContextProvider,
        { value: binding },
        h(module.Surface, { context: { tenantId: 'tenant', projectId: 'project' } }),
      ),
    ),
  );
  assert.match(html, /Local communities/);
  assert.match(html, /unavailable for this session/);
});

test('history shows durable receipt identity without treating initial state as live status', () => {
  const html = render({
    ...model,
    page: null,
    allowedActions: ['community_active', 'community_build', 'community_builds'],
    history: {
      items: [
        { build_id: 'unselected-build', created_at_ms: 100, candidate_count: 2, state: 'pending' },
      ],
      total: 1,
      offset: 0,
      limit: 20,
    },
  });
  assert.match(html, /Build history/);
  assert.match(html, /unselected-build/);
  assert.match(html, /Candidates: 2/);
  assert.doesNotMatch(html, /Pending|nativeCommunity\./);
});

test('history safely renders schema-valid timestamps beyond the JavaScript date range', () => {
  const html = render({
    ...model,
    page: null,
    allowedActions: ['community_builds'],
    history: {
      items: [
        {
          build_id: 'future-build',
          created_at_ms: 9_007_199_254_740_991,
          candidate_count: 2,
          state: 'pending',
        },
      ],
      total: 1,
      offset: 0,
      limit: 20,
    },
  });
  assert.match(html, /9007199254740991/);
  assert.doesNotMatch(html, /Invalid Date/);
});
