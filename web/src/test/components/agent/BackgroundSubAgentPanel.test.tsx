import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { BackgroundSubAgentPanel } from '../../../components/agent/BackgroundSubAgentPanel';
import { 
  useBackgroundPanel, 
  useBackgroundExecutions, 
  useBackgroundActions 
} from '../../../stores/backgroundStore';

vi.mock('../../../stores/backgroundStore', () => ({
  useBackgroundPanel: vi.fn(),
  useBackgroundExecutions: vi.fn(),
  useBackgroundActions: vi.fn(),
}));

describe('BackgroundSubAgentPanel', () => {
  const mockSetPanel = vi.fn();
  const mockClear = vi.fn();
  const mockClearAll = vi.fn();
  const mockKill = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();

    (useBackgroundPanel as any).mockReturnValue(true);
    (useBackgroundActions as any).mockReturnValue({
      setPanel: mockSetPanel,
      clear: mockClear,
      clearAll: mockClearAll,
      kill: mockKill,
    });
    
    (useBackgroundExecutions as any).mockReturnValue([
      {
        executionId: 'exec-1',
        subagentName: 'Agent 1',
        task: 'Task 1 description',
        status: 'running',
        startedAt: Date.now() - 5000,
        progress: 45,
        progressMessage: 'Downloading files...',
      },
      {
        executionId: 'exec-2',
        subagentName: 'Agent 2',
        task: 'Task 2 description',
        status: 'completed',
        startedAt: Date.now() - 10000,
        completedAt: Date.now() - 1000,
        tokensUsed: 2500,
        summary: 'Completed successfully',
      }
    ]);
  });

  it('renders nothing when panelOpen is false', () => {
    (useBackgroundPanel as any).mockReturnValue(false);
    const { container } = render(<BackgroundSubAgentPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders background subagents when panel is open', () => {
    render(<BackgroundSubAgentPanel />);
    
    expect(screen.getByText('agent.background.title')).toBeInTheDocument();
    
    // Shows agent names
    expect(screen.getByText('Agent 1')).toBeInTheDocument();
    expect(screen.getByText('Agent 2')).toBeInTheDocument();
    
    // Shows task descriptions
    expect(screen.getByText('Task 1 description')).toBeInTheDocument();
    expect(screen.getByText('Task 2 description')).toBeInTheDocument();

    // Shows progress message for running agent
    expect(screen.getByText('Downloading files...')).toBeInTheDocument();
  });

  it('calls kill action when stop button is clicked on running agent', () => {
    render(<BackgroundSubAgentPanel />);
    
    const killButton = screen.getByTitle('agent.background.kill');
    fireEvent.click(killButton);
    
    expect(mockKill).toHaveBeenCalledWith('exec-1');
  });

  it('calls clear action when clear button is clicked on completed agent', () => {
    render(<BackgroundSubAgentPanel />);
    
    const clearButton = screen.getByTitle('agent.background.clear');
    fireEvent.click(clearButton);
    
    expect(mockClear).toHaveBeenCalledWith('exec-2');
  });

  it('calls clearAll action when clear all button is clicked', () => {
    render(<BackgroundSubAgentPanel />);
    
    const clearAllButton = screen.getByText('agent.background.clearAll');
    fireEvent.click(clearAllButton);
    
    expect(mockClearAll).toHaveBeenCalled();
  });

  it('renders empty state when no executions', () => {
    (useBackgroundExecutions as any).mockReturnValue([]);
    render(<BackgroundSubAgentPanel />);
    
    expect(screen.getByText('agent.background.empty')).toBeInTheDocument();
  });

  it('toggles execution details when show details button is clicked', () => {
    render(<BackgroundSubAgentPanel />);
    
    const showDetailsBtn = screen.getByText('agent.background.showDetails');
    fireEvent.click(showDetailsBtn);
    
    expect(screen.getByText('agent.background.hideDetails')).toBeInTheDocument();
    // Because it is expanded, the summary should be visible
    expect(screen.getByText('Completed successfully')).toBeInTheDocument();
  });
});
