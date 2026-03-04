import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SubAgentDetailPanel } from '../../../../components/agent/timeline/SubAgentDetailPanel';

describe('SubAgentDetailPanel', () => {
  const mockOnClose = vi.fn();

  const mockGroup: any = {
    subagentId: 'sub-123456789',
    subagentName: 'TestAgent',
    status: 'running',
    mode: 'parallel',
    executionTimeMs: 1500,
    tokensUsed: 1200,
    modelName: 'gpt-4',
    events: [
      { id: 'e1', type: 'agent_start', timestamp: 1000 },
      { id: 'e2', type: 'tool_call', timestamp: 2000 }
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders correctly with given props', () => {
    render(<SubAgentDetailPanel group={mockGroup} onClose={mockOnClose} />);

    // Renders name and truncated ID
    expect(screen.getByText('TestAgent')).toBeInTheDocument();
    expect(screen.getByText('sub-1234...')).toBeInTheDocument();
    
    // Renders model name
    expect(screen.getByText('gpt-4')).toBeInTheDocument();

    // Renders metrics
    expect(screen.getByText('parallel')).toBeInTheDocument();
    expect(screen.getByText('1.5s')).toBeInTheDocument(); // formatDuration(1500)
    expect(screen.getByText('1.2k')).toBeInTheDocument(); // formatTokens(1200)

    // Renders events
    expect(screen.getByText('Agent Start')).toBeInTheDocument(); // formatEventType('agent_start')
    expect(screen.getByText('Tool Call')).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', () => {
    render(<SubAgentDetailPanel group={mockGroup} onClose={mockOnClose} />);
    
    const closeButton = screen.getByRole('button');
    fireEvent.click(closeButton);
    
    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it('renders error section when error is present', () => {
    const errorGroup = { ...mockGroup, error: 'Execution failed', status: 'error' };
    render(<SubAgentDetailPanel group={errorGroup} onClose={mockOnClose} />);
    
    expect(screen.getByText('agent.subagent.detail.error_title')).toBeInTheDocument();
    expect(screen.getByText('Execution failed')).toBeInTheDocument();
  });

  it('renders summary section when summary is present', () => {
    const summaryGroup = { ...mockGroup, summary: 'Task completed successfully', status: 'success' };
    render(<SubAgentDetailPanel group={summaryGroup} onClose={mockOnClose} />);
    
    expect(screen.getByText('agent.subagent.detail.summary_title')).toBeInTheDocument();
    expect(screen.getByText('Task completed successfully')).toBeInTheDocument();
  });

  it('handles missing metrics gracefully', () => {
    const emptyGroup = {
      subagentId: 'sub-987654321',
      subagentName: 'EmptyAgent',
      status: 'queued',
      events: []
    };
    render(<SubAgentDetailPanel group={emptyGroup} onClose={mockOnClose} />);
    
    expect(screen.getByText('EmptyAgent')).toBeInTheDocument();
    expect(screen.queryByText('parallel')).not.toBeInTheDocument();
    expect(screen.queryByText('1.5s')).not.toBeInTheDocument();
  });
});
