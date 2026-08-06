import '@radix-ui/themes/styles.css';
import React, { useMemo, useState, useSyncExternalStore } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ChatBubbleIcon, CubeIcon, MixerHorizontalIcon } from '@radix-ui/react-icons';
import { Button, Theme } from '@radix-ui/themes';

import { ChatPanel } from '../features/chat/ChatPanel';
import type { ComposerCatalogClient } from '../features/chat/composerCatalogModel';
import { ToastProvider } from '../features/feedback/ToastCenter';
import type {
  VoiceCallRuntime,
  VoicePlaybackBuffer,
  VoicePlaybackContext,
  VoicePlaybackSource,
} from '../features/chat/voiceCallRuntime';
import type {
  VoiceAudioContext,
  VoiceMediaStream,
  VoiceSocket,
  VoiceWorkletNode,
} from '../features/chat/voiceTranscriptionRuntime';
import { I18nProvider } from '../i18n';
import type {
  AgentConversation,
  AgentTimelineItem,
  ComposerContextItem,
  ConversationTimelineState,
  DesktopRuntimeConfig,
} from '../types';
import '../styles/global.css';
import './sessionSteeringQa.css';
import './voiceCallQa.css';

declare global {
  var __voiceCallQaRoot: Root | undefined;
}

const qaApi: ComposerCatalogClient = {
  listWorkspaceAgents: async () => [],
  listManagedAgents: async () => [],
  listManagedSkills: async () => [],
  listManagedPlugins: async () => [],
  listManagedSubAgents: async () => [],
};

const conversations: AgentConversation[] = [
  {
    id: 'conversation-call-alpha',
    project_id: 'project-call',
    tenant_id: 'tenant-call',
    user_id: 'user-call',
    title: 'Voice call alpha',
    status: 'active',
    message_count: 2,
    created_at: '2026-07-24T09:00:00Z',
    workspace_id: 'workspace-call',
  },
  {
    id: 'conversation-call-beta',
    project_id: 'project-call',
    tenant_id: 'tenant-call',
    user_id: 'user-call',
    title: 'Voice call beta',
    status: 'active',
    message_count: 2,
    created_at: '2026-07-24T09:05:00Z',
    workspace_id: 'workspace-call',
  },
];

const cloudConfig: DesktopRuntimeConfig = {
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: 'qa-cloud-session',
  localApiToken: '',
  tenantId: 'tenant-call',
  projectId: 'project-call',
  workspaceId: 'workspace-call',
  mode: 'cloud',
  workspaceRoot: '/qa/voice-call',
};

function timelineItem(
  partial: Partial<AgentTimelineItem> & { id: string; type: string },
): AgentTimelineItem {
  return {
    eventTimeUs: Date.now() * 1_000,
    eventCounter: 0,
    timestamp: Date.now(),
    ...partial,
  };
}

function timelineState(conversation: AgentConversation): ConversationTimelineState {
  const items = [
    timelineItem({
      id: `${conversation.id}-user`,
      type: 'user_message',
      role: 'user',
      content: 'Start a voice call and ask the Agent for a concise project update.',
      eventCounter: 1,
    }),
    timelineItem({
      id: `${conversation.id}-agent`,
      type: 'assistant_message',
      role: 'assistant',
      content: 'The live transcript and synthesized reply stay visible in the call panel.',
      eventCounter: 2,
    }),
  ];
  return {
    conversationId: conversation.id,
    items,
    approvalRequests: [],
    artifactVersions: [],
    artifactDeliveries: [],
    toolInvocations: [],
    loading: false,
    loadingEarlier: false,
    error: null,
    hasMore: false,
    firstCursor: {
      timeUs: items[0].eventTimeUs,
      counter: items[0].eventCounter,
    },
    lastCursor: {
      timeUs: items[1].eventTimeUs,
      counter: items[1].eventCounter,
    },
  };
}

class QaVoiceCallSocket implements VoiceSocket {
  readyState = 0;
  binaryType?: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  sent: (string | ArrayBuffer)[] = [];
  private messageHandler: ((message: { data: unknown }) => void) | null = null;
  private staleMessageHandler: ((message: { data: unknown }) => void) | null = null;

  constructor(private readonly runtime: QaVoiceCallRuntime) {
    window.queueMicrotask(() => {
      if (this.readyState !== 0) return;
      this.readyState = 1;
      this.onopen?.();
      this.runtime.changed();
    });
  }

  get onmessage(): ((message: { data: unknown }) => void) | null {
    return this.messageHandler;
  }

  set onmessage(handler: ((message: { data: unknown }) => void) | null) {
    if (!handler && this.messageHandler) this.staleMessageHandler = this.messageHandler;
    this.messageHandler = handler;
  }

  send(data: string | ArrayBuffer): void {
    this.sent.push(data);
    this.runtime.changed();
  }

  close(): void {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.runtime.socketClosed(this);
  }

  emitText(value: Record<string, unknown>): void {
    this.messageHandler?.({ data: JSON.stringify(value) });
  }

  emitBinary(seed = 2): void {
    this.messageHandler?.({ data: Uint8Array.from([seed]).buffer });
  }

  emitStale(): void {
    this.staleMessageHandler?.({
      data: JSON.stringify({
        type: 'agent_complete',
        content: 'A stale reply must never enter the new call.',
      }),
    });
  }
}

class QaPlaybackSource implements VoicePlaybackSource {
  buffer: VoicePlaybackBuffer | null = null;
  onended: (() => void) | null = null;
  private ended = false;

  constructor(private readonly runtime: QaVoiceCallRuntime) {}

  connect(): void {}

  disconnect(): void {}

  start(): void {
    this.runtime.playbackScheduleCount += 1;
    this.runtime.activePlaybackSources.add(this);
    this.runtime.changed();
  }

  stop(): void {
    if (this.ended) return;
    this.runtime.playbackStopCount += 1;
    this.finish();
  }

  finish(): void {
    if (this.ended) return;
    this.ended = true;
    this.runtime.activePlaybackSources.delete(this);
    this.onended?.();
    this.runtime.changed();
  }
}

class QaVoiceCallRuntime implements VoiceCallRuntime {
  readonly workletModuleUrl = '/audio-processor.js';
  readonly socketOpenState = 1;
  permissionGranted = true;
  activeSocket: QaVoiceCallSocket | null = null;
  lastClosedSocket: QaVoiceCallSocket | null = null;
  socketCloseCount = 0;
  trackStopCount = 0;
  captureCloseCount = 0;
  playbackCloseCount = 0;
  playbackScheduleCount = 0;
  playbackStopCount = 0;
  readonly activePlaybackSources = new Set<QaPlaybackSource>();
  private revision = 0;
  private readonly listeners = new Set<() => void>();

  createSocket(): QaVoiceCallSocket {
    const socket = new QaVoiceCallSocket(this);
    this.activeSocket = socket;
    this.changed();
    return socket;
  }

  createCaptureContext(): VoiceAudioContext {
    let state = 'running';
    return {
      sampleRate: 48_000,
      get state() {
        return state;
      },
      audioWorklet: { addModule: async () => undefined },
      createMediaStreamSource: () => ({
        connect: () => undefined,
        disconnect: () => undefined,
      }),
      close: async () => {
        if (state === 'closed') return;
        state = 'closed';
        this.captureCloseCount += 1;
        this.changed();
      },
    };
  }

  createWorkletNode(): VoiceWorkletNode {
    return {
      port: {
        onmessage: null,
        postMessage: () => undefined,
      },
      disconnect: () => undefined,
    };
  }

  async getUserMedia(): Promise<VoiceMediaStream> {
    return {
      getTracks: () => [
        {
          stop: () => {
            this.trackStopCount += 1;
            this.changed();
          },
        },
      ],
    };
  }

  async requestMicrophoneAccess(): Promise<boolean> {
    return this.permissionGranted;
  }

  createPlaybackContext(): VoicePlaybackContext {
    let state = 'running';
    return {
      get state() {
        return state;
      },
      currentTime: 4,
      destination: {},
      resume: async () => undefined,
      decodeAudioData: async () => ({ duration: 0.2 }),
      createBufferSource: () => new QaPlaybackSource(this),
      close: async () => {
        if (state === 'closed') return;
        state = 'closed';
        this.playbackCloseCount += 1;
        this.changed();
      },
    };
  }

  socketClosed(socket: QaVoiceCallSocket): void {
    this.lastClosedSocket = socket;
    if (this.activeSocket === socket) this.activeSocket = null;
    this.socketCloseCount += 1;
    this.changed();
  }

  emitConversationTurn(): void {
    const socket = this.activeSocket;
    if (!socket) return;
    socket.emitText({ type: 'asr_interim', text: '项目现在' });
    socket.emitText({ type: 'asr_final', text: '项目现在进展如何？' });
    socket.emitText({ type: 'agent_token', content: '当前' });
    socket.emitText({ type: 'agent_token', content: '进展顺利。' });
    socket.emitText({ type: 'agent_complete', content: '当前进展顺利。' });
    socket.emitText({ type: 'tts_start' });
    socket.emitBinary();
    socket.emitText({ type: 'tts_end' });
  }

  finishPlayback(): void {
    [...this.activePlaybackSources].forEach((source) => source.finish());
  }

  changed = (): void => {
    this.revision += 1;
    this.listeners.forEach((listener) => listener());
  };

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): number => this.revision;
}

function VoiceCallQa() {
  const [conversationIndex, setConversationIndex] = useState(0);
  const [sentMessages, setSentMessages] = useState<string[]>([]);
  const runtime = useMemo(() => new QaVoiceCallRuntime(), []);
  useSyncExternalStore(runtime.subscribe, runtime.getSnapshot, runtime.getSnapshot);
  const conversation = conversations[conversationIndex];

  const sendMessage = (
    content: string,
    _contextItems: ComposerContextItem[],
    onWorkspaceMessageSaved?: () => void,
  ) => {
    setSentMessages((current) => [...current, content]);
    onWorkspaceMessageSaved?.();
  };

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="large">
      <div className="session-steering-qa-shell">
        <aside className="session-steering-qa-rail voice-call-qa-rail">
          <div className="session-steering-qa-brand">
            <CubeIcon />
            <strong>MemStack</strong>
          </div>
          <nav>
            <button type="button" className="selected">
              <ChatBubbleIcon /> Voice call
            </button>
          </nav>
          <section>
            <span>CALL EVENTS</span>
            <Button
              data-testid="emit-call-turn"
              variant="soft"
              onClick={() => runtime.emitConversationTurn()}
            >
              Emit ASR → Agent → TTS
            </Button>
            <Button
              data-testid="finish-playback"
              variant="soft"
              onClick={() => runtime.finishPlayback()}
            >
              Finish TTS playback
            </Button>
            <Button
              data-testid="emit-service-error"
              variant="soft"
              color="orange"
              onClick={() =>
                runtime.activeSocket?.emitText({
                  type: 'error',
                  message: 'Deterministic QA failure',
                })
              }
            >
              Emit service error
            </Button>
          </section>
          <section>
            <span>SCOPE & PERMISSION</span>
            <Button
              data-testid="switch-conversation"
              variant="soft"
              onClick={() =>
                setConversationIndex((current) => (current + 1) % conversations.length)
              }
            >
              Switch conversation
            </Button>
            <Button
              data-testid="emit-stale"
              variant="soft"
              onClick={() => runtime.lastClosedSocket?.emitStale()}
            >
              Emit stale old reply
            </Button>
            <Button
              data-testid="toggle-permission"
              variant="soft"
              color={runtime.permissionGranted ? 'green' : 'red'}
              onClick={() => {
                runtime.permissionGranted = !runtime.permissionGranted;
                runtime.changed();
              }}
            >
              Permission: {runtime.permissionGranted ? 'granted' : 'denied'}
            </Button>
          </section>
          <dl className="voice-call-qa-diagnostics" data-testid="diagnostics">
            <div>
              <dt>Socket closes</dt>
              <dd>{runtime.socketCloseCount}</dd>
            </div>
            <div>
              <dt>Track stops</dt>
              <dd>{runtime.trackStopCount}</dd>
            </div>
            <div>
              <dt>Capture closes</dt>
              <dd>{runtime.captureCloseCount}</dd>
            </div>
            <div>
              <dt>Playback closes</dt>
              <dd>{runtime.playbackCloseCount}</dd>
            </div>
            <div>
              <dt>TTS scheduled</dt>
              <dd>{runtime.playbackScheduleCount}</dd>
            </div>
            <div>
              <dt>TTS stopped</dt>
              <dd>{runtime.playbackStopCount}</dd>
            </div>
            <div>
              <dt>Sent messages</dt>
              <dd>{sentMessages.length}</dd>
            </div>
          </dl>
        </aside>
        <main>
          <header className="session-steering-qa-titlebar">
            <div>
              <MixerHorizontalIcon />
              <span>
                <strong>Cloud audio call acceptance</strong>
                <small>Real ChatPanel · deterministic duplex media · scoped cleanup</small>
              </span>
            </div>
            <dl>
              <div>
                <dt>Conversation</dt>
                <dd data-testid="active-conversation">{conversation.title}</dd>
              </div>
            </dl>
          </header>
          <div className="session-steering-qa-content compose-ahead-qa-content">
            <ChatPanel
              api={qaApi}
              conversations={conversations}
              selectedConversationId={conversation.id}
              messages={[]}
              timelineState={timelineState(conversation)}
              agentTaskSignals={[]}
              workflowCounts={{ plan: 'ready' }}
              sessionTitle={conversation.title}
              scopeLabel="Cloud audio call"
              composerVariant="session"
              composerResetKey={conversation.id}
              activityPresence="recorded"
              activityStructuredEvidence={null}
              sending={false}
              disabledReason={null}
              activeWorkflowTarget="plan"
              modelLabel="gpt-5.5"
              selectedModelValue="gpt-5.5"
              runtimeTargetLabel="MemStack Cloud"
              runtimeTargetOptions={['MemStack Cloud']}
              runInputDelivery={null}
              runInputDeliveryOptions={[]}
              runInputs={[]}
              runInputsLoading={false}
              runInputsError={null}
              promotingRunInputId={null}
              runInputAuthorityRunId={null}
              references={[]}
              voiceTranscriptionConfig={cloudConfig}
              voiceCallRuntime={runtime}
              onRunInputDeliveryChange={() => undefined}
              onPromoteRunInput={() => undefined}
              onRemoveReference={() => undefined}
              onSend={sendMessage}
              onRefresh={() => undefined}
              onLoadEarlier={() => undefined}
              onRespondToHitl={async () => undefined}
              respondableHitlRequestIds={[]}
              onWorkflowSelect={() => undefined}
              onRuntimeTargetChange={() => undefined}
              onOpenCommands={() => undefined}
            />
          </div>
        </main>
      </div>
    </Theme>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root container');
const qaRoot = globalThis.__voiceCallQaRoot ?? createRoot(root);
globalThis.__voiceCallQaRoot = qaRoot;
qaRoot.render(
  <React.StrictMode>
    <I18nProvider>
      <ToastProvider>
        <VoiceCallQa />
      </ToastProvider>
    </I18nProvider>
  </React.StrictMode>,
);
