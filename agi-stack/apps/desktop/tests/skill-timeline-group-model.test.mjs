import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { groupSkillTimelineItems, isSkillTimelineEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/skillTimelineGroupModel.js',
);

const skillTimelineCardSource = readFileSync(
  new URL('../src/features/chat/SkillTimelineCard.tsx', import.meta.url),
  'utf8',
);
const chatTimelineSource = readFileSync(
  new URL('../src/features/chat/ChatTimeline.tsx', import.meta.url),
  'utf8',
);
const sessionSteeringQaSource = readFileSync(
  new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

test('skill lifecycle events become one structured execution with tool-chain evidence', () => {
  const items = [
    {
      id: 'skill-match-1',
      type: 'skill_matched',
      eventTimeUs: 1,
      eventCounter: 1,
      payload: {
        skill_id: 'skill-release-guard',
        skill_name: 'Release guard',
        tools: ['read_file', 'shell_command'],
        match_score: 0.96,
        execution_mode: 'direct',
      },
    },
    {
      id: 'skill-start-1',
      type: 'skill_execution_start',
      eventTimeUs: 2,
      eventCounter: 2,
      payload: {
        skill_id: 'skill-release-guard',
        skill_name: 'Release guard',
        query: 'Run release checks',
        total_steps: 2,
      },
    },
    {
      id: 'skill-tool-start-1',
      type: 'skill_tool_start',
      eventTimeUs: 3,
      eventCounter: 3,
      payload: {
        skill_id: 'skill-release-guard',
        skill_name: 'Release guard',
        tool_name: 'shell_command',
        tool_input: { command: 'pnpm test' },
        step_index: 1,
        total_steps: 2,
        status: 'running',
      },
    },
    {
      id: 'skill-tool-result-1',
      type: 'skill_tool_result',
      eventTimeUs: 4,
      eventCounter: 4,
      payload: {
        skill_id: 'skill-release-guard',
        skill_name: 'Release guard',
        tool_name: 'shell_command',
        result: 'All release checks passed',
        duration_ms: 812,
        step_index: 1,
        total_steps: 2,
        status: 'completed',
      },
    },
    {
      id: 'skill-complete-1',
      type: 'skill_execution_complete',
      eventTimeUs: 5,
      eventCounter: 5,
      payload: {
        skill_id: 'skill-release-guard',
        skill_name: 'Release guard',
        success: true,
        summary: 'Release checks passed',
        tool_results: [
          { tool_name: 'read_file', status: 'completed' },
          { tool_name: 'shell_command', status: 'completed' },
        ],
        execution_time_ms: 1_240,
      },
    },
  ];

  assert.deepEqual(groupSkillTimelineItems(items), {
    groups: [
      {
        id: 'skill-group:skill-match-1:skill-complete-1',
        startItemId: 'skill-match-1',
        itemIds: items.map((item) => item.id),
        items,
        skillId: 'skill-release-guard',
        skillName: 'Release guard',
        status: 'completed',
        executionMode: 'direct',
        matchScore: 0.96,
        tools: ['read_file', 'shell_command'],
        query: 'Run release checks',
        currentStep: 2,
        totalSteps: 2,
        toolSteps: [
          {
            key: 'skill-release-guard:0:read_file',
            stepIndex: 0,
            toolName: 'read_file',
            input: undefined,
            result: undefined,
            error: '',
            durationMs: null,
            status: 'completed',
          },
          {
            key: 'skill-release-guard:1:shell_command',
            stepIndex: 1,
            toolName: 'shell_command',
            input: { command: 'pnpm test' },
            result: 'All release checks passed',
            error: '',
            durationMs: 812,
            status: 'completed',
          },
        ],
        summary: 'Release checks passed',
        error: '',
        reason: '',
        executionTimeMs: 1_240,
      },
    ],
    claimedItemIds: items.map((item) => item.id),
  });
});

test('skill grouping associates terminal evidence across interleaved main-agent work', () => {
  const items = [
    {
      id: 'skill-start-2',
      type: 'skill_execution_start',
      eventTimeUs: 1,
      eventCounter: 1,
      payload: {
        skill_id: 'skill-review',
        skill_name: 'Review skill',
        total_steps: 1,
      },
    },
    {
      id: 'main-thought-1',
      type: 'thought',
      eventTimeUs: 2,
      eventCounter: 2,
      content: 'Waiting for the skill execution result.',
    },
    {
      id: 'skill-complete-2',
      type: 'skill_execution_complete',
      eventTimeUs: 3,
      eventCounter: 3,
      payload: {
        skill_id: 'skill-review',
        skill_name: 'Review skill',
        success: true,
        summary: 'Review complete',
      },
    },
  ];

  const grouping = groupSkillTimelineItems(items);
  assert.equal(grouping.groups.length, 1);
  assert.deepEqual(grouping.groups[0].itemIds, ['skill-start-2', 'skill-complete-2']);
  assert.deepEqual(grouping.claimedItemIds, ['skill-start-2', 'skill-complete-2']);
});

test('different skills and repeated terminal executions never merge', () => {
  const grouping = groupSkillTimelineItems([
    skillEvent('release-match-1', 'skill_matched', 'release', 'Release'),
    skillEvent('audit-match-1', 'skill_matched', 'audit', 'Audit'),
    skillEvent('release-complete-1', 'skill_execution_complete', 'release', 'Release', {
      success: true,
    }),
    skillEvent('audit-fallback-1', 'skill_fallback', 'audit', 'Audit', {
      reason: 'execution_error',
      error: 'Runtime unavailable',
    }),
    skillEvent('release-match-2', 'skill_matched', 'release', 'Release'),
    skillEvent('release-complete-2', 'skill_execution_complete', 'release', 'Release', {
      success: false,
      error: 'Verification failed',
    }),
  ]);

  assert.deepEqual(
    grouping.groups.map((group) => ({
      status: group.status,
      itemIds: group.itemIds,
      skillId: group.skillId,
    })),
    [
      {
        status: 'completed',
        itemIds: ['release-match-1', 'release-complete-1'],
        skillId: 'release',
      },
      {
        status: 'fallback',
        itemIds: ['audit-match-1', 'audit-fallback-1'],
        skillId: 'audit',
      },
      {
        status: 'failed',
        itemIds: ['release-match-2', 'release-complete-2'],
        skillId: 'release',
      },
    ],
  );
});

test('skill event detection uses the exact protocol event set', () => {
  assert.equal(isSkillTimelineEvent(skillEvent('skill-1', 'skill_tool_start', 'a', 'A')), true);
  assert.equal(
    isSkillTimelineEvent({
      id: 'skill-like-thought',
      type: 'thought',
      content: 'skill_execution_complete',
      eventTimeUs: 1,
      eventCounter: 1,
    }),
    false,
  );
});

test('a failed tool result does not claim unobserved steps before a terminal event', () => {
  const grouping = groupSkillTimelineItems([
    skillEvent('review-start', 'skill_execution_start', 'review', 'Review', {
      total_steps: 3,
    }),
    skillEvent('review-tool-error', 'skill_tool_result', 'review', 'Review', {
      tool_name: 'lint',
      step_index: 1,
      total_steps: 3,
      status: 'failed',
      error: 'Lint failed',
    }),
  ]);

  assert.equal(grouping.groups[0].status, 'failed');
  assert.equal(grouping.groups[0].currentStep, 1);
  assert.equal(grouping.groups[0].totalSteps, 3);
});

test('Desktop renders one structured skill execution card per lifecycle', () => {
  assert.match(chatTimelineSource, /kind: 'skill_group'/);
  assert.match(chatTimelineSource, /groupSkillTimelineItems/);
  assert.match(chatTimelineSource, /<SkillTimelineCard/);
  assert.match(skillTimelineCardSource, /className="skill-execution-card/);
  assert.match(skillTimelineCardSource, /skill-progress-bar/);
  assert.match(skillTimelineCardSource, /skill-tool-chain/);
  assert.match(skillTimelineCardSource, /skill\.toolSteps\.map/);
  assert.match(sessionSteeringQaSource, /skill-events/);
  assert.equal(
    i18nSource.split("'chat.skillExecutionTitle'").length - 1,
    2,
    'skill execution labels must cover both locales',
  );
});

function skillEvent(id, type, skillId, skillName, extra = {}) {
  return {
    id,
    type,
    eventTimeUs: 1,
    eventCounter: 1,
    payload: {
      skill_id: skillId,
      skill_name: skillName,
      ...extra,
    },
  };
}
