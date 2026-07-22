import '@radix-ui/themes/styles.css';
import React, { useEffect, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';

import { AgentTimeline } from '../features/chat/ChatTimeline';
import { I18nProvider } from '../i18n';
import type { AgentTimelineItem, ConversationTimelineState } from '../types';
import '../styles.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __sessionConversationQaRoot: Root | undefined;
}

// Visual QA fixture for the agent conversation timeline: day dividers, a
// reasoning row, paired tool calls (complete / running / failed), SubAgent and
// graph lifecycle rows, markdown with a highlighted code block, a streaming
// assistant reply, and the live working indicator. Item timestamps are
// relative to load time so the day dividers are deterministic ("yesterday"
// then "today").

const nowMs = Date.now();
const HOUR = 3_600_000;

function item(partial: Partial<AgentTimelineItem> & { id: string; type: string }): AgentTimelineItem {
  return {
    eventTimeUs: nowMs * 1000,
    eventCounter: 0,
    timestamp: nowMs,
    ...partial,
  } as AgentTimelineItem;
}

const longTestReport = JSON.stringify(
  {
    suite: 'pipeline_race_regression',
    status: 'failed',
    duration_ms: 12_431,
    totals: { tests: 18, passed: 17, failed: 1, skipped: 0 },
    failures: [
      {
        name: 'race_regression::concurrent_fixture_disposal',
        message: 'fixture disposed while job 42 was still running',
        location: 'tests/race_regression.rs:87',
      },
    ],
    environment: {
      os: 'macos',
      arch: 'aarch64',
      rust: '1.81.0',
      workers: 8,
      seed: 918_273,
    },
  },
  null,
  2,
);

const conversationItems: AgentTimelineItem[] = [
  item({
    id: 'user-1',
    type: 'user_message',
    role: 'user',
    content:
      'Please reproduce the flaky pipeline test, isolate the race without changing the public API, and leave verification evidence in this session.',
    eventTimeUs: (nowMs - 26 * HOUR) * 1000,
    eventCounter: 1,
    timestamp: nowMs - 26 * HOUR,
  }),
  item({
    id: 'thought-1',
    type: 'thought',
    content:
      'The runner shares a module-level fixture across jobs. I will inspect `src/pipeline/runner.py` first, then reproduce the race in an isolated worktree before touching the public API.',
    eventTimeUs: (nowMs - 25.8 * HOUR) * 1000,
    eventCounter: 2,
    timestamp: nowMs - 25.8 * HOUR,
  }),
  item({
    id: 'act-1',
    type: 'act',
    toolName: 'read_file',
    toolInput: { path: 'src/pipeline/runner.py', offset: 0, limit: 120 },
    display: { kind: 'read' },
    eventTimeUs: (nowMs - 25.7 * HOUR) * 1000,
    eventCounter: 3,
    timestamp: nowMs - 25.7 * HOUR,
  }),
  item({
    id: 'observe-1',
    type: 'observe',
    toolName: 'read_file',
    toolOutput:
      'async def run_job(job: PipelineJob) -> Result:\n    # shared across jobs — race source\n    async with shared_fixture() as runner:\n        await runner.execute(job)\n        return runner.result',
    display: { kind: 'read' },
    eventTimeUs: (nowMs - 25.7 * HOUR + 420) * 1000,
    eventCounter: 4,
    timestamp: nowMs - 25.7 * HOUR + 420,
  }),
  item({
    id: 'act-2',
    type: 'act',
    toolName: 'run_tests',
    toolInput: { command: 'pytest tests/pipeline -k race --count 50' },
    display: { kind: 'check' },
    eventTimeUs: (nowMs - 25.6 * HOUR) * 1000,
    eventCounter: 5,
    timestamp: nowMs - 25.6 * HOUR,
  }),
  item({
    id: 'observe-2',
    type: 'observe',
    toolName: 'run_tests',
    toolOutput: longTestReport,
    display: { kind: 'check' },
    eventTimeUs: (nowMs - 25.6 * HOUR + 12_431) * 1000,
    eventCounter: 6,
    timestamp: nowMs - 25.6 * HOUR + 12_431,
  }),
  item({
    id: 'act-edit-1',
    type: 'act',
    toolName: 'apply_patch',
    toolInput: { path: 'src/pipeline/runner.py' },
    display: { kind: 'edit', title: 'runner.py', summary: 'Scope fixture to job ID' },
    eventTimeUs: (nowMs - 25.5 * HOUR) * 1000,
    eventCounter: 7,
    timestamp: nowMs - 25.5 * HOUR,
  }),
  item({
    id: 'observe-edit-1',
    type: 'observe',
    toolName: 'apply_patch',
    toolOutput: { files_changed: 2, additions: 28, deletions: 9 },
    display: { kind: 'edit', title: 'runner.py', summary: 'Fixture scoped to job ID' },
    fileMetadata: { diffStat: { filesChanged: 2, additions: 28, deletions: 9 } },
    eventTimeUs: (nowMs - 25.5 * HOUR + 680) * 1000,
    eventCounter: 8,
    timestamp: nowMs - 25.5 * HOUR + 680,
  }),
  item({
    id: 'agent-1',
    type: 'assistant_message',
    role: 'assistant',
    content:
      '已定位竞态：共享可变状态让上一个任务的 runner 保持存活。修复方案：\n\n- 将 fixture 作用域收窄到 `job_id`\n- 增加并发回归覆盖\n\n```ts\nexport async function withIsolatedFixture<T>(\n  jobId: string,\n  run: (fixture: Fixture) => Promise<T>,\n): Promise<T> {\n  const fixture = await createFixture({ scope: jobId });\n  try {\n    return await run(fixture);\n  } finally {\n    await fixture.dispose();\n  }\n}\n```\n\n验证证据已同步到右侧变更面板。',
    metadata: {
      executionSummary: {
        step_count: 6,
        artifact_count: 2,
        call_count: 4,
        total_cost: 0.01842,
        total_cost_formatted: '$0.018420',
        total_tokens: { total: 12480 },
        tasks: { total: 3, completed: 3, remaining: 0 },
      },
    },
    eventTimeUs: (nowMs - 25.4 * HOUR) * 1000,
    eventCounter: 9,
    timestamp: nowMs - 25.4 * HOUR,
  }),
  item({
    id: 'user-2',
    type: 'user_message',
    role: 'user',
    content: '很好 — 把竞态回归也加到 CI。',
    eventTimeUs: (nowMs - 2 * HOUR) * 1000,
    eventCounter: 10,
    timestamp: nowMs - 2 * HOUR,
  }),
  item({
    id: 'subagent-started-1',
    type: 'subagent_started',
    payload: {
      subagent_name: 'Regression reviewer',
      task: 'Verify the concurrent disposal fix',
    },
    eventTimeUs: (nowMs - 1.99 * HOUR) * 1000,
    eventCounter: 11,
    timestamp: nowMs - 1.99 * HOUR,
  }),
  item({
    id: 'graph-run-started-1',
    type: 'graph_run_started',
    payload: { graph_name: 'Release validation', pattern: 'supervisor' },
    eventTimeUs: (nowMs - 1.98 * HOUR) * 1000,
    eventCounter: 12,
    timestamp: nowMs - 1.98 * HOUR,
  }),
  item({
    id: 'graph-handoff-1',
    type: 'graph_handoff',
    payload: {
      from_label: 'Planner',
      to_label: 'Reviewer',
      context_summary: 'Patch ready for verification',
    },
    eventTimeUs: (nowMs - 1.97 * HOUR) * 1000,
    eventCounter: 13,
    timestamp: nowMs - 1.97 * HOUR,
  }),
  item({
    id: 'graph-node-failed-1',
    type: 'graph_node_failed',
    payload: {
      node_label: 'Run regression tests',
      error_message: '1 test failed after 12.4s',
    },
    eventTimeUs: (nowMs - 1.96 * HOUR) * 1000,
    eventCounter: 14,
    timestamp: nowMs - 1.96 * HOUR,
  }),
  item({
    id: 'subagent-completed-1',
    type: 'subagent_completed',
    payload: {
      subagent_name: 'Patch reviewer',
      summary: 'Public API remains unchanged',
      success: true,
    },
    eventTimeUs: (nowMs - 1.95 * HOUR) * 1000,
    eventCounter: 15,
    timestamp: nowMs - 1.95 * HOUR,
  }),
  item({
    id: 'act-3',
    type: 'act',
    toolName: 'shell_command',
    toolInput: { command: 'cargo test -p pipeline --test race_regression' },
    display: { kind: 'command' },
    eventTimeUs: (nowMs - 1.9 * HOUR) * 1000,
    eventCounter: 11,
    timestamp: nowMs - 1.9 * HOUR,
  }),
  item({
    id: 'observe-3',
    type: 'observe',
    toolName: 'shell_command',
    isError: true,
    display: { kind: 'command' },
    toolOutput:
      'error[E0432]: unresolved import `pipeline::shared_fixture`\n  --> tests/race_regression.rs:3:5\n\nnote: the fixture module was made private by the scoping fix',
    eventTimeUs: (nowMs - 1.9 * HOUR + 3_800) * 1000,
    eventCounter: 12,
    timestamp: nowMs - 1.9 * HOUR + 3_800,
  }),
  item({
    id: 'stream-1',
    type: 'assistant_message',
    role: 'assistant',
    message_id: 'msg-stream-1',
    content: '已修复导入并重新运行回归，目前 **17 项测试**通过，还有 1 项在重试验证。正在整理最终报告…',
    metadata: { streaming: true },
    eventTimeUs: (nowMs - 40_000) * 1000,
    eventCounter: 13,
    timestamp: nowMs - 40_000,
  }),
];

const workingIndicatorItems: AgentTimelineItem[] = [
  item({
    id: 'w-user-1',
    type: 'user_message',
    role: 'user',
    content: '把竞态回归加入 CI 之后，顺手更新流水线徽章状态。',
    eventTimeUs: (nowMs - 30_000) * 1000,
    eventCounter: 1,
    timestamp: nowMs - 30_000,
  }),
  item({
    id: 'w-act-1',
    type: 'act',
    toolName: 'read_file',
    toolInput: { path: '.github/workflows/pipeline.yml' },
    display: { kind: 'read' },
    eventTimeUs: (nowMs - 20_000) * 1000,
    eventCounter: 2,
    timestamp: nowMs - 20_000,
  }),
  item({
    id: 'w-observe-1',
    type: 'observe',
    toolName: 'read_file',
    toolOutput: 'name: pipeline\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest',
    display: { kind: 'read' },
    eventTimeUs: (nowMs - 19_000) * 1000,
    eventCounter: 3,
    timestamp: nowMs - 19_000,
  }),
];

function timelineState(items: AgentTimelineItem[]): ConversationTimelineState {
  return {
    conversationId: 'conversation-qa',
    items,
    approvalRequests: [],
    artifactVersions: [],
    artifactDeliveries: [],
    toolInvocations: [],
    loading: false,
    loadingEarlier: false,
    error: null,
    hasMore: false,
    firstCursor: null,
    lastCursor: null,
  };
}

function TimelineFixture({
  state,
  presence,
}: {
  state: ConversationTimelineState;
  presence: 'live' | 'recorded';
}) {
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});
  return (
    <AgentTimeline
      state={state}
      expandedItems={expandedItems}
      onToggleItem={(toggleItem) =>
        setExpandedItems((current) => ({
          ...current,
          [toggleItem.id]: !current[toggleItem.id],
        }))
      }
      onLoadEarlier={() => {}}
      onShowEarlier={() => {}}
      earlierRenderAllowance={0}
      onRetry={() => {}}
      onRespondToHitl={() => Promise.resolve()}
      respondableHitlRequestIds={[]}
      activityPresence={presence}
    />
  );
}

function SessionConversationQa() {
  useEffect(() => {
    // Open the interactive layers (groups, pairs, reasoning) so the capture
    // shows the expanded states without a scripted browser session.
    const timer = window.setTimeout(() => {
      document
        .querySelectorAll<HTMLElement>('.timeline-tool-group > summary')
        .forEach((element) => element.click());
      document
        .querySelectorAll<HTMLElement>('.tool-call .timeline-row-toggle')
        .forEach((element) => element.click());
      document
        .querySelectorAll<HTMLElement>('.message.timeline-row.thought .timeline-row-toggle')
        .forEach((element) => element.click());
    }, 350);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="session-workspace-thread" style={{ minHeight: '100%' }}>
      <section
        className="pane-shell chat-shell session-chat-narrative"
        style={{ maxWidth: 860, margin: '0 auto' }}
      >
        <div className="message-scroll">
          <div className="message-stack">
            <TimelineFixture state={timelineState(conversationItems)} presence="live" />
            <div style={{ height: 48 }} aria-hidden="true" />
            <TimelineFixture state={timelineState(workingIndicatorItems)} presence="live" />
          </div>
        </div>
      </section>
    </div>
  );
}

function mount() {
  const container = document.getElementById('root');
  if (!container) return;
  if (!globalThis.__sessionConversationQaRoot) {
    globalThis.__sessionConversationQaRoot = createRoot(container);
  }
  globalThis.__sessionConversationQaRoot.render(
    <React.StrictMode>
      <I18nProvider>
        <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium">
          <SessionConversationQa />
        </Theme>
      </I18nProvider>
    </React.StrictMode>,
  );
}

mount();
