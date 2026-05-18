import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SandboxSection } from '../../../components/agent/SandboxSection';
import { projectSandboxService } from '../../../services/projectSandboxService';
import { useSandboxStore } from '../../../stores/sandbox';

vi.mock('../../../components/agent/sandbox/RemoteDesktopViewer', () => ({
  RemoteDesktopViewer: ({ sandboxId }: { sandboxId: string }) => (
    <div data-testid="remote-desktop">desktop {sandboxId}</div>
  ),
}));

vi.mock('../../../components/agent/sandbox/SandboxTerminal', () => ({
  SandboxTerminal: ({ sandboxId }: { sandboxId: string }) => (
    <div data-testid="sandbox-terminal">terminal {sandboxId}</div>
  ),
}));

vi.mock('../../../services/projectSandboxService', () => ({
  projectSandboxService: {
    ensureProxyAuthCookie: vi.fn(),
    ensureSandbox: vi.fn(),
    executeTool: vi.fn(),
    startDesktop: vi.fn(),
    startTerminal: vi.fn(),
    stopDesktop: vi.fn(),
    stopTerminal: vi.fn(),
  },
}));

function StoreBackedSandboxSection() {
  const sandboxId = useSandboxStore((state) => state.activeSandboxId);
  return <SandboxSection sandboxId={sandboxId} />;
}

describe('SandboxSection', () => {
  const mockedProjectSandboxService = vi.mocked(projectSandboxService);

  beforeEach(() => {
    vi.clearAllMocks();
    useSandboxStore.getState().reset();
    mockedProjectSandboxService.ensureSandbox.mockResolvedValue({
      sandbox_id: 'sandbox-1',
      project_id: 'project-1',
      tenant_id: 'tenant-1',
      status: 'running',
      terminal_url: '/terminal',
      terminal_port: 7681,
      is_healthy: true,
    });
  });

  it('ensures the project sandbox when the code panel opens without a sandbox id', async () => {
    act(() => {
      useSandboxStore.getState().setProjectId('project-1');
    });

    render(<StoreBackedSandboxSection />);

    await waitFor(() => {
      expect(mockedProjectSandboxService.ensureSandbox).toHaveBeenCalledWith('project-1');
    });
    await waitFor(() => {
      expect(screen.getByTestId('sandbox-terminal')).toHaveTextContent('terminal sandbox-1');
    });
  });

  it('does not create another sandbox when a sandbox id is already attached', async () => {
    act(() => {
      useSandboxStore.getState().setProjectId('project-1');
      useSandboxStore.getState().setSandboxId('sandbox-existing');
      useSandboxStore.getState().setTerminalStatus({
        running: true,
        url: '/terminal',
        port: 7681,
        sessionId: null,
        pid: null,
      });
    });

    render(<StoreBackedSandboxSection />);

    expect(screen.getByTestId('sandbox-terminal')).toHaveTextContent('terminal sandbox-existing');
    expect(mockedProjectSandboxService.ensureSandbox).not.toHaveBeenCalled();
  });
});
