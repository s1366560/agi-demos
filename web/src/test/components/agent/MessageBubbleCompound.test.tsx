/**
 * Tests for MessageBubble Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

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

const mockStepStartEvent: any = {
  id: '9',
  type: 'step_start',
  stepDescription: 'Executing step 1',
  stepIndex: 0,
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

      expect(screen.getByTestId('avatar')).toBeInTheDocument();
      expect(screen.getByText('Hello, how are you?')).toBeInTheDocument();
    });

    it('should render assistant message event', () => {
      render(<MessageBubble event={mockAssistantEvent} />);

      expect(screen.getByTestId('avatar')).toBeInTheDocument();
      expect(screen.getByTestId('markdown')).toBeInTheDocument();
    });

    it('should render text delta event', () => {
      render(<MessageBubble event={mockTextDeltaEvent} />);

      expect(screen.getByTestId('avatar')).toBeInTheDocument();
      expect(screen.getByTestId('markdown')).toBeInTheDocument();
    });

    it('should render text end event', () => {
      render(<MessageBubble event={mockTextEndEvent} />);

      expect(screen.getByTestId('avatar')).toBeInTheDocument();
      expect(screen.getByTestId('markdown')).toBeInTheDocument();
    });

    it('should render thought event', () => {
      render(<MessageBubble event={mockThoughtEvent} />);

      expect(screen.getByText('Reasoning Log')).toBeInTheDocument();
      expect(screen.getByText('Thinking about the response')).toBeInTheDocument();
    });

    it('should render act (tool execution) event', () => {
      const allEvents = [mockActEvent, mockObserveEvent];
      render(<MessageBubble event={mockActEvent} allEvents={allEvents} />);

      expect(screen.getByText('search')).toBeInTheDocument();
      expect(screen.getByTestId('tag')).toBeInTheDocument();
    });

    it('should return null for observe event (rendered with act)', () => {
      const { container } = render(<MessageBubble event={mockObserveEvent} />);

      expect(container.firstChild).toBe(null);
    });

    it('should render work plan event', () => {
      render(<MessageBubble event={mockWorkPlanEvent} />);

      expect(screen.getByText(/Work Plan:/)).toBeInTheDocument();
      expect(screen.getByText('Step 1')).toBeInTheDocument();
      expect(screen.getByText('Step 2')).toBeInTheDocument();
    });

    it('should render step start event', () => {
      render(<MessageBubble event={mockStepStartEvent} />);

      expect(screen.getByText('Executing step 1')).toBeInTheDocument();
    });

    it('should render artifact created event', () => {
      render(<MessageBubble event={mockArtifactEvent} />);

      expect(screen.getByText('test.png')).toBeInTheDocument();
      expect(screen.getByText(/1\.0 KB/)).toBeInTheDocument();
    });

    it('should return null for control events', () => {
      const { container } = render(
        <MessageBubble event={{ type: 'step_end' as any, id: '11', timestamp: Date.now() }} />
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

      expect(screen.getByText(/Work Plan:/)).toBeInTheDocument();
      expect(screen.getByText('Step 1')).toBeInTheDocument();
    });

    it('should return null for empty steps', () => {
      const emptyEvent = { ...mockWorkPlanEvent, steps: [] };
      const { container } = render(<MessageBubble.WorkPlan event={emptyEvent} />);

      expect(container.firstChild).toBe(null);
    });
  });

  describe('Step Start Sub-Component', () => {
    it('should render StepStart sub-component', () => {
      render(<MessageBubble.StepStart event={mockStepStartEvent} />);

      expect(screen.getByText('Executing step 1')).toBeInTheDocument();
    });

    it('should return null when no step description', () => {
      const emptyEvent = { ...mockStepStartEvent, stepDescription: undefined };
      const { container } = render(<MessageBubble.StepStart event={emptyEvent} />);

      expect(container.firstChild).toBe(null);
    });
  });

  describe('Text End Sub-Component', () => {
    it('should render TextEnd sub-component', () => {
      render(<MessageBubble.TextEnd event={mockTextEndEvent} />);

      expect(screen.getByText('Complete response here')).toBeInTheDocument();
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
      expect(screen.getByText(/文件已生成/)).toBeInTheDocument();
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
      expect(MessageBubble.StepStart).toBeDefined();
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
