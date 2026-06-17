import type { ReactNode } from 'react';

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppLauncher } from '@/components/mcp-app/AppLauncher';
import { mcpAppAPI } from '@/services/mcpAppService';
import { useMCPAppStore } from '@/stores/mcpAppStore';

const mockScope = vi.hoisted(() => ({
  projectId: 'project-1' as string | undefined,
}));

vi.mock('@/components/mcp/useMcpProjectScope', () => ({
  useMcpProjectScope: () => ({ projectId: mockScope.projectId }),
}));

vi.mock('@/stores/canvasStore', () => ({
  usePinnedCanvasTabs: () => [],
  useCanvasStore: {
    getState: () => ({
      openTab: vi.fn(),
      tabs: [],
      togglePin: vi.fn(),
    }),
  },
}));

vi.mock('@/stores/layoutMode', () => ({
  useLayoutModeStore: {
    getState: () => ({
      setMode: vi.fn(),
    }),
  },
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyTooltip: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>();
  return {
    ...actual,
    Popover: ({
      children,
      content,
      open,
      onOpenChange,
    }: {
      children: ReactNode;
      content: ReactNode;
      open?: boolean;
      onOpenChange?: (open: boolean) => void;
    }) => (
      <>
        <span
          onClick={() => {
            onOpenChange?.(!open);
          }}
        >
          {children}
        </span>
        {open ? <div>{content}</div> : null}
      </>
    ),
  };
});

describe('AppLauncher', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockScope.projectId = 'project-1';
    useMCPAppStore.getState().reset();
  });

  it('shows fetch failures instead of an empty launcher state', async () => {
    vi.spyOn(mcpAppAPI, 'list').mockRejectedValue(new Error('Registry unavailable'));

    render(<AppLauncher />);
    fireEvent.click(screen.getByRole('button', { name: 'Open MCP Apps' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load MCP apps');
    expect(screen.getByRole('alert')).toHaveTextContent('Registry unavailable');
    expect(screen.queryByText('No MCP apps available')).not.toBeInTheDocument();
    expect(mcpAppAPI.list).toHaveBeenCalledWith('project-1');
  });

  it('retries loading apps from the failure state', async () => {
    const listSpy = vi
      .spyOn(mcpAppAPI, 'list')
      .mockRejectedValueOnce(new Error('Registry unavailable'))
      .mockResolvedValueOnce([
        {
          id: 'app-1',
          project_id: 'project-1',
          tenant_id: 'tenant-1',
          server_id: 'server-1',
          server_name: 'charts',
          tool_name: 'render_chart',
          ui_metadata: { resourceUri: 'ui://charts/app.html', title: 'Charts' },
          source: 'user_added',
          status: 'ready',
          has_resource: true,
        },
      ]);

    render(<AppLauncher />);
    fireEvent.click(screen.getByRole('button', { name: 'Open MCP Apps' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Registry unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Retry loading apps' }));

    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
    expect(await screen.findByText('Charts')).toBeInTheDocument();
    expect(listSpy).toHaveBeenCalledTimes(2);
    expect(listSpy).toHaveBeenNthCalledWith(1, 'project-1');
    expect(listSpy).toHaveBeenNthCalledWith(2, 'project-1');
  });

  it('does not expose cached apps when scoped project is unavailable', () => {
    mockScope.projectId = undefined;
    const listSpy = vi.spyOn(mcpAppAPI, 'list').mockResolvedValue([]);
    useMCPAppStore.setState({
      apps: {
        'app-1': {
          id: 'app-1',
          project_id: 'project-2',
          tenant_id: 'tenant-2',
          server_id: 'server-1',
          server_name: 'charts',
          tool_name: 'render_chart',
          ui_metadata: { resourceUri: 'ui://charts/app.html', title: 'Charts' },
          source: 'user_added',
          status: 'ready',
          has_resource: true,
        },
      },
      loading: false,
      error: null,
    });

    render(<AppLauncher />);
    fireEvent.click(screen.getByRole('button', { name: 'Open MCP Apps' }));

    expect(screen.queryByText('Charts')).not.toBeInTheDocument();
    expect(screen.getByText('No MCP apps available')).toBeInTheDocument();
    expect(listSpy).not.toHaveBeenCalled();
  });
});
