import '@radix-ui/themes/styles.css';
import React, { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';
import {
  ChatBubbleIcon,
  CodeIcon,
  CubeIcon,
  GearIcon,
  GridIcon,
  HomeIcon,
  PlusIcon,
} from '@radix-ui/react-icons';

import { ChatPanel } from '../features/chat/ChatPanel';
import type { ComposerCatalogClient } from '../features/chat/ComposerPlusMenu';
import { SessionChangesCanvas } from '../features/session/SessionChangesCanvas';
import { toggleRunInputReference } from '../features/session/sessionChangesModel';
import { I18nProvider } from '../i18n';
import type {
  ChangeSnapshot,
  CodeRangeReference,
  ConversationTimelineState,
  DesktopRunInput,
  RunInputDelivery,
  WorkspaceMessage,
} from '../types';
import '../styles.css';
import './sessionSteeringQa.css';

declare global {
  var __sessionSteeringQaRoot: Root | undefined;
}

const qaApi: ComposerCatalogClient = {
  listWorkspaceAgents: async () => [],
  listManagedAgents: async () => [],
  listManagedSkills: async () => [],
  listManagedPlugins: async () => [],
  uploadSandboxFile: async (file) => {
    await new Promise((resolve) => window.setTimeout(resolve, 180));
    return {
      filename: file.name,
      sandbox_path: `/workspace/input/${file.name}`,
      mime_type: file.type || 'application/octet-stream',
      size_bytes: file.size,
    };
  },
};

const snapshot: ChangeSnapshot = {
  id: 'change-snapshot-72e3a5b9',
  run_id: 'run-desktop-session-42',
  conversation_id: 'conversation-desktop-session',
  run_revision: 7,
  environment_id: 'environment-worktree-42',
  repository_root: '/workspace/memstack',
  workspace_path: '/workspace/.agistack-worktrees/desktop-session-42',
  branch: 'agistack/desktop-session-42',
  base_revision: '8f19c6e',
  head_revision: '8f19c6e',
  status: 'ready',
  additions: 8,
  deletions: 3,
  files_changed: 2,
  truncated: false,
  captured_at: '2026-07-13T12:30:00Z',
  files: [
    {
      path: 'src/session/steering.ts',
      status: 'modified',
      additions: 6,
      deletions: 3,
      binary: false,
      untracked: false,
      patch_digest: '0ac29be318f42861',
      hunks: [
        {
          header: '@@ -41,7 +41,10 @@ export function deliverInput',
          old_start: 41,
          new_start: 41,
          lines: [
            { kind: 'context', old_line: 41, new_line: 41, text: '  const run = authority.run;' },
            { kind: 'deletion', old_line: 42, new_line: null, text: '  return send(message);' },
            { kind: 'addition', old_line: null, new_line: 42, text: '  const input = bindToRevision(message, run.revision);' },
            { kind: 'addition', old_line: null, new_line: 43, text: '  await ledger.persist(input);' },
            { kind: 'addition', old_line: null, new_line: 44, text: '  return run.control.deliver(input);' },
            { kind: 'context', old_line: 43, new_line: 45, text: '}' },
          ],
        },
      ],
    },
    {
      path: 'src/session/changes.ts',
      status: 'added',
      additions: 2,
      deletions: 0,
      binary: false,
      untracked: true,
      patch_digest: 'af62d78a822cf890',
      hunks: [
        {
          header: '@@ -0,0 +1,2 @@',
          old_start: 0,
          new_start: 1,
          lines: [
            { kind: 'addition', old_line: null, new_line: 1, text: "export const scope = 'run';" },
            { kind: 'addition', old_line: null, new_line: 2, text: 'export const revision = 7;' },
          ],
        },
      ],
    },
  ],
};

const queuedInput: DesktopRunInput = {
  id: 'run-input-next-1',
  conversation_id: 'conversation-desktop-session',
  run_id: 'run-desktop-session-42',
  expected_run_revision: 7,
  message_id: 'message-next-1',
  idempotency_key: 'queue-next-1',
  delivery: 'queue_next',
  status: 'ready',
  sequence: 1,
  queue_position: 1,
  content: 'Run the compatibility matrix and prepare a migration plan.',
  references: [],
  created_at: '2026-07-13T10:10:00Z',
  updated_at: '2026-07-13T10:18:00Z',
};

const qaModelOptions = [
  { value: 'gpt-5.5', modelId: 'gpt-5.5', providerLabel: 'OpenAI production' },
  { value: 'gpt-5.5-mini', modelId: 'gpt-5.5-mini', providerLabel: 'OpenAI production' },
  { value: 'glm-5.2', modelId: 'glm-5.2', providerLabel: 'OpenAI-compatible' },
];

const messages: WorkspaceMessage[] = [
  {
    id: 'message-1',
    sender_type: 'user',
    content: 'Implement the authoritative steering path and keep revision conflicts explicit.',
    created_at: '2026-07-13T12:20:00Z',
  },
  {
    id: 'message-2',
    sender_type: 'agent',
    content: 'The run is active in an isolated worktree. I am applying the reviewed plan.',
    created_at: '2026-07-13T12:21:00Z',
  },
];

const timelineState: ConversationTimelineState = {
  conversationId: 'conversation-desktop-session',
  items: [
    {
      id: 'message-user-goal',
      type: 'user_message',
      eventTimeUs: 1_784_282_041_000_000,
      eventCounter: 1,
      role: 'user',
      content:
        'Please reproduce the flaky pipeline test, isolate the race, and leave verification evidence.',
    },
    {
      id: 'message-agent-result',
      type: 'assistant_message',
      eventTimeUs: 1_784_282_042_000_000,
      eventCounter: 2,
      role: 'assistant',
      content:
        'I scoped fixture ownership to the job ID and added concurrent regression coverage.',
    },
    {
      id: 'verification-progress',
      type: 'task_updated',
      eventTimeUs: 1_784_282_043_000_000,
      eventCounter: 3,
      content: '18 tests passed · 50 race runs passed · static checks',
      display: {
        title: 'Verifying the isolated fix',
        summary: '18 tests passed · 50 race runs passed · static checks',
        checkpoint: 'Patch applied',
        evidence: '18 tests · 50 race runs',
      },
    },
  ],
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

const earlierTimelineItem: ConversationTimelineState['items'][number] = {
  id: 'message-earlier-context',
  type: 'assistant_message',
  eventTimeUs: 1_784_282_022_000_000,
  eventCounter: 0,
  role: 'assistant',
  content: 'I am checking the pipeline fixture ownership before reproducing the race.',
};

const anchorTimelineItems: ConversationTimelineState['items'] = [
  ...Array.from({ length: 18 }, (_, index) => ({
    id: `message-recorded-checkpoint-${index + 1}`,
    type: 'assistant_message',
    eventTimeUs: 1_784_282_023_000_000 + index * 1_000_000,
    eventCounter: index,
    role: 'assistant',
    content: `Recorded checkpoint ${index + 1}: pipeline ownership remained isolated.`,
  })),
  ...timelineState.items,
];

const concurrentTailItem: ConversationTimelineState['items'][number] = {
  id: 'message-concurrent-live-tail',
  type: 'assistant_message',
  eventTimeUs: 1_784_282_044_000_000,
  eventCounter: 4,
  role: 'assistant',
  content: 'A concurrent live update arrived while earlier history was loading.',
};

const suggestionTimelineItem: ConversationTimelineState['items'][number] = {
  id: 'agent-follow-up-suggestions',
  type: 'suggestions',
  eventTimeUs: 1_784_282_045_000_000,
  eventCounter: 5,
  payload: {
    suggestions: [
      'Open the verification report',
      'Run the compatibility matrix',
      'Prepare the migration checklist',
    ],
  },
};

const runtimeInfrastructureTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'sandbox-runtime-created',
    type: 'sandbox_created',
    eventTimeUs: 1_784_282_045_000_000,
    eventCounter: 5,
    payload: {
      sandbox_id: 'sandbox-release-1',
      status: 'running',
      endpoint: 'wss://sandbox.example/ws',
    },
  },
  {
    id: 'sandbox-desktop-started',
    type: 'desktop_started',
    eventTimeUs: 1_784_282_046_000_000,
    eventCounter: 6,
    payload: {
      sandbox_id: 'sandbox-release-1',
      resolution: '1280x720',
      display: ':1',
    },
  },
  {
    id: 'sandbox-terminal-started',
    type: 'terminal_started',
    eventTimeUs: 1_784_282_047_000_000,
    eventCounter: 7,
    payload: {
      sandbox_id: 'sandbox-release-1',
      session_id: 'terminal-release-1',
      url: 'wss://sandbox.example/terminal',
    },
  },
  {
    id: 'sandbox-terminal-stopped',
    type: 'terminal_status',
    eventTimeUs: 1_784_282_048_000_000,
    eventCounter: 8,
    payload: {
      sandbox_id: 'sandbox-release-1',
      session_id: 'terminal-release-1',
      running: false,
    },
  },
  {
    id: 'sandbox-runtime-error',
    type: 'sandbox_status',
    eventTimeUs: 1_784_282_049_000_000,
    eventCounter: 9,
    payload: {
      sandbox_id: 'sandbox-release-1',
      status: 'error',
      error_message: 'Runtime health probe failed',
    },
  },
];

const httpServiceTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'http-service-preview-started',
    type: 'http_service_started',
    eventTimeUs: 1_784_282_050_000_000,
    eventCounter: 10,
    payload: {
      sandbox_id: 'sandbox-release-1',
      service_id: 'service-preview-1',
      service_name: 'Vite preview',
      source_type: 'sandbox_internal',
      service_url: 'http://172.17.0.2:5173',
      proxy_url: '/api/v1/projects/project-1/sandbox/http-services/service-preview-1/proxy/',
      auto_open: true,
    },
  },
  {
    id: 'http-service-preview-updated',
    type: 'http_service_updated',
    eventTimeUs: 1_784_282_051_000_000,
    eventCounter: 11,
    payload: {
      sandbox_id: 'sandbox-release-1',
      service_id: 'service-preview-1',
      service_name: 'Vite preview',
      source_type: 'sandbox_internal',
      service_url: 'http://172.17.0.2:4173',
      proxy_url: '/api/v1/projects/project-1/sandbox/http-services/service-preview-1/proxy/',
      status: 'running',
    },
  },
  {
    id: 'http-service-preview-stopped',
    type: 'http_service_stopped',
    eventTimeUs: 1_784_282_052_000_000,
    eventCounter: 12,
    payload: {
      sandbox_id: 'sandbox-release-1',
      service_id: 'service-preview-1',
      service_name: 'Vite preview',
      status: 'stopped',
    },
  },
  {
    id: 'http-service-preview-error',
    type: 'http_service_error',
    eventTimeUs: 1_784_282_053_000_000,
    eventCounter: 13,
    payload: {
      sandbox_id: 'sandbox-release-1',
      service_id: 'service-preview-1',
      service_name: 'Vite preview',
      status: 'error',
      error_message: 'Preview port is not reachable',
    },
  },
];

const doomLoopTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'doom-loop-detected-terminal',
    type: 'doom_loop_detected',
    eventTimeUs: 1_784_282_054_000_000,
    eventCounter: 14,
    payload: {
      request_id: 'request-doom-loop-1',
      tool_name: 'terminal',
      call_count: 4,
      last_calls: [],
    },
  },
  {
    id: 'doom-loop-intervened-terminal',
    type: 'doom_loop_intervened',
    eventTimeUs: 1_784_282_055_000_000,
    eventCounter: 15,
    payload: {
      request_id: 'request-doom-loop-1',
      action: 'resume_with_guardrails',
    },
  },
];

const conversationTerminalTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'agent-goal-completed-release',
    type: 'agent_goal_completed',
    eventTimeUs: 1_784_282_056_000_000,
    eventCounter: 16,
    payload: {
      conversation_id: 'conversation-release-1',
      actor_agent_id: 'coordinator',
      summary: 'Release verification completed with all requested checks passing',
      artifacts: ['release-report', 'verification-log'],
    },
  },
  {
    id: 'agent-conversation-finished-budget',
    type: 'agent_conversation_finished',
    eventTimeUs: 1_784_282_057_000_000,
    eventCounter: 17,
    payload: {
      conversation_id: 'conversation-budget-1',
      reason: 'budget_turns',
      actor: 'system',
      rationale: 'Turn budget reached before the remaining optional checks',
    },
  },
  {
    id: 'agent-conversation-finished-safety',
    type: 'agent_conversation_finished',
    eventTimeUs: 1_784_282_058_000_000,
    eventCounter: 18,
    payload: {
      conversation_id: 'conversation-safety-1',
      reason: 'safety_doom_loop',
      actor: 'supervisor',
      rationale: 'Repeated terminal calls remained unsafe after intervention',
    },
  },
];

function SessionSteeringQa() {
  const searchParams = new URLSearchParams(window.location.search);
  const historyMode = searchParams.get('history');
  const suggestionsMode = searchParams.get('suggestions') === '1';
  const runtimeEventsMode = searchParams.get('runtime-events') === '1';
  const httpServiceEventsMode = searchParams.get('http-service-events') === '1';
  const doomLoopEventsMode = searchParams.get('doom-loop-events') === '1';
  const terminalEventsMode = searchParams.get('terminal-events') === '1';
  const [delivery, setDelivery] = useState<RunInputDelivery>('steer_now');
  const [references, setReferences] = useState<CodeRangeReference[]>([]);
  const [runInputs, setRunInputs] = useState<DesktopRunInput[]>([queuedInput]);
  const [model, setModel] = useState('gpt-5.5');
  const [switchingModel, setSwitchingModel] = useState(false);
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const [timeline, setTimeline] = useState<ConversationTimelineState>(() => {
    const items =
      historyMode === 'anchor'
        ? anchorTimelineItems
        : suggestionsMode
          ? [...timelineState.items, suggestionTimelineItem]
          : runtimeEventsMode
            ? [...timelineState.items, ...runtimeInfrastructureTimelineItems]
            : httpServiceEventsMode
              ? [...timelineState.items, ...httpServiceTimelineItems]
              : doomLoopEventsMode
                ? [...timelineState.items, ...doomLoopTimelineItems]
                : terminalEventsMode
                  ? [...timelineState.items, ...conversationTerminalTimelineItems]
                  : timelineState.items;
    return {
      ...timelineState,
      items,
      hasMore:
        historyMode === 'pagination' || historyMode === 'error' || historyMode === 'anchor',
      firstCursor: {
        timeUs: items[0]?.eventTimeUs ?? 0,
        counter: items[0]?.eventCounter ?? 0,
      },
      lastCursor: {
        timeUs: items[items.length - 1]?.eventTimeUs ?? 0,
        counter: items[items.length - 1]?.eventCounter ?? 0,
      },
    };
  });

  const loadEarlierHistory = () => {
    setTimeline((current) => ({ ...current, loadingEarlier: true, error: null }));
    if (historyMode === 'anchor') {
      window.setTimeout(() => {
        setTimeline((current) => ({
          ...current,
          items: current.items.some((item) => item.id === concurrentTailItem.id)
            ? current.items
            : [...current.items, concurrentTailItem],
        }));
      }, 1000);
    }
    window.setTimeout(() => {
      if (historyMode === 'error' && historyAttempt === 0) {
        setHistoryAttempt(1);
        setTimeline((current) => ({
          ...current,
          loadingEarlier: false,
          error: 'Earlier history could not be loaded. Retry without losing this page.',
          hasMore: false,
        }));
        return;
      }
      setTimeline((current) => ({
        ...current,
        items: current.items.some((item) => item.id === earlierTimelineItem.id)
          ? current.items
          : [earlierTimelineItem, ...current.items],
        loadingEarlier: false,
        error: null,
        hasMore: false,
        firstCursor: {
          timeUs: earlierTimelineItem.eventTimeUs ?? 0,
          counter: earlierTimelineItem.eventCounter ?? 0,
        },
      }));
    }, historyMode === 'anchor' ? 2000 : 180);
  };

  const sendQaMessage = (content: string) => {
    if (!suggestionsMode) return;
    setTimeline((current) => {
      const eventTimeUs = (current.items[current.items.length - 1]?.eventTimeUs ?? 0) + 1_000_000;
      const eventCounter = (current.items[current.items.length - 1]?.eventCounter ?? 0) + 1;
      const nextItem: ConversationTimelineState['items'][number] = {
        id: `suggestion-user-message-${eventCounter}`,
        type: 'user_message',
        eventTimeUs,
        eventCounter,
        role: 'user',
        content,
      };
      return {
        ...current,
        items: [...current.items, nextItem],
        lastCursor: { timeUs: eventTimeUs, counter: eventCounter },
      };
    });
  };

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="session-steering-qa-shell">
        <aside className="session-steering-qa-rail">
          <div className="session-steering-qa-brand"><CubeIcon /><strong>MemStack</strong></div>
          <button type="button"><PlusIcon /> New task</button>
          <nav>
            <button type="button"><HomeIcon /> Home</button>
            <button type="button"><GridIcon /> My work</button>
          </nav>
          <section>
            <span>WORKSPACE</span>
            <button type="button"><CubeIcon /> Desktop Client</button>
            <button type="button" className="selected"><ChatBubbleIcon /> Session interaction redesign</button>
          </section>
          <button type="button"><GearIcon /> Settings</button>
        </aside>
        <main>
          <header className="session-steering-qa-titlebar">
            <div><CodeIcon /><span><strong>Session interaction redesign</strong><small>Code · Build · Running</small></span></div>
            <dl>
              <div><dt>Environment</dt><dd>Worktree</dd></div>
              <div><dt>Branch</dt><dd>agistack/desktop-session-42</dd></div>
              <div><dt>Run</dt><dd>run-desk · r7</dd></div>
            </dl>
          </header>
          <div className="session-steering-qa-content">
            <ChatPanel
              api={qaApi}
              conversations={[]}
              messages={messages}
              timelineState={timeline}
              agentTaskSignals={[]}
              workflowCounts={{ changes: 2, plan: 'ready' }}
              sessionTitle="Conversation"
              scopeLabel="Current run narrative"
              composerVariant="session"
              composerResetKey="qa-session-steering"
              initialInput={
                suggestionsMode ? '' : 'Keep the public API stable and add the missing revision test.'
              }
              activityPresence={
                suggestionsMode ||
                runtimeEventsMode ||
                httpServiceEventsMode ||
                doomLoopEventsMode
                  ? 'recorded'
                  : 'live'
              }
              activityStructuredEvidence={null}
              sending={false}
              disabledReason={null}
              activeWorkflowTarget="changes"
              modelLabel={model}
              modelOptions={qaModelOptions}
              selectedModelValue={model}
              modelSwitching={switchingModel}
              runtimeTargetLabel="Local Rust Core"
              runtimeTargetOptions={['Local Rust Core']}
              runInputDelivery={delivery}
              runInputDeliveryOptions={['steer_now', 'queue_next']}
              runInputs={runInputs}
              runInputsLoading={false}
              runInputsError={null}
              promotingRunInputId={null}
              runInputAuthorityRunId="run-desktop-session-42"
              respondableHitlRequestIds={[]}
              references={references}
              onRunInputDeliveryChange={setDelivery}
              onPromoteRunInput={(input) =>
                setRunInputs((current) =>
                  current.map((candidate) =>
                    candidate.id === input.id
                      ? { ...candidate, status: 'promoted_to_plan' }
                      : candidate,
                  ),
                )
              }
              onRemoveReference={(reference) =>
                setReferences((current) => toggleRunInputReference(current, reference))
              }
              onSend={sendQaMessage}
              onRefresh={() => undefined}
              onLoadEarlier={loadEarlierHistory}
              onRespondToHitl={async () => undefined}
              onWorkflowSelect={() => undefined}
              onModelChange={async (value) => {
                setSwitchingModel(true);
                await new Promise((resolve) => window.setTimeout(resolve, 180));
                setModel(value);
                setSwitchingModel(false);
              }}
              onRuntimeTargetChange={() => undefined}
              onOpenCommands={() => undefined}
            />
            <SessionChangesCanvas
              snapshot={snapshot}
              loading={false}
              error={null}
              references={references}
              onRefresh={() => undefined}
              onToggleReference={(reference) =>
                setReferences((current) => toggleRunInputReference(current, reference))
              }
            />
          </div>
        </main>
      </div>
    </Theme>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root container');
const qaRoot = globalThis.__sessionSteeringQaRoot ?? createRoot(root);
globalThis.__sessionSteeringQaRoot = qaRoot;
qaRoot.render(
  <React.StrictMode>
    <I18nProvider>
      <SessionSteeringQa />
    </I18nProvider>
  </React.StrictMode>,
);
