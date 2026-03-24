import type React from 'react';

import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MessageArea } from '@/components/agent/MessageArea';
import { AgentSwitcher } from '@/components/agent/AgentSwitcher';
import { InputToolbar } from '@/components/agent/InputToolbar';
import { useAgentV3Store } from '@/stores/agentV3';
import { useAgentDefinitionStore } from '@/stores/agentDefinitions';
import { createDefaultConversationState } from '@/types/conversationState';

import type { TimelineEvent } from '@/types/agent';

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 80,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        start: index * 80,
        size: 80,
        key: index,
      })),
    measureElement: vi.fn(),
    scrollToIndex: vi.fn(),
    measure: vi.fn(),
  }),
}));

vi.mock('@/components/agent/MessageBubble', () => ({
  MessageBubble: ({ event }: { event: { content?: string } }) => (
    <div data-testid="message-bubble">{event.content || 'message'}</div>
  ),
}));

vi.mock('@/components/agent/timeline/ExecutionTimeline', () => ({
  ExecutionTimeline: () => <div data-testid="execution-timeline" />,
}));

vi.mock('@/components/agent/timeline/SubAgentTimeline', () => ({
  SubAgentTimeline: () => <div data-testid="subagent-timeline" />,
}));

vi.mock('@/components/agent/timeline/SubAgentCostSummary', () => ({
  SubAgentCostSummary: () => <div data-testid="subagent-cost-summary" />,
}));

vi.mock('@/components/agent/chat/ThinkingBlock', () => ({
  ThinkingBlock: ({ content }: { content: string }) => (
    <div data-testid="thinking-block">{content}</div>
  ),
}));

vi.mock('@/components/agent/message/ConversationSummaryCardWrapper', () => ({
  ConversationSummaryCardWrapper: () => null,
}));

vi.mock('@/components/agent/message/StreamingToolPreparation', () => ({
  StreamingToolPreparation: () => <div data-testid="streaming-tool-prep" />,
}));

vi.mock('@/components/agent/chat/SuggestionChips', () => ({
  SuggestionChips: () => <div data-testid="suggestion-chips" />,
}));

vi.mock('@/components/agent/chat/LlmOverridePopover', () => ({
  LlmOverridePopover: () => <div data-testid="llm-override-popover" />,
}));

vi.mock('@/components/agent/chat/ModelSwitchPopover', () => ({
  ModelSwitchPopover: () => <div data-testid="model-switch-popover" />,
}));

vi.mock('@/components/agent/chat/VoiceWaveform', () => ({
  VoiceWaveform: () => null,
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyButton: ({
    children,
    onClick,
    disabled,
    icon,
    className,
    ...rest
  }: {
    children?: React.ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    icon?: React.ReactNode;
    className?: string;
  }) => (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={className}
      {...rest}
    >
      {icon}
      {children}
    </button>
  ),
  LazyTooltip: ({
    children,
  }: {
    title?: React.ReactNode;
    children: React.ReactNode;
  }) => <>{children}</>,
}));

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>();
  return {
    ...actual,
    Popover: ({ children, content, open }: { children: React.ReactNode; content: React.ReactNode; open?: boolean }) => (
      <div>
        {children}
        {open ? <div data-testid="popover-content">{content}</div> : null}
      </div>
    ),
  };
});

describe('Agent Workspace hardening', () => {
  beforeEach(() => {
    const convState = createDefaultConversationState();
    convState.isStreaming = false;
    convState.streamingAssistantContent = '';
    convState.streamingThought = '';
    convState.isThinkingStreaming = false;

    useAgentV3Store.setState((state) => ({
      ...state,
      activeConversationId: 'conv-1',
      timeline: [],
      isStreaming: false,
      streamingAssistantContent: '',
      streamingThought: '',
      isThinkingStreaming: false,
      conversationStates: new Map([['conv-1', convState]]),
    }));

    useAgentDefinitionStore.setState((state) => ({
      ...state,
      definitions: [
        {
          id: 'agent-1',
          name: 'primary-agent',
          display_name: 'Primary Agent',
          enabled: true,
          source: 'database',
          project_id: null,
        } as any,
      ],
      isLoading: false,
      error: null,
    }));
  });

  it('hides ThinkingBlock when assistant text is streaming', () => {
    const timeline: TimelineEvent[] = [
      {
        id: 'evt-msg-1',
        type: 'assistant_message',
        content: 'existing',
        timestamp: Date.now(),
      } as any,
    ];

    useAgentV3Store.setState((state) => ({
      ...state,
      isStreaming: true,
      streamingThought: 'thinking...',
      isThinkingStreaming: false,
      streamingAssistantContent: 'final answer chunk',
      conversationStates: new Map(
        Array.from(state.conversationStates.entries()).map(([id, cs]) =>
          id === 'conv-1'
            ? [
                id,
                {
                  ...cs,
                  isStreaming: true,
                  streamingThought: 'thinking...',
                  isThinkingStreaming: false,
                  streamingAssistantContent: 'final answer chunk',
                },
              ]
            : [id, cs]
        )
      ),
    }));

    render(
      <MessageArea
        timeline={timeline}
        isStreaming
        isLoading={false}
      />
    );

    expect(screen.queryByTestId('thinking-block')).not.toBeInTheDocument();
  });

  it('hides ThinkingBlock when text exists even if thinking flag is stale', () => {
    const timeline: TimelineEvent[] = [
      {
        id: 'evt-msg-1b',
        type: 'assistant_message',
        content: 'existing',
        timestamp: Date.now(),
      } as any,
    ];

    useAgentV3Store.setState((state) => ({
      ...state,
      isStreaming: true,
      streamingThought: 'stale thought',
      isThinkingStreaming: true,
      streamingAssistantContent: 'new token',
      conversationStates: new Map(
        Array.from(state.conversationStates.entries()).map(([id, cs]) =>
          id === 'conv-1'
            ? [
                id,
                {
                  ...cs,
                  isStreaming: true,
                  streamingThought: 'stale thought',
                  isThinkingStreaming: true,
                  streamingAssistantContent: 'new token',
                },
              ]
            : [id, cs]
        )
      ),
    }));

    render(
      <MessageArea
        timeline={timeline}
        isStreaming
        isLoading={false}
      />
    );

    expect(screen.queryByTestId('thinking-block')).not.toBeInTheDocument();
  });

  it('keeps full thought text visible when thinking stops but stream still active', () => {
    const timeline: TimelineEvent[] = [
      {
        id: 'evt-msg-thought-persist',
        type: 'assistant_message',
        content: 'existing',
        timestamp: Date.now(),
      } as any,
    ];

    useAgentV3Store.setState((state) => ({
      ...state,
      isStreaming: true,
      streamingThought: '完整思考内容 full thought content',
      isThinkingStreaming: false,
      streamingAssistantContent: '',
      conversationStates: new Map(
        Array.from(state.conversationStates.entries()).map(([id, cs]) =>
          id === 'conv-1'
            ? [
                id,
                {
                  ...cs,
                  isStreaming: true,
                  streamingThought: '完整思考内容 full thought content',
                  isThinkingStreaming: false,
                  streamingAssistantContent: '',
                },
              ]
            : [id, cs]
        )
      ),
    }));

    render(
      <MessageArea
        timeline={timeline}
        isStreaming
        isLoading={false}
      />
    );

    expect(screen.getByTestId('thinking-block')).toHaveTextContent('完整思考内容 full thought content');
  });

  it('renders ThinkingBlock while thought is streaming without assistant text', () => {
    const timeline: TimelineEvent[] = [
      {
        id: 'evt-msg-2',
        type: 'assistant_message',
        content: 'existing',
        timestamp: Date.now(),
      } as any,
    ];

    useAgentV3Store.setState((state) => ({
      ...state,
      isStreaming: true,
      streamingThought: 'thinking...',
      isThinkingStreaming: true,
      streamingAssistantContent: '',
      conversationStates: new Map(
        Array.from(state.conversationStates.entries()).map(([id, cs]) =>
          id === 'conv-1'
            ? [
                id,
                {
                  ...cs,
                  isStreaming: true,
                  streamingThought: 'thinking...',
                  isThinkingStreaming: true,
                  streamingAssistantContent: '',
                },
              ]
            : [id, cs]
        )
      ),
    }));

    render(
      <MessageArea
        timeline={timeline}
        isStreaming
        isLoading={false}
      />
    );

    expect(screen.getByTestId('thinking-block')).toBeInTheDocument();
  });

  it('sets subagent timeline anchor data attributes', () => {
    const timeline: TimelineEvent[] = [
      {
        id: 'evt-1',
        type: 'subagent_started',
        subagentId: 'subagent-1',
        subagentName: 'Alpha',
        task: 'do work',
        timestamp: Date.now(),
      } as any,
    ];

    render(
      <MessageArea
        timeline={timeline}
        isStreaming={false}
        isLoading={false}
      />
    );

    const anchor = document.querySelector('[data-subagent-start-index="0"]');
    expect(anchor).toBeTruthy();
    expect((anchor as HTMLElement).getAttribute('data-timeline-index')).toBe('0');
  });

  it('puts AgentSwitcher as first control in InputToolbar', () => {
    const noop = () => {};
    const fileInputRef = { current: null } as React.RefObject<HTMLInputElement | null>;

    render(
      <InputToolbar
        fileInputRef={fileInputRef}
        attachments={[]}
        capabilities={{ supportsAttachment: true } as any}
        templateLibraryVisible={false}
        setTemplateLibraryVisible={vi.fn()}
        isListening={false}
        toggleVoiceInput={async () => {}}
        voiceCallStatus="idle"
        handleVoiceCall={noop}
        activeConversationId="conv-1"
        projectId="project-1"
        isStreaming={false}
        disabled={false}
        onTogglePlanMode={noop}
        isPlanMode={false}
        onAgentSelect={vi.fn()}
        activeAgentId="agent-1"
        charCount={0}
        canSend={false}
        handleSend={noop}
        onAbort={noop}
      />
    );

    expect(screen.getByRole('button', { name: /Primary Agent/i })).toBeInTheDocument();
  });

  it('prevents opening AgentSwitcher when disabled', () => {
    const onSelect = vi.fn();
    render(<AgentSwitcher activeAgentId="agent-1" onSelect={onSelect} disabled />);

    const trigger = screen.getByRole('button');
    expect(trigger).toBeDisabled();
    fireEvent.click(trigger);
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('opens AgentSwitcher as upward overlay from toolbar trigger', () => {
    render(<AgentSwitcher activeAgentId="agent-1" onSelect={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: /Primary Agent/i }));

    const listbox = screen.getByRole('listbox');
    expect(listbox).toBeInTheDocument();
    const overlay = listbox.parentElement as HTMLElement;
    expect(overlay.className).toContain('bottom-full');
    expect(overlay.className).toContain('mb-2');
  });

  it('supports keyboard selection in AgentSwitcher like slash/@ popovers', () => {
    useAgentDefinitionStore.setState((state) => ({
      ...state,
      definitions: [
        {
          id: 'agent-1',
          name: 'primary-agent',
          display_name: 'Primary Agent',
          enabled: true,
          source: 'database',
          project_id: null,
        } as any,
        {
          id: 'agent-2',
          name: 'secondary-agent',
          display_name: 'Secondary Agent',
          enabled: true,
          source: 'system',
          project_id: null,
        } as any,
      ],
    }));

    const onSelect = vi.fn();
    render(<AgentSwitcher activeAgentId="agent-1" onSelect={onSelect} />);

    const trigger = screen.getByRole('button', { name: /Primary Agent/i });
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    fireEvent.keyDown(trigger, { key: 'Enter' });

    expect(onSelect).toHaveBeenCalledWith('agent-2');
  });

  it('uses toolbar-consistent compact switcher button styling', () => {
    render(<AgentSwitcher activeAgentId="agent-1" onSelect={vi.fn()} />);

    const trigger = screen.getByRole('button', { name: /Primary Agent/i });
    expect(trigger.className).toContain('h-8');
    expect(trigger.className).toContain('rounded-lg');
    expect(trigger.className).toContain('hover:bg-slate-100');
    expect(trigger.className).toContain('dark:hover:bg-slate-700/50');
  });
});
