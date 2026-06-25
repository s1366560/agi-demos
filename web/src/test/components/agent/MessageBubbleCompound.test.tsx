/**
 * Tests for MessageBubble Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('react-i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-i18next')>();
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, defaultValue?: string, options?: Record<string, unknown>) => {
        if (typeof defaultValue === 'string') {
          return defaultValue.replace('{{count}}', String(options?.count ?? ''));
        }
        return key;
      },
      i18n: { language: 'en' },
    }),
  };
});

// Mock heavy dependencies
vi.mock('react-markdown', () => ({
  default: ({ children }: any) => <div data-testid="markdown">{children}</div>,
}));

vi.mock('remark-gfm', () => ({
  default: () => ({}),
}));

vi.mock('react-syntax-highlighter', () => ({
  default: ({ children }: any) => <div data-testid="syntax-highlighter">{children}</div>,
  Prism: ({ children }: any) => <div data-testid="syntax-highlighter">{children}</div>,
}));

vi.mock('react-syntax-highlighter/dist/esm/styles/prism', () => ({
  vscDarkPlus: {},
}));

vi.mock('react-syntax-highlighter/dist/esm/styles/hljs', () => ({
  vs2015: {},
}));

// Mock lazy antd components
vi.mock('@/components/ui/lazyAntd', () => ({
  LazyAvatar: ({ children, className }: any) => (
    <div data-testid="avatar" className={className}>
      {children}
    </div>
  ),
  LazyTag: ({ children, className }: any) => (
    <span data-testid="tag" className={className}>
      {children}
    </span>
  ),
  LazyTooltip: ({ children }: any) => <>{children}</>,
}));

// Import from the MessageBubble.tsx file directly
import { MessageBubble } from '../../../components/agent/MessageBubble';

// Mock timeline events
const mockUserEvent: any = {
  id: '1',
  type: 'user_message',
  content: 'Hello, how are you?',
  timestamp: Date.now(),
};

const mockAssistantEvent: any = {
  id: '2',
  type: 'assistant_message',
  content: 'I am doing well, thank you!',
  timestamp: Date.now(),
};

const mockAssistantSummaryEvent: any = {
  id: '2-summary',
  type: 'assistant_message',
  content: 'I am doing well, thank you!',
  timestamp: Date.now(),
  metadata: {
    executionSummary: {
      stepCount: 4,
      artifactCount: 2,
      callCount: 1,
      totalCost: 0.123456,
      totalCostFormatted: '$0.123456',
      totalTokens: {
        input: 10,
        output: 5,
        reasoning: 2,
        cacheRead: 0,
        cacheWrite: 0,
        total: 17,
      },
      tasks: {
        total: 3,
        completed: 2,
        remaining: 1,
        pending: 1,
        inProgress: 0,
        failed: 0,
        cancelled: 0,
        other: 0,
      },
    },
  },
};

const mockAssistantEmptySummaryEvent: any = {
  id: '2-empty-summary',
  type: 'assistant_message',
  content: 'External ACP response',
  timestamp: Date.now(),
  metadata: {
    executionSummary: {
      source: 'acp_external',
      acp_agent_key: 'opencode-local',
    },
  },
};

const mockTextDeltaEvent: any = {
  id: '3',
  type: 'text_delta',
  content: 'Streaming...',
  timestamp: Date.now(),
};

const mockTextEndEvent: any = {
  id: '4',
  type: 'text_end',
  fullText: 'Complete response here',
  timestamp: Date.now(),
};

const mockTextEndSummaryEvent: any = {
  id: '4-summary',
  type: 'text_end',
  fullText: 'Complete response here',
  timestamp: Date.now(),
  metadata: {
    executionSummary: {
      stepCount: 2,
      artifactCount: 1,
      callCount: 1,
      totalCost: 0.123456,
      totalCostFormatted: '$0.123456',
      totalTokens: {
        input: 10,
        output: 5,
        reasoning: 2,
        cacheRead: 0,
        cacheWrite: 0,
        total: 17,
      },
      tasks: {
        total: 2,
        completed: 2,
        remaining: 0,
        pending: 0,
        inProgress: 0,
        failed: 0,
        cancelled: 0,
        other: 0,
      },
    },
  },
};

const mockTextEndArtifactEvent: any = {
  id: '4-artifacts',
  type: 'text_end',
  fullText: 'Complete response here',
  timestamp: Date.now(),
  artifacts: [
    {
      url: 'https://example.com/artifacts/report.pdf',
      object_key: 'artifacts/report.pdf',
      mime_type: 'application/pdf',
      size_bytes: 2048,
    },
  ],
};

const mockUnsafeTextEndArtifactEvent: any = {
  id: '4-unsafe-artifacts',
  type: 'text_end',
  fullText: 'Complete response here',
  timestamp: Date.now(),
  artifacts: [
    {
      url: 'javascript:alert(1)',
      object_key: 'artifacts/report.pdf',
      mime_type: 'application/pdf',
      size_bytes: 2048,
    },
  ],
};

const mockUnsafeArtifactOnlyTextEndEvent: any = {
  id: '4-unsafe-artifact-only',
  type: 'text_end',
  timestamp: Date.now(),
  artifacts: [
    {
      url: 'javascript:alert(1)',
      object_key: 'artifacts/report.pdf',
      mime_type: 'application/pdf',
      size_bytes: 2048,
    },
  ],
};

const mockThoughtEvent: any = {
  id: '5',
  type: 'thought',
  content: 'Thinking about the response',
  timestamp: Date.now(),
};

const mockActEvent: any = {
  id: '6',
  type: 'act',
  toolName: 'search',
  toolInput: { query: 'test' },
  execution_id: 'exec-1',
  timestamp: Date.now(),
};

const mockObserveEvent: any = {
  id: '7',
  type: 'observe',
  toolName: 'search',
  toolOutput: { results: ['result1', 'result2'] },
  execution_id: 'exec-1',
  isError: false,
  timestamp: Date.now() + 100,
};

const mockWorkPlanEvent: any = {
  id: '8',
  type: 'work_plan',
  steps: [{ description: 'Step 1' }, { description: 'Step 2' }],
  timestamp: Date.now(),
};

const mockArtifactEvent: any = {
  id: '10',
  type: 'artifact_created',
  filename: 'test.png',
  category: 'image',
  mimeType: 'image/png',
  sizeBytes: 1024,
  url: 'https://example.com/test.png',
  timestamp: Date.now(),
};

describe('MessageBubble Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Root Component', () => {
    it('should render user message event', () => {
      render(<MessageBubble event={mockUserEvent} />);

      expect(screen.getByText('Hello, how are you?')).toBeInTheDocument();
    });

    it('should render assistant message event', () => {
      render(<MessageBubble event={mockAssistantEvent} />);

      expect(screen.getByTestId('markdown')).toBeInTheDocument();
      expect(screen.getByText('I am doing well, thank you!')).toBeInTheDocument();
    });

    it('should render assistant execution summary metadata', () => {
      render(<MessageBubble event={mockAssistantSummaryEvent} />);

      expect(screen.getByText('Steps')).toBeInTheDocument();
      expect(screen.getByText('Artifacts')).toBeInTheDocument();
      expect(screen.getByText('Tasks')).toBeInTheDocument();
      expect(screen.getByText('2/3')).toBeInTheDocument();
      expect(screen.getByText('$0.123456')).toBeInTheDocument();
    });

    it('should hide empty assistant execution summary metadata', () => {
      render(<MessageBubble event={mockAssistantEmptySummaryEvent} />);

      expect(screen.getByText('External ACP response')).toBeInTheDocument();
      expect(screen.queryByText('Steps')).not.toBeInTheDocument();
      expect(screen.queryByText('0')).not.toBeInTheDocument();
    });

    it('should render text delta event', () => {
      render(<MessageBubble event={mockTextDeltaEvent} />);

      expect(screen.getByTestId('markdown')).toBeInTheDocument();
      expect(screen.getByText('Streaming...')).toBeInTheDocument();
    });

    it('should render text end event', () => {
      render(<MessageBubble event={mockTextEndEvent} />);

      expect(screen.getByTestId('markdown')).toBeInTheDocument();
      expect(screen.getByText('Complete response here')).toBeInTheDocument();
    });

    it('should render text end execution summary metadata', () => {
      render(<MessageBubble event={mockTextEndSummaryEvent} />);

      expect(screen.getByText('Steps')).toBeInTheDocument();
      expect(screen.getByText('Artifacts')).toBeInTheDocument();
      expect(screen.getByText('$0.123456')).toBeInTheDocument();
    });

    it('should render text end completion artifacts', () => {
      render(<MessageBubble event={mockTextEndArtifactEvent} />);

      expect(screen.getByText('report.pdf')).toBeInTheDocument();
      expect(screen.getByText(/2\.0 KB/)).toBeInTheDocument();
    });

    it('should block unsafe text end artifact urls', () => {
      render(<MessageBubble event={mockUnsafeTextEndArtifactEvent} />);

      expect(screen.queryByRole('link', { name: /report\.pdf/i })).not.toBeInTheDocument();
      expect(screen.getByText('Complete response here')).toBeInTheDocument();
    });

    it('should not render an artifact-only text end bubble when all artifact urls are unsafe', () => {
      const { container } = render(<MessageBubble event={mockUnsafeArtifactOnlyTextEndEvent} />);

      expect(container.firstChild).toBe(null);
    });

    it('should render thought event', () => {
      render(<MessageBubble event={mockThoughtEvent} />);

      expect(screen.getByText('Reasoning')).toBeInTheDocument();
      expect(screen.getByText('Thinking about the response')).toBeInTheDocument();
    });

    it('should render act (tool execution) event', () => {
      const allEvents = [mockActEvent, mockObserveEvent];
      render(<MessageBubble event={mockActEvent} allEvents={allEvents} />);

      expect(screen.getByText('search')).toBeInTheDocument();
      expect(screen.getByText('Success')).toBeInTheDocument();
    });

    it('should return null for observe event (rendered with act)', () => {
      const { container } = render(<MessageBubble event={mockObserveEvent} />);

      expect(container.firstChild).toBe(null);
    });

    it('should render work plan event', () => {
      render(<MessageBubble event={mockWorkPlanEvent} />);

      expect(screen.getByText('Work Plan')).toBeInTheDocument();
      expect(screen.getByText('Step 1')).toBeInTheDocument();
      expect(screen.getByText('Step 2')).toBeInTheDocument();
    });

    it('should render artifact created event', () => {
      render(<MessageBubble event={mockArtifactEvent} />);

      expect(screen.getByText('test.png')).toBeInTheDocument();
      expect(screen.getByText(/1\.0 KB/)).toBeInTheDocument();
    });

    it('should return null for control events', () => {
      const { container } = render(
        <MessageBubble event={{ type: 'text_start' as any, id: '11', timestamp: Date.now() }} />
      );

      expect(container.firstChild).toBe(null);
    });

    it('should return null for unknown event types', () => {
      const { container } = render(
        <MessageBubble event={{ type: 'unknown_type' as any, id: '12', timestamp: Date.now() }} />
      );

      expect(container.firstChild).toBe(null);
    });
  });

  describe('User Message Sub-Component', () => {
    it('should render User sub-component', () => {
      render(<MessageBubble.User content="Test user message" />);

      expect(screen.getByText('Test user message')).toBeInTheDocument();
    });

    it('should return null for empty content', () => {
      const { container } = render(<MessageBubble.User content="" />);

      expect(container.firstChild).toBe(null);
    });
  });

  describe('Assistant Message Sub-Component', () => {
    it('should render Assistant sub-component', () => {
      render(<MessageBubble.Assistant content="Test assistant message" />);

      expect(screen.getByText('Test assistant message')).toBeInTheDocument();
    });

    it('should linkify sandbox file paths in assistant content', () => {
      render(
        <MessageBubble.Assistant content="报告已导出: output/补充工具深度测试报告_20260529.md (9.4KB)" />
      );

      const markdown = screen.getByTestId('markdown');
      expect(markdown.textContent).toContain(
        '[output/补充工具深度测试报告_20260529.md](#sandbox-file:'
      );
    });

    it('should not rewrite sandbox paths inside existing markdown links', () => {
      const content =
        '| 项目 | 路径 |\n| 完整测试报告 | [/workspace/output/agent_test/agent_test_report.md](/workspace/output/agent_test/agent_test_report.md) |';

      render(<MessageBubble.Assistant content={content} />);

      const markdown = screen.getByTestId('markdown');
      expect(markdown.textContent).toContain(
        '[/workspace/output/agent_test/agent_test_report.md](/workspace/output/agent_test/agent_test_report.md)'
      );
      expect(markdown.textContent).not.toContain(']([/workspace/output');
    });

    it('should linkify sandbox paths in compact markdown table cells', () => {
      render(<MessageBubble.Assistant content="| 路径 |\n|/workspace/output/report.md|" />);

      const markdown = screen.getByTestId('markdown');
      expect(markdown.textContent).toContain(
        '|[/workspace/output/report.md](#sandbox-file:%2Fworkspace%2Foutput%2Freport.md)|'
      );
    });

    it('should return null for empty content when not streaming', () => {
      const { container } = render(<MessageBubble.Assistant content="" />);

      expect(container.firstChild).toBe(null);
    });
  });

  describe('Text Delta Sub-Component', () => {
    it('should render TextDelta sub-component', () => {
      render(<MessageBubble.TextDelta content="Streaming content" />);

      expect(screen.getByText('Streaming content')).toBeInTheDocument();
    });

    it('should return null for empty content', () => {
      const { container } = render(<MessageBubble.TextDelta content="" />);

      expect(container.firstChild).toBe(null);
    });
  });

  describe('Thought Sub-Component', () => {
    it('should render Thought sub-component', () => {
      render(<MessageBubble.Thought content="Thinking..." />);

      expect(screen.getByText('Thinking...')).toBeInTheDocument();
    });

    it('should return null for empty content', () => {
      const { container } = render(<MessageBubble.Thought content="" />);

      expect(container.firstChild).toBe(null);
    });
  });

  describe('Tool Execution Sub-Component', () => {
    it('should render ToolExecution sub-component', () => {
      render(<MessageBubble.ToolExecution event={mockActEvent} observeEvent={mockObserveEvent} />);

      expect(screen.getByText('search')).toBeInTheDocument();
    });

    it('should display error status when observe has error', () => {
      const errorObserve = { ...mockObserveEvent, isError: true };
      render(<MessageBubble.ToolExecution event={mockActEvent} observeEvent={errorObserve} />);

      expect(screen.getByText('Failed')).toBeInTheDocument();
    });
  });

  describe('Work Plan Sub-Component', () => {
    it('should render WorkPlan sub-component', () => {
      render(<MessageBubble.WorkPlan event={mockWorkPlanEvent} />);

      expect(screen.getByText('Work Plan')).toBeInTheDocument();
      expect(screen.getByText('Step 1')).toBeInTheDocument();
    });

    it('should return null for empty steps', () => {
      const emptyEvent = { ...mockWorkPlanEvent, steps: [] };
      const { container } = render(<MessageBubble.WorkPlan event={emptyEvent} />);

      expect(container.firstChild).toBe(null);
    });
  });

  describe('Text End Sub-Component', () => {
    it('should render TextEnd sub-component', () => {
      render(<MessageBubble.TextEnd event={mockTextEndEvent} />);

      expect(screen.getByText('Complete response here')).toBeInTheDocument();
    });

    it('should render TextEnd artifact links', () => {
      render(<MessageBubble.TextEnd event={mockTextEndArtifactEvent} />);

      expect(screen.getByRole('link', { name: /report\.pdf/i })).toBeInTheDocument();
    });

    it('should return null for empty fullText', () => {
      const emptyEvent = { ...mockTextEndEvent, fullText: '' };
      const { container } = render(<MessageBubble.TextEnd event={emptyEvent} />);

      expect(container.firstChild).toBe(null);
    });
  });

  describe('Artifact Created Sub-Component', () => {
    it('should render ArtifactCreated sub-component', () => {
      render(<MessageBubble.ArtifactCreated event={mockArtifactEvent} />);

      expect(screen.getByText('test.png')).toBeInTheDocument();
      expect(screen.getByText('File Generated')).toBeInTheDocument();
    });

    it('should display image preview for image artifacts', () => {
      render(<MessageBubble.ArtifactCreated event={mockArtifactEvent} />);

      const img = screen.getByRole('img') || screen.getByAltText('test.png');
      expect(img).toBeInTheDocument();
    });
  });

  describe('Backward Compatibility', () => {
    it('should work with legacy props', () => {
      render(<MessageBubble event={mockUserEvent} isStreaming={false} allEvents={[]} />);

      expect(screen.getByText('Hello, how are you?')).toBeInTheDocument();
    });
  });

  describe('Compound Component Namespace', () => {
    it('should export the component', () => {
      expect(MessageBubble).toBeDefined();
      expect(MessageBubble.displayName).toBe('MessageBubble');
    });

    it('should export all sub-components', () => {
      expect(MessageBubble.User).toBeDefined();
      expect(MessageBubble.Assistant).toBeDefined();
      expect(MessageBubble.TextDelta).toBeDefined();
      expect(MessageBubble.Thought).toBeDefined();
      expect(MessageBubble.ToolExecution).toBeDefined();
      expect(MessageBubble.WorkPlan).toBeDefined();
      expect(MessageBubble.TextEnd).toBeDefined();
      expect(MessageBubble.ArtifactCreated).toBeDefined();
      expect(MessageBubble.Root).toBeDefined();
    });

    it('should use Root component as alias', () => {
      render(<MessageBubble.Root event={mockUserEvent} />);

      expect(screen.getByText('Hello, how are you?')).toBeInTheDocument();
    });
  });
});
