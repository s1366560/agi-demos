import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SandboxTerminal } from '../../../components/agent/sandbox/SandboxTerminal';
import { SandboxSection } from '../../../components/agent/SandboxSection';
import { useSandboxStore } from '../../../stores/sandbox';

const state = vi.hoisted(() => ({
  availability: { owner: {}, available: true },
  listeners: new Set<() => void>(),
  props: [] as Array<{
    sessionId?: string;
    onConnect(id: string): void;
    onError(error: string): void;
  }>,
}));
vi.mock('../../../plugins/webOperationAdmissionV2', async (original) => ({
  ...(await original<object>()),
  getWebOperationAvailabilityV2: () => state.availability,
  subscribeWebOperationAvailabilityV2: (listener: () => void) => {
    state.listeners.add(listener);
    return () => {
      state.listeners.delete(listener);
    };
  },
}));
vi.mock('../../../components/agent/sandbox/TerminalImpl', () => ({
  default: (props: {
    sessionId?: string;
    onConnect(id: string): void;
    onError(error: string): void;
  }) => {
    state.props.push(props);
    return <div data-testid="terminal-session">{props.sessionId ?? 'fresh'}</div>;
  },
}));
vi.mock('../../../components/agent/sandbox/RemoteDesktopViewer', () => ({
  RemoteDesktopViewer: () => null,
}));
function owner(available = true) {
  act(() => {
    state.availability = { owner: {}, available };
    for (const listener of state.listeners) listener();
  });
}
describe('terminal outer owner identity', () => {
  beforeEach(() => {
    state.availability = { owner: {}, available: true };
    state.props = [];
    state.listeners.clear();
  });
  it('drops previous owner session and ignores late callbacks', async () => {
    const connected = vi.fn(),
      error = vi.fn();
    render(
      <SandboxTerminal
        sandboxId="s1"
        projectId="p1"
        sessionId="old"
        onConnect={connected}
        onError={error}
      />
    );
    await screen.findByText('old');
    const old = state.props.at(-1)!;
    owner();
    await screen.findByText('fresh');
    act(() => {
      old.onConnect('stale');
      old.onError('stale failure');
    });
    expect(connected).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
    expect(screen.queryByText('stale failure')).not.toBeInTheDocument();
  });
  it('clears session on project or sandbox changes and manual restart', async () => {
    const view = render(<SandboxTerminal sandboxId="s1" projectId="p1" sessionId="old" />);
    await screen.findByText('old');
    view.rerender(<SandboxTerminal sandboxId="s1" projectId="p2" sessionId="old" />);
    await screen.findByText('fresh');
    act(() => {
      state.props.at(-1)!.onConnect('current');
    });
    await screen.findByText('current');
    view.rerender(<SandboxTerminal sandboxId="s2" projectId="p2" sessionId="old" />);
    await screen.findByText('fresh');
    act(() => {
      state.props.at(-1)!.onConnect('next');
    });
    await screen.findByText('next');
    const previousAttempt = state.props.at(-1)!;
    fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }));
    await screen.findByText('fresh');
    act(() => previousAttempt.onConnect('stale-retry'));
    expect(screen.queryByText('stale-retry')).not.toBeInTheDocument();
  });
  it('unavailable owner mounts no transport and ready owner starts fresh', async () => {
    state.availability = { owner: {}, available: false };
    render(<SandboxTerminal sandboxId="s1" projectId="p1" sessionId="old" />);
    expect(state.props).toHaveLength(0);
    owner();
    await screen.findByText('fresh');
  });
  it('outer reconnect forces a new terminal rather than retaining the child session', async () => {
    const start = vi.fn().mockResolvedValue(undefined);
    useSandboxStore.setState({
      activeProjectId: 'p1',
      activeSandboxId: 's1',
      terminalStatus: { running: true, url: '/terminal', port: 7681, sessionId: null, pid: null },
      startTerminal: start,
    });
    render(<SandboxSection sandboxId="s1" />);
    await screen.findByText('fresh');
    const old = state.props.at(-1)!;
    act(() => {
      old.onConnect('old-tab-session');
    });
    await screen.findByText('old-tab-session');
    start.mockImplementationOnce(() => {
      old.onConnect('stale-sync');
      return Promise.resolve();
    });
    fireEvent.click(screen.getByRole('button', { name: 'components.sandboxSection.reconnect' }));
    await waitFor(() => expect(start).toHaveBeenCalledOnce());
    await screen.findByText('fresh');
    expect(screen.queryByText('(stale-sy)')).not.toBeInTheDocument();
    expect(screen.queryByText('components.sandboxSection.connected')).not.toBeInTheDocument();
    act(() => old.onConnect('late-tab-session'));
    expect(screen.queryByText('late-tab-session')).not.toBeInTheDocument();
  });
});
