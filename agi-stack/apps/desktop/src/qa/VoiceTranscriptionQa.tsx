import '@radix-ui/themes/styles.css';
import React, { useMemo, useState, useSyncExternalStore } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ChatBubbleIcon, CubeIcon, MixerHorizontalIcon } from '@radix-ui/react-icons';
import { Button, Theme } from '@radix-ui/themes';

import { ChatPanel } from '../features/chat/ChatPanel';
import type { ComposerCatalogClient } from '../features/chat/composerCatalogModel';
import { ToastProvider } from '../features/feedback/ToastCenter';
import type {
  VoiceAudioContext,
  VoiceMediaStream,
  VoiceSocket,
  VoiceTranscriptionRuntime,
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
import '../styles.css';
import './sessionSteeringQa.css';
import './voiceTranscriptionQa.css';

declare global {
  var __voiceTranscriptionQaRoot: Root | undefined;
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
    id: 'conversation-voice-alpha',
    project_id: 'project-voice',
    tenant_id: 'tenant-voice',
    user_id: 'user-voice',
    title: 'Voice draft alpha',
    status: 'active',
    message_count: 2,
    created_at: '2026-07-24T08:00:00Z',
    workspace_id: 'workspace-voice',
  },
  {
    id: 'conversation-voice-beta',
    project_id: 'project-voice',
    tenant_id: 'tenant-voice',
    user_id: 'user-voice',
    title: 'Voice draft beta',
    status: 'active',
    message_count: 2,
    created_at: '2026-07-24T08:05:00Z',
    workspace_id: 'workspace-voice',
  },
];

const cloudConfig: DesktopRuntimeConfig = {
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: 'qa-cloud-session',
  localApiToken: '',
  tenantId: 'tenant-voice',
  projectId: 'project-voice',
  workspaceId: 'workspace-voice',
  mode: 'cloud',
  workspaceRoot: '/qa/voice',
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
      content: 'Use voice input to prepare the next message without sending it.',
      eventCounter: 1,
    }),
    timelineItem({
      id: `${conversation.id}-agent`,
      type: 'assistant_message',
      role: 'assistant',
      content: 'The microphone result will remain in the draft until you choose to send it.',
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

class QaVoiceSocket implements VoiceSocket {
  readyState = 0;
  binaryType?: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  sent: (string | ArrayBuffer)[] = [];
  private messageHandler: ((message: { data: unknown }) => void) | null = null;
  private staleMessageHandler: ((message: { data: unknown }) => void) | null = null;

  constructor(private readonly runtime: QaVoiceRuntime) {
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

  emit(type: 'asr_interim' | 'asr_final', text: string): void {
    this.messageHandler?.({ data: JSON.stringify({ type, text }) });
  }

  emitServiceError(): void {
    this.messageHandler?.({
      data: JSON.stringify({
        type: 'error',
        message: 'Deterministic QA failure',
      }),
    });
  }

  emitStale(text: string): void {
    this.staleMessageHandler?.({
      data: JSON.stringify({ type: 'asr_final', text }),
    });
  }
}

class QaVoiceRuntime implements VoiceTranscriptionRuntime {
  readonly workletModuleUrl = '/audio-processor.js';
  readonly socketOpenState = 1;
  permissionGranted = true;
  activeSocket: QaVoiceSocket | null = null;
  lastClosedSocket: QaVoiceSocket | null = null;
  socketCloseCount = 0;
  trackStopCount = 0;
  audioCloseCount = 0;
  private revision = 0;
  private readonly listeners = new Set<() => void>();

  createSocket(): QaVoiceSocket {
    const socket = new QaVoiceSocket(this);
    this.activeSocket = socket;
    this.changed();
    return socket;
  }

  createAudioContext(): VoiceAudioContext {
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
        this.audioCloseCount += 1;
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

  socketClosed(socket: QaVoiceSocket): void {
    this.lastClosedSocket = socket;
    if (this.activeSocket === socket) this.activeSocket = null;
    this.socketCloseCount += 1;
    this.changed();
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

function VoiceTranscriptionQa() {
  const [conversationIndex, setConversationIndex] = useState(0);
  const [sentMessages, setSentMessages] = useState<string[]>([]);
  const runtime = useMemo(() => new QaVoiceRuntime(), []);
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
        <aside className="session-steering-qa-rail voice-transcription-qa-rail">
          <div className="session-steering-qa-brand">
            <CubeIcon />
            <strong>MemStack</strong>
          </div>
          <nav>
            <button type="button" className="selected">
              <ChatBubbleIcon /> Voice input
            </button>
          </nav>
          <section>
            <span>TRANSCRIPTION EVENTS</span>
            <Button
              data-testid="emit-interim"
              variant="soft"
              onClick={() => runtime.activeSocket?.emit('asr_interim', '你好，')}
            >
              Emit interim
            </Button>
            <Button
              data-testid="emit-final"
              variant="soft"
              onClick={() => runtime.activeSocket?.emit('asr_final', '你好，这是云端语音转写。')}
            >
              Emit final
            </Button>
            <Button
              data-testid="emit-error"
              variant="soft"
              color="orange"
              onClick={() => runtime.activeSocket?.emitServiceError()}
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
              onClick={() => runtime.lastClosedSocket?.emitStale('旧会话污染')}
            >
              Emit stale old result
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
          <dl className="voice-transcription-qa-diagnostics" data-testid="diagnostics">
            <div>
              <dt>Socket closes</dt>
              <dd>{runtime.socketCloseCount}</dd>
            </div>
            <div>
              <dt>Track stops</dt>
              <dd>{runtime.trackStopCount}</dd>
            </div>
            <div>
              <dt>Audio closes</dt>
              <dd>{runtime.audioCloseCount}</dd>
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
                <strong>Cloud voice transcription acceptance</strong>
                <small>Real ChatPanel · deterministic media runtime · no auto-send</small>
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
              scopeLabel="Cloud voice transcription"
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
              voiceTranscriptionRuntime={runtime}
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
const qaRoot = globalThis.__voiceTranscriptionQaRoot ?? createRoot(root);
globalThis.__voiceTranscriptionQaRoot = qaRoot;
qaRoot.render(
  <React.StrictMode>
    <I18nProvider>
      <ToastProvider>
        <VoiceTranscriptionQa />
      </ToastProvider>
    </I18nProvider>
  </React.StrictMode>,
);
