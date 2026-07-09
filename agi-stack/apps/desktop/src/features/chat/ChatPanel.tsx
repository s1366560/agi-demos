import { useCallback, useEffect, useMemo, useRef } from 'react';
import type { ReactNode } from 'react';
import { Badge, Button, Flex, Heading, ScrollArea, Text, TextArea } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ArchiveIcon,
  ArrowUpIcon,
  CodeIcon,
  DotsHorizontalIcon,
  ReaderIcon,
  ReloadIcon,
  RocketIcon,
} from '@radix-ui/react-icons';

import type { WorkspaceMessage } from '../../types';
import { ComposerControls } from './ComposerControls';

type ChatPanelProps = {
  messages: WorkspaceMessage[];
  agentTaskSignals: AgentTaskSignal[];
  input: string;
  sending: boolean;
  disabledReason: string | null;
  activeWorkflowTarget: ChatWorkflowTarget;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onRefresh: () => void;
  onWorkflowSelect: (target: ChatWorkflowTarget) => void;
  onOpenUsagePlan: () => void;
};

export type ChatWorkflowTarget = 'changes' | 'pull' | 'plan' | 'background' | 'artifacts';
export type AgentTaskSignalStatus = 'saving' | 'queued' | 'acknowledged' | 'failed';

export type AgentTaskSignal = {
  id: string;
  content: string;
  status: AgentTaskSignalStatus;
  detail: string;
  createdAt: string;
  conversationId?: string;
  messageId?: string;
  eventType?: string;
};

export function ChatPanel({
  messages,
  agentTaskSignals,
  input,
  sending,
  disabledReason,
  activeWorkflowTarget,
  onInputChange,
  onSend,
  onRefresh,
  onWorkflowSelect,
  onOpenUsagePlan,
}: ChatPanelProps) {
  const disabled = Boolean(disabledReason);
  const canSend = !disabled && !sending && Boolean(input.trim());
  const scrollAnchorRef = useRef<HTMLDivElement>(null);
  const signalStateKey = useMemo(
    () => agentTaskSignals.map((signal) => `${signal.id}:${signal.status}`).join('|'),
    [agentTaskSignals],
  );
  const scrollToLatest = useCallback(() => {
    scrollAnchorRef.current?.scrollIntoView({ block: 'end' });
  }, []);

  useEffect(() => {
    scrollToLatest();
  }, [messages.length, scrollToLatest, signalStateKey]);

  useEffect(() => {
    const handleResize = () => {
      window.requestAnimationFrame(scrollToLatest);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [scrollToLatest]);

  const handleSend = useCallback(() => {
    if (!canSend) return;
    onSend();
  }, [canSend, onSend]);

  return (
    <section className="pane-shell chat-shell">
      <header className="pane-head">
        <div>
          <Heading as="h2" size="3">
            Chat
          </Heading>
          <Text size="1" color="gray">
            Workspace conversation
          </Text>
        </div>
        <Button
          size="2"
          variant="surface"
          aria-label="Refresh workspace messages"
          onClick={onRefresh}
          disabled={disabled}
        >
          <ReloadIcon /> Refresh
        </Button>
      </header>
      <ScrollArea className="message-scroll">
        <div className="message-stack">
          {messages.length === 0 ? (
            <div className="chat-empty-state" role="status" aria-label="Ready for a new task" />
          ) : (
            messages.map((message) => (
              <article className={`message ${messageKind(message)}`} key={message.id}>
                <Flex align="center" justify="between" gap="2" mb="2">
                  <Flex align="center" gap="2">
                    <Text size="2" weight="bold">
                      {messageSenderLabel(message)}
                    </Text>
                    {message.mentions?.length ? (
                      <Badge color="cyan" variant="soft">
                        {message.mentions.length} mentions
                      </Badge>
                    ) : null}
                  </Flex>
                  <Text size="1" color="gray">
                    {formatTime(message.created_at)}
                  </Text>
                </Flex>
                <Text as="p" size="2" color="gray">
                  {message.content}
                </Text>
              </article>
            ))
          )}
          {agentTaskSignals.length ? (
            <div className="agent-run-stack" aria-label="Agent task status">
              {agentTaskSignals.map((signal) => (
                <article className={`message agent-run ${signal.status}`} key={signal.id}>
                  <Flex align="center" justify="between" gap="2" mb="2">
                    <Flex align="center" gap="2" className="agent-run-title">
                      <RocketIcon />
                      <Text size="2" weight="bold">
                        Agent task
                      </Text>
                      <Badge color={agentSignalColor(signal.status)} variant="soft">
                        {agentSignalLabel(signal.status)}
                      </Badge>
                    </Flex>
                    <Text size="1" color="gray">
                      {formatTime(signal.createdAt)}
                    </Text>
                  </Flex>
                  <Text as="p" size="2" className="agent-run-content">
                    {signal.content}
                  </Text>
                  <div className="agent-run-meta">
                    <span>{signal.detail}</span>
                    {signal.conversationId ? (
                      <span title={signal.conversationId}>
                        Conversation {shortId(signal.conversationId)}
                      </span>
                    ) : null}
                    {signal.eventType ? <span>{signal.eventType}</span> : null}
                  </div>
                </article>
              ))}
            </div>
          ) : null}
          <div ref={scrollAnchorRef} aria-hidden="true" />
        </div>
      </ScrollArea>
      <form
        className="composer chat-composer"
        onSubmit={(event) => {
          event.preventDefault();
          handleSend();
        }}
      >
        <ChatWorkflowStrip activeTarget={activeWorkflowTarget} onSelect={onWorkflowSelect} />
        <TextArea
          className="chat-composer-input"
          value={input}
          disabled={disabled}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder={
            disabledReason ??
            'Describe a task to run autonomously. Type / for commands, @ for files, or # for issues...'
          }
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              handleSend();
            }
          }}
        />
        <Flex align="center" justify="between" className="chat-composer-footer">
          <ComposerControls disabledHint={disabledReason} modelLabel="Claude Fable 5 · 1M" />
          <Flex align="center" gap="2" className="composer-right-actions">
            <button
              className={`composer-status-button composer-status-dot ${
                disabledReason ? 'is-blocked' : 'is-connected'
              }`}
              type="button"
              aria-label={disabledReason ?? 'AI credits quota: 100% used'}
              aria-haspopup="dialog"
              title={disabledReason ?? 'AI credits quota: 100% used'}
              onClick={onOpenUsagePlan}
            />
            <Button
              size="2"
              color="green"
              className="send-pill"
              type="submit"
              aria-label="Send workspace message"
              loading={sending}
              disabled={!canSend}
            >
              <ArrowUpIcon />
            </Button>
          </Flex>
        </Flex>
      </form>
    </section>
  );
}

function ChatWorkflowStrip({
  activeTarget,
  onSelect,
}: {
  activeTarget: ChatWorkflowTarget;
  onSelect: (target: ChatWorkflowTarget) => void;
}) {
  const items: Array<[ChatWorkflowTarget, string, string, ReactNode]> = [
    ['changes', 'Changes', '+0 -0', <CodeIcon key="changes" />],
    ['pull', 'PR', 'idle', <ReaderIcon key="pull" />],
    ['plan', 'Plan', 'active', <ActivityLogIcon key="plan" />],
    ['background', 'Background', '0', <DotsHorizontalIcon key="background" />],
    ['artifacts', 'Artifacts', '0', <ArchiveIcon key="artifacts" />],
  ];

  return (
    <div className="composer-workflows chat-composer-workflows" aria-label="chat workflow shortcuts">
      {items.map(([target, label, value, icon]) => (
        <button
          className={activeTarget === target ? 'selected' : ''}
          type="button"
          aria-label={`${label} ${value}`}
          key={target}
          onClick={() => onSelect(target)}
        >
          <span>{icon}</span>
          <strong>{label}</strong>
          <em>{value}</em>
        </button>
      ))}
    </div>
  );
}

function messageSenderLabel(message: WorkspaceMessage): string {
  const sender = (message.sender_type ?? '').toLowerCase();
  if (sender === 'human' || sender === 'user') return 'You';
  if (sender === 'runtime' || sender === 'system') return 'System';
  return message.sender_type ?? 'Agent';
}

function messageKind(message: WorkspaceMessage): 'user' | 'agent' | 'runtime' {
  const sender = (message.sender_type ?? '').toLowerCase();
  if (sender === 'human' || sender === 'user') return 'user';
  if (sender === 'runtime' || sender === 'system') return 'runtime';
  return 'agent';
}

function agentSignalLabel(status: AgentTaskSignalStatus): string {
  if (status === 'saving') return 'Saving';
  if (status === 'queued') return 'Sent';
  if (status === 'acknowledged') return 'Accepted';
  return 'Needs attention';
}

function agentSignalColor(status: AgentTaskSignalStatus): 'gray' | 'cyan' | 'green' | 'red' {
  if (status === 'saving') return 'gray';
  if (status === 'queued') return 'cyan';
  if (status === 'acknowledged') return 'green';
  return 'red';
}

function shortId(value: string): string {
  return value.length > 8 ? value.slice(0, 8) : value;
}

function formatTime(value: string | undefined): string {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
