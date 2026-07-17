import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const reviewSource = readFileSync(
  new URL('../src/features/session/SessionPlanReview.tsx', import.meta.url),
  'utf8',
);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const { SessionPlanReview, SessionTaskListReview } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/SessionPlanReview.js'
);

const plan = {
  id: 'plan-version-3',
  conversation_id: 'conversation-1',
  version: 3,
  status: 'draft',
  tasks: [
    { id: 'task-1', content: 'Review the persisted plan', status: 'pending', priority: 'high' },
    { id: 'task-2', content: 'Start the bound run', status: 'pending', priority: 'medium' },
  ],
  created_at: '2026-07-16T09:00:00Z',
  approved_at: null,
};

const capabilities = {
  canSendMessage: true,
  canApprovePlan: true,
  canRespondToHitl: false,
  canSteerNow: false,
  canQueueNext: false,
  canReviewArtifacts: false,
  canDeliverArtifacts: false,
  runActions: [],
  allowedActions: ['send_message', 'approve_plan_and_start'],
};

function renderReview(overrides = {}) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(SessionPlanReview, {
        plan,
        capabilities,
        capabilityMode: 'code',
        pending: false,
        onApprove: async () => {},
        ...overrides,
      }),
    ),
  );
}

test('draft review renders persisted steps and an enabled atomic approval action', () => {
  const markup = renderReview();
  assert.match(markup, /Plan version 3/);
  assert.match(markup, /Review the persisted plan/);
  assert.match(markup, /Start the bound run/);
  assert.match(markup, /Approve version 3 &amp; start/);
  assert.doesNotMatch(markup, /<button[^>]*disabled/);
  assert.match(markup, /<option value="worktree" selected="">Isolated worktree<\/option>/);
  assert.match(markup, /<option value="workspace_write" selected="">Workspace write<\/option>/);
  assert.match(markup, /High priority · Pending/);
  assert.doesNotMatch(markup, /high priority · pending/);
});

test('task-list authority remains readable and resumes guarded review without direct approval', () => {
  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(SessionTaskListReview, {
        tasks: plan.tasks,
        onResumeReview: () => {},
      }),
    ),
  );

  assert.match(markup, /Recovered Agent task list/);
  assert.match(markup, /Review the persisted plan/);
  assert.match(markup, /Resume guarded review/);
  assert.match(markup, /rechecked against the authoritative task list/);
  assert.doesNotMatch(markup, /Approve version/);
  assert.doesNotMatch(markup, /&amp; start/);
});

test('draft review fails closed when either approval capability signal is absent', () => {
  const withoutAction = renderReview({
    capabilities: { ...capabilities, allowedActions: ['send_message'] },
  });
  assert.match(withoutAction, /<button[^>]*disabled/);

  const withoutFlag = renderReview({
    capabilities: { ...capabilities, canApprovePlan: false },
  });
  assert.match(withoutFlag, /<button[^>]*disabled/);
});

test('pending approval announces progress and marks the approval region busy', () => {
  const markup = renderReview({ pending: true });

  assert.match(markup, /aria-busy="true"/);
  assert.match(markup, /aria-live="polite"/);
  assert.match(markup, /aria-atomic="true"/);
  assert.match(markup, /<button[^>]*disabled/);
  assert.match(markup, /Starting approved run…/);
});

test('approved plan stays readable without retaining a Plan to Build action', () => {
  const markup = renderReview({
    plan: {
      ...plan,
      status: 'approved',
      approved_at: '2026-07-16T09:18:00Z',
    },
    capabilities: {
      ...capabilities,
      canApprovePlan: false,
      allowedActions: [],
    },
  });
  assert.match(markup, /Plan approved/);
  assert.doesNotMatch(markup, /Approve version 3/);
});

test('select changes capture event values before entering functional state updates', () => {
  assert.match(
    reviewSource,
    /const environmentKind = event\.currentTarget[\s\S]*?setSelection\(\(current\) => \(\{[\s\S]*?environmentKind,/,
  );
  assert.match(
    reviewSource,
    /const permissionProfile = event\.currentTarget\.value[\s\S]*?setSelection\(\(current\) => \(\{[\s\S]*?permissionProfile,/,
  );
  assert.doesNotMatch(
    reviewSource,
    /setSelection\(\(current\) => \(\{[\s\S]{0,180}?event\.currentTarget\.value/,
  );
});
