import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { BackgroundSubAgentPanel } from '../../../components/agent/BackgroundSubAgentPanel';
import {
  useBackgroundPanel,
  useBackgroundExecutions,
  useBackgroundActions,
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
      },
    ]);
  });

  it('renders nothing when panelOpen is false', () => {
    (useBackgroundPanel as any).mockReturnValue(false);
    const { container } = render(<BackgroundSubAgentPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders background subagents when panel is open', () => {
    render(<BackgroundSubAgentPanel />);

    expect(screen.getByText('Background Tasks')).toBeInTheDocument();

    // Shows agent names
    expect(screen.getByText('Agent 1')).toBeInTheDocument();
    expect(screen.getByText('Agent 2')).toBeInTheDocument();

    // Shows task descriptions
    expect(screen.getByText('Task 1 description')).toBeInTheDocument();
    expect(screen.getByText('Task 2 description')).toBeInTheDocument();

    // Shows progress message for running agent
    expect(screen.getByText('Downloading files...')).toBeInTheDocument();
  });

  it('calls kill action when stop button is clicked on running agent', async () => {
    render(<BackgroundSubAgentPanel />);

    const killButton = screen.getByTitle('Stop execution');
    fireEvent.click(killButton);

    // The trigger and confirmation action share the same accessible name.
    const stopButtons = await screen.findAllByRole('button', { name: 'Stop execution' });
    fireEvent.click(stopButtons[stopButtons.length - 1]!);

    expect(mockKill).toHaveBeenCalledWith('exec-1');
  });

  it('calls clear action when clear button is clicked on completed agent', () => {
    render(<BackgroundSubAgentPanel />);

    const clearButton = screen.getByTitle('Clear');
    fireEvent.click(clearButton);

    expect(mockClear).toHaveBeenCalledWith('exec-2');
  });

  it('calls clearAll action when clear all button is clicked', async () => {
    render(<BackgroundSubAgentPanel />);

    const clearAllButton = screen.getByText('Clear all');
    fireEvent.click(clearAllButton);

    // Confirm the destructive action in the Popconfirm dialog (trigger and OK
    // share the label, so pick the dialog's button)
    const matches = await screen.findAllByText('Clear all');
    fireEvent.click(matches[matches.length - 1]!);

    expect(mockClearAll).toHaveBeenCalled();
  });

  it('renders empty state when no executions', () => {
    (useBackgroundExecutions as any).mockReturnValue([]);
    render(<BackgroundSubAgentPanel />);

    expect(screen.getByText('No background tasks')).toBeInTheDocument();
  });

  it('toggles execution details when show details button is clicked', () => {
    render(<BackgroundSubAgentPanel />);

    const showDetailsBtn = screen.getByText('Show details');
    fireEvent.click(showDetailsBtn);

    expect(screen.getByText('Hide details')).toBeInTheDocument();
    // Because it is expanded, the summary should be visible
    expect(screen.getByText('Completed successfully')).toBeInTheDocument();
  });
});
