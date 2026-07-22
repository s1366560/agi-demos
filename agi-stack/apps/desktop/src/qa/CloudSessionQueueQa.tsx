import { useState } from 'react';
import { createRoot } from 'react-dom/client';

import { useAgentSocket } from '../hooks/useAgentSocket';
import { DEFAULT_CONFIG, type DesktopRuntimeConfig } from '../types';

import '../styles.css';

type SentSocketMessage = Record<string, unknown>;

class QaWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  static latest: QaWebSocket | null = null;

  readonly url: string;
  readonly protocols: string[];
  readyState = QaWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  sent: SentSocketMessage[] = [];

  constructor(url: string | URL, protocols?: string | string[]) {
    this.url = String(url);
    this.protocols = Array.isArray(protocols) ? protocols : protocols ? [protocols] : [];
    QaWebSocket.latest = this;
  }

  send(data: string) {
    if (this.readyState !== QaWebSocket.OPEN) throw new Error('Socket is not open');
    this.sent.push(JSON.parse(data) as SentSocketMessage);
    window.dispatchEvent(new Event('qa-socket-sent'));
  }

  close() {
    this.readyState = QaWebSocket.CLOSED;
  }

  open() {
    this.readyState = QaWebSocket.OPEN;
    this.onopen?.();
  }
}

window.WebSocket = QaWebSocket as unknown as typeof WebSocket;
document.documentElement.dataset.qaRuntimeErrors = '';
window.addEventListener('error', (event) => {
  document.documentElement.dataset.qaRuntimeErrors = event.message || 'window error';
});
window.addEventListener('unhandledrejection', (event) => {
  document.documentElement.dataset.qaRuntimeErrors = String(event.reason ?? 'unhandled rejection');
});

const config: DesktopRuntimeConfig = {
  ...DEFAULT_CONFIG,
  apiBaseUrl: 'https://cloud.qa.memstack.local',
  apiKey: 'qa-cloud-session',
  localApiToken: '',
  tenantId: 'tenant-cloud',
  projectId: 'project-cloud',
  workspaceId: 'workspace-cloud',
  mode: 'cloud',
  workspaceRoot: '',
};

function CloudSessionQueueQa() {
  const [, refresh] = useState(0);
  const [accepted, setAccepted] = useState(false);
  const [activeConfig, setActiveConfig] = useState(config);
  const socket = useAgentSocket(activeConfig, true, 1, 'conversation-cloud');
  const sentMessages = QaWebSocket.latest?.sent ?? [];
  const agentMessages = sentMessages.filter((message) => message.type === 'send_message');
  const latestAgentMessage = agentMessages[agentMessages.length - 1];

  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        background: '#071019',
        color: '#f5f7fa',
      }}
    >
      <section style={{ width: 560, padding: 32, border: '1px solid #33485f', borderRadius: 16 }}>
        <span>Cloud session recovery QA</span>
        <h1>Start a session while realtime is connecting</h1>
        <p>
          The first Agent turn must wait locally and flush exactly once when the live channel opens.
        </p>
        <dl>
          <div>
            <dt>Realtime</dt>
            <dd data-qa-realtime>{socket.connected ? 'connected' : 'connecting'}</dd>
          </div>
          <div>
            <dt>Session request</dt>
            <dd data-qa-session>{accepted ? 'accepted' : 'not started'}</dd>
          </div>
          <div>
            <dt>Agent turns sent</dt>
            <dd data-qa-agent-turns>{agentMessages.length}</dd>
          </div>
          <div>
            <dt>Selected Agent</dt>
            <dd data-qa-agent>{String(latestAgentMessage?.agent_id ?? 'not sent')}</dd>
          </div>
          <div>
            <dt>Forced skill</dt>
            <dd data-qa-skill>{String(latestAgentMessage?.forced_skill_name ?? 'not sent')}</dd>
          </div>
          <div>
            <dt>Composer context</dt>
            <dd data-qa-context>
              {latestAgentMessage?.app_model_context ? 'preserved' : 'not sent'}
            </dd>
          </div>
          <div>
            <dt>Sandbox attachment</dt>
            <dd data-qa-attachment>
              {Array.isArray(latestAgentMessage?.file_metadata)
                ? String(
                    (latestAgentMessage.file_metadata[0] as
                      | Record<string, unknown>
                      | undefined)?.sandbox_path ?? 'not sent',
                  )
                : 'not sent'}
            </dd>
          </div>
        </dl>
        <div style={{ display: 'flex', gap: 12 }}>
          <button
            type="button"
            onClick={() => {
              const queued = socket.sendAgentMessage({
                conversationId: 'conversation-cloud',
                projectId: 'project-cloud',
                message: 'Prepare a structured plan',
                messageId: 'message-cloud-1',
                agentId: 'definition-reviewer',
                forcedSkillName: 'source-research',
                mentions: ['agent-research'],
                fileMetadata: [
                  {
                    filename: 'evidence.txt',
                    sandbox_path: '/workspace/input/evidence.txt',
                    mime_type: 'text/plain',
                    size_bytes: 42,
                  },
                ],
                appModelContext: {
                  desktop_composer_context: {
                    resources: [{ kind: 'plugin', resource_id: 'github' }],
                  },
                },
              });
              setAccepted(queued);
              if (queued) {
                setActiveConfig((current) => ({
                  ...current,
                  workspaceId: 'workspace-created-for-session',
                }));
              }
            }}
          >
            Start cloud session
          </button>
          <button
            type="button"
            onClick={() => {
              QaWebSocket.latest?.open();
              refresh((value) => value + 1);
            }}
          >
            Connect realtime channel
          </button>
        </div>
      </section>
    </main>
  );
}

window.addEventListener('qa-socket-sent', () => {
  document.documentElement.dataset.qaSentMessages = String(QaWebSocket.latest?.sent.length ?? 0);
});

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root');
createRoot(root).render(<CloudSessionQueueQa />);
