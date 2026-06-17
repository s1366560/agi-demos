import type { ReactNode } from 'react';

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppLauncher } from '@/components/mcp-app/AppLauncher';
import { mcpAppAPI } from '@/services/mcpAppService';
import { useMCPAppStore } from '@/stores/mcpAppStore';

vi.mock('@/stores/project', () => ({
  useProjectStore: (
    selector: (state: { currentProject: { id: string; name: string } }) => unknown
  ) => selector({ currentProject: { id: 'project-1', name: 'Project One' } }),
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
    useMCPAppStore.getState().reset();
  });

  it('shows fetch failures instead of an empty launcher state', async () => {
    vi.spyOn(mcpAppAPI, 'list').mockRejectedValue(new Error('Registry unavailable'));

    render(<AppLauncher />);
    fireEvent.click(screen.getByRole('button', { name: 'Open MCP Apps' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load MCP apps');
    expect(screen.getByRole('alert')).toHaveTextContent('Registry unavailable');
    expect(screen.queryByText('No MCP apps available')).not.toBeInTheDocument();
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
  });
});
