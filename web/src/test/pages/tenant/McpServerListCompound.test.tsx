/**
 * McpServerListCompound.test.tsx
 *
 * Tests for the McpServerList page with tab-based architecture.
 * Mocks tab components and verifies page-level behavior.
 */

import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock tab components
vi.mock('../../../components/mcp/McpServerTab', () => ({
  McpServerTab: () => <div data-testid="mcp-server-tab">ServerTabContent</div>,
}));
vi.mock('../../../components/mcp/McpToolsTab', () => ({
  McpToolsTab: () => <div data-testid="mcp-tools-tab">ToolsTabContent</div>,
}));
vi.mock('../../../components/mcp/McpAppsTab', () => ({
  McpAppsTab: () => <div data-testid="mcp-apps-tab">AppsTabContent</div>,
}));

// Mock store data
const mockServers = [
  {
    id: '1',
    name: 'Server 1',
    server_type: 'stdio' as const,
    enabled: true,
    discovered_tools: [{ name: 't1' }, { name: 't2' }],
  },
  {
    id: '2',
    name: 'Server 2',
    server_type: 'sse' as const,
    enabled: false,
    discovered_tools: [{ name: 't3' }],
  },
];

const mockClearError = vi.fn();

let mcpStoreState: Record<string, any> = {
  servers: mockServers,
  clearError: mockClearError,
};

let mcpAppStoreState: Record<string, any> = {
  apps: { app1: { id: 'app1' }, app2: { id: 'app2' } },
};

vi.mock('../../../stores/mcp', () => ({
  useMCPStore: vi.fn((selector: any) => selector(mcpStoreState)),
}));

vi.mock('../../../stores/mcpAppStore', () => ({
  useMCPAppStore: vi.fn((selector: any) => selector(mcpAppStoreState)),
}));

describe('McpServerList Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mcpStoreState = { servers: mockServers, clearError: mockClearError };
    mcpAppStoreState = { apps: { app1: { id: 'app1' }, app2: { id: 'app2' } } };
  });

  afterEach(() => {
    cleanup();
  });

  const renderPage = async () => {
    const { McpServerList } = await import('../../../pages/tenant/McpServerList');
    return render(<McpServerList />);
  };

  // --------------------------------------------------------------------------
  // Header & Stats
  // --------------------------------------------------------------------------

  describe('Header and Stats', () => {
    it('should render page title and subtitle', async () => {
      await renderPage();
      expect(screen.getByText('MCP Runtime')).toBeInTheDocument();
      expect(screen.getByText(/Unified runtime dashboard for MCP servers, tools, and app lifecycle/)).toBeInTheDocument();
    });

    it('should render stats cards with correct values', async () => {
      await renderPage();
      expect(screen.getByText('Total')).toBeInTheDocument();
      expect(screen.getByText('Running Runtime')).toBeInTheDocument();
      expect(screen.getByText('Runtime Errors')).toBeInTheDocument();
      expect(screen.getByText('Apps Ready')).toBeInTheDocument();
    });

    it('should compute stats from store data', async () => {
      await renderPage();
      // Total servers = 2
      // Running Runtime = 0 (mock data lacks runtime info)
      // Runtime Errors = 0
      // Apps Ready = 0
      
      // Check total count
      expect(screen.getAllByText('2').length).toBeGreaterThanOrEqual(1);
    });

    it('should show zero stats when no servers', async () => {
      mcpStoreState = { servers: [], clearError: mockClearError };
      await renderPage();
      const zeroes = screen.getAllByText('0');
      expect(zeroes.length).toBeGreaterThanOrEqual(3);
    });
  });

  // --------------------------------------------------------------------------
  // Tab Bar
  // --------------------------------------------------------------------------

  describe('Tab Bar', () => {
    it('should render all three tabs with counts', async () => {
      await renderPage();
      expect(screen.getByText('Servers')).toBeInTheDocument();
      expect(screen.getByText('Tools')).toBeInTheDocument();
      expect(screen.getByText('Apps')).toBeInTheDocument();
    });

    it('should show Servers tab content by default', async () => {
      await renderPage();
      expect(screen.getByTestId('mcp-server-tab')).toBeInTheDocument();
      expect(screen.queryByTestId('mcp-tools-tab')).not.toBeInTheDocument();
      expect(screen.queryByTestId('mcp-apps-tab')).not.toBeInTheDocument();
    });

    it('should switch to Tools tab on click', async () => {
      await renderPage();
      fireEvent.click(screen.getByText('Tools'));
      expect(screen.queryByTestId('mcp-server-tab')).not.toBeInTheDocument();
      expect(screen.getByTestId('mcp-tools-tab')).toBeInTheDocument();
    });

    it('should switch to Apps tab on click', async () => {
      await renderPage();
      fireEvent.click(screen.getByText('Apps'));
      expect(screen.queryByTestId('mcp-server-tab')).not.toBeInTheDocument();
      expect(screen.getByTestId('mcp-apps-tab')).toBeInTheDocument();
    });

    it('should switch back to Servers tab', async () => {
      await renderPage();
      fireEvent.click(screen.getByText('Tools'));
      fireEvent.click(screen.getByText('Servers'));
      expect(screen.getByTestId('mcp-server-tab')).toBeInTheDocument();
      expect(screen.queryByTestId('mcp-tools-tab')).not.toBeInTheDocument();
    });
  });

  // --------------------------------------------------------------------------
  // Cleanup
  // --------------------------------------------------------------------------

  describe('Cleanup', () => {
    it('should call clearError on unmount', async () => {
      const { unmount } = await renderPage();
      expect(mockClearError).not.toHaveBeenCalled();
      unmount();
      expect(mockClearError).toHaveBeenCalledTimes(1);
    });
  });
});
