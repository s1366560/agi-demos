import '@radix-ui/themes/styles.css';
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';

import {
  MarkdownContent,
  NarrativeMessageFrame,
  WorkspaceTranscriptMessage,
} from '../features/chat/ChatTranscript';
import { I18nProvider } from '../i18n';
import { ToastProvider } from '../features/feedback/ToastCenter';
import type { WorkspaceMessage } from '../types';
import '../styles/global.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __messageIdentityQaRoot: Root | undefined;
}

const messages: WorkspaceMessage[] = [
  {
    id: 'qa-human',
    sender_type: 'human',
    sender_id: 'internal-user-id',
    content: '请把会话身份信息与 Web 保持一致。',
    metadata: { sender_name: 'Alice' },
    created_at: '2026-07-26T09:05:00.000Z',
  },
  {
    id: 'qa-agent',
    sender_type: 'agent',
    sender_id: 'internal-agent-id',
    content: '已使用结构化发送者名称，不会从消息正文推断身份。',
    metadata: { sender_name: 'Builder' },
    created_at: '2026-07-26T09:06:00.000Z',
  },
  {
    id: 'qa-runtime',
    sender_type: 'runtime',
    sender_id: 'internal-runtime-id',
    content: '运行时通知保持为独立角色。',
    created_at: '2026-07-26T09:07:00.000Z',
  },
  {
    id: 'qa-unknown',
    sender_type: 'internal_dispatch_worker',
    sender_id: 'must-not-render',
    content: '未知发送者类型使用安全的智能体降级标签。',
    created_at: 'malformed-time',
  },
  {
    id: 'qa-long-label',
    sender_type: 'agent',
    content: '长名称在窄屏下应截断，而不是挤压操作按钮或让消息横向溢出。',
    metadata: {
      sender_name:
        'Release verification and reliability reviewer with an intentionally long display name',
    },
    created_at: '2026-07-26T09:08:00.000Z',
  },
];

function MessageIdentityQa() {
  const narrow = new URLSearchParams(window.location.search).has('narrow');
  return (
    <main className="session-workspace-thread" style={{ minHeight: '100%' }}>
      <section
        className="pane-shell chat-shell session-chat-narrative"
        style={{ maxWidth: narrow ? 360 : 860, margin: '0 auto' }}
      >
        <div className="message-scroll">
          <div className="message-stack" data-testid="message-identity-fixture">
            {messages.map((message) => (
              <WorkspaceTranscriptMessage key={message.id} message={message} />
            ))}
            <NarrativeMessageFrame
              kind="agent"
              label="Streaming Agent"
              time="17:09"
              content="实时回复正在生成。"
              badge="工作空间智能体"
              className="timeline-item"
              timelineItemId="qa-streaming"
              streaming
            >
              <MarkdownContent content="实时回复正在生成。" className="transcript-content" />
            </NarrativeMessageFrame>
          </div>
        </div>
      </section>
    </main>
  );
}

function mount() {
  const container = document.getElementById('root');
  if (!container) return;
  if (!globalThis.__messageIdentityQaRoot) {
    globalThis.__messageIdentityQaRoot = createRoot(container);
  }
  globalThis.__messageIdentityQaRoot.render(
    <React.StrictMode>
      <I18nProvider>
        <ToastProvider>
          <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium">
            <MessageIdentityQa />
          </Theme>
        </ToastProvider>
      </I18nProvider>
    </React.StrictMode>,
  );
}

mount();
