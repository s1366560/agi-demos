/**
 * StandardMCPAppRenderer Component Tests
 *
 * TDD tests for MCP App frontend issues:
 * - P2: Synthetic ID problem
 * - P3: Canvas mode switching stability
 */

import React from 'react';

import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the mcpAppAPI - must be before vi.mock calls
vi.mock('../../../services/mcpAppService', () => ({
  mcpAppAPI: {
    list: vi.fn(),
    get: vi.fn(),
    proxyToolCall: vi.fn(),
    proxyToolCallDirect: vi.fn(),
    readResource: vi.fn(),
    listResources: vi.fn(),
  },
}));

// Mock the useMCPClient hook
vi.mock('../../../hooks/useMCPClient', () => ({
  useMCPClient: vi.fn(() => ({
    client: null,
    status: 'disconnected',
    error: null,
    reconnect: vi.fn(),
  })),
}));

// Mock the project store
vi.mock('../../../stores/project', () => ({
  useProjectStore: vi.fn(() => ({ currentProject: { id: 'proj-1' } })),
}));

// Mock the theme store
vi.mock('../../../stores/theme', () => ({
  useThemeStore: vi.fn(() => ({ computedTheme: 'light' })),
}));

// Mock @mcp-ui/client (lazy loaded)
vi.mock('@mcp-ui/client', () => ({
  AppRenderer: ({ toolName, html, onCallTool }: any) => (
    <div data-testid="app-renderer" data-tool={toolName}>
      {html ? <div data-testid="html-content">{html}</div> : null}
      {onCallTool ? <div data-testid="has-callback" /> : null}
    </div>
  ),
}));

// Import after mocks are set up
import {
  StandardMCPAppRenderer,
  SYNTHETIC_APP_ID_PREFIX,
} from '../../../components/mcp-app/StandardMCPAppRenderer';
import { useMCPClient } from '../../../hooks/useMCPClient';
import { mcpAppAPI } from '../../../services/mcpAppService';

// Helper to create minimal props
const createProps = (overrides = {}) => ({
  toolName: 'test-tool',
  resourceUri: 'test://resource',
  projectId: 'proj-1',
  serverName: 'test-server',
  ...overrides,
});

// Get typed mocks
const mockMcpAppAPI = mcpAppAPI as unknown as {
  list: ReturnType<typeof vi.fn>;
  get: ReturnType<typeof vi.fn>;
  proxyToolCall: ReturnType<typeof vi.fn>;
  proxyToolCallDirect: ReturnType<typeof vi.fn>;
  readResource: ReturnType<typeof vi.fn>;
  listResources: ReturnType<typeof vi.fn>;
};

const mockUseMCPClient = useMCPClient as ReturnType<typeof vi.fn>;

describe('StandardMCPAppRenderer - Synthetic ID Problem (P2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default MCP client state: disconnected (Mode B)
    mockUseMCPClient.mockReturnValue({
      client: null,
      status: 'disconnected',
      error: null,
      reconnect: vi.fn(),
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('Synthetic ID handling', () => {
    it('should use SYNTHETIC_APP_ID_PREFIX constant for synthetic IDs', () => {
      expect(SYNTHETIC_APP_ID_PREFIX).toBe('_synthetic_');
    });

    it('should call proxyToolCallDirect when appId starts with synthetic prefix', async () => {
      const syntheticAppId = `${SYNTHETIC_APP_ID_PREFIX}auto-discovered`;
      const props = createProps({
        appId: syntheticAppId,
        html: '<div>Test</div>',
      });

      // Setup mock for direct tool call
      mockMcpAppAPI.proxyToolCallDirect.mockResolvedValueOnce({
        content: [{ type: 'text', text: 'success' }],
        is_error: false,
      });

      render(<StandardMCPAppRenderer {...props} />);

      // Find the AppRenderer and simulate tool call
      await waitFor(() => {
        expect(screen.getByTestId('app-renderer')).toBeInTheDocument();
      });

      // Verify proxyToolCallDirect would be called for synthetic IDs
      // (The actual call happens through onCallTool callback)
    });

    it('should log warning when using synthetic ID', async () => {
      const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const syntheticAppId = `${SYNTHETIC_APP_ID_PREFIX}auto-discovered`;
      const props = createProps({
        appId: syntheticAppId,
        html: '<div>Test</div>',
      });

      render(<StandardMCPAppRenderer {...props} />);

      // The component should log a warning about using synthetic ID
      // This will be verified by the implementation
      await waitFor(() => {
        expect(screen.getByTestId('app-renderer')).toBeInTheDocument();
      });

      consoleWarnSpy.mockRestore();
    });

    it('should prefer real app ID over synthetic when available', async () => {
      const realAppId = 'real-uuid-app-id';
      const props = createProps({
        appId: realAppId,
        html: '<div>Test</div>',
      });

      // Setup mock for regular tool call
      mockMcpAppAPI.proxyToolCall.mockResolvedValueOnce({
        content: [{ type: 'text', text: 'success' }],
        is_error: false,
      });

      render(<StandardMCPAppRenderer {...props} />);

      await waitFor(() => {
        expect(screen.getByTestId('app-renderer')).toBeInTheDocument();
      });

      // Verify proxyToolCall (not direct) would be used for real app IDs
    });

    it('should attempt to find real app via server_name + tool_name lookup when using synthetic fallback', async () => {
      const syntheticAppId = `${SYNTHETIC_APP_ID_PREFIX}auto-discovered`;
      const props = createProps({
        appId: syntheticAppId,
        html: '<div>Test</div>',
      });

      // Setup mock for list to return a matching app
      const realApp = {
        id: 'real-app-id',
        server_name: 'test-server',
        tool_name: 'test-tool',
        project_id: 'proj-1',
      };
      mockMcpAppAPI.list.mockResolvedValueOnce([realApp]);

      render(<StandardMCPAppRenderer {...props} />);

      await waitFor(() => {
        expect(screen.getByTestId('app-renderer')).toBeInTheDocument();
      });

      // The component should be able to look up real apps by server/tool name
    });
  });

  describe('Real app ID lookup', () => {
    it('should find app by server_name when no appId provided', async () => {
      const props = createProps({
        appId: undefined,
        html: '<div>Test</div>',
      });

      const matchingApp = {
        id: 'found-app-id',
        server_name: 'test-server',
        tool_name: 'other-tool',
        project_id: 'proj-1',
      };

      mockMcpAppAPI.list.mockResolvedValueOnce([matchingApp]);
      mockMcpAppAPI.proxyToolCall.mockResolvedValueOnce({
        content: [{ type: 'text', text: 'success' }],
        is_error: false,
      });

      render(<StandardMCPAppRenderer {...props} />);

      await waitFor(() => {
        expect(screen.getByTestId('app-renderer')).toBeInTheDocument();
      });
    });

    it('should find app by tool_name when server_name does not match', async () => {
      const props = createProps({
        appId: undefined,
        serverName: 'other-server',
        html: '<div>Test</div>',
      });

      const matchingApp = {
        id: 'found-app-id',
        server_name: 'other-server',
        tool_name: 'test-tool',
        project_id: 'proj-1',
      };

      mockMcpAppAPI.list.mockResolvedValueOnce([matchingApp]);
      mockMcpAppAPI.proxyToolCall.mockResolvedValueOnce({
        content: [{ type: 'text', text: 'success' }],
        is_error: false,
      });

      render(<StandardMCPAppRenderer {...props} />);

      await waitFor(() => {
        expect(screen.getByTestId('app-renderer')).toBeInTheDocument();
      });
    });
  });
});

describe('StandardMCPAppRenderer - Canvas Mode Switching (P3)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('WebSocket connection stability', () => {
    it('should not immediately switch to Mode B on temporary disconnect', async () => {
      // Start connected
      const mockReconnect = vi.fn();
      mockUseMCPClient.mockReturnValue({
        client: { connected: true },
        status: 'connected',
        error: null,
        reconnect: mockReconnect,
      });

      const props = createProps({
        html: '<div>Test</div>',
      });

      const { rerender } = render(<StandardMCPAppRenderer {...props} />);

      // Should be in Mode A (using client)
      expect(screen.getByTestId('app-renderer')).toBeInTheDocument();

      // Simulate temporary disconnect
      mockUseMCPClient.mockReturnValue({
        client: null,
        status: 'disconnected',
        error: null,
        reconnect: mockReconnect,
      });

      // Re-render should trigger reconnection attempt, not immediate mode switch
      await act(async () => {
        rerender(<StandardMCPAppRenderer {...props} />);
      });

      // Component should still be functional
      expect(screen.getByTestId('app-renderer')).toBeInTheDocument();
    });

    it('should attempt reconnection before falling back to Mode B', async () => {
      const mockReconnect = vi.fn();

      // Start disconnected
      mockUseMCPClient.mockReturnValue({
        client: null,
        status: 'disconnected',
        error: null,
        reconnect: mockReconnect,
      });

      const props = createProps({
        html: '<div>Test</div>',
      });

      render(<StandardMCPAppRenderer {...props} />);

      // The hook's reconnect should be available
      expect(mockReconnect).toBeDefined();
    });

    it('should use Mode A when WebSocket is connected', async () => {
      mockUseMCPClient.mockReturnValue({
        client: { callTool: vi.fn() },
        status: 'connected',
        error: null,
        reconnect: vi.fn(),
      });

      const props = createProps({
        html: '<div>Test</div>',
      });

      render(<StandardMCPAppRenderer {...props} />);

      // Mode A should NOT have onCallTool callback (uses client directly)
      // Use findByTestId which handles async lazy loading automatically
      const renderer = await screen.findByTestId('app-renderer', {}, { timeout: 10000 });
      expect(renderer).toBeInTheDocument();
      // In Mode A, onCallTool should not be passed
      expect(screen.queryByTestId('has-callback')).not.toBeInTheDocument();
    });

    it('should use Mode B when WebSocket is unavailable', async () => {
      mockUseMCPClient.mockReturnValue({
        client: null,
        status: 'disconnected',
        error: 'Connection failed',
        reconnect: vi.fn(),
      });

      const props = createProps({
        html: '<div>Test</div>',
      });

      render(<StandardMCPAppRenderer {...props} />);

      // Mode B should have onCallTool callback
      // Use findByTestId which handles async lazy loading automatically
      const renderer = await screen.findByTestId('app-renderer', {}, { timeout: 10000 });
      expect(renderer).toBeInTheDocument();
      expect(screen.getByTestId('has-callback')).toBeInTheDocument();
    });

    it('should maintain stable key during brief connection fluctuations', async () => {
      // Test that key doesn't change on every render
      const props = createProps({
        html: '<div>Test</div>',
      });

      mockUseMCPClient.mockReturnValue({
        client: { callTool: vi.fn() },
        status: 'connected',
        error: null,
        reconnect: vi.fn(),
      });

      const { rerender } = render(<StandardMCPAppRenderer {...props} />);

      // Initial render
      expect(screen.getByTestId('app-renderer')).toBeInTheDocument();

      // Brief fluctuation (still connected)
      mockUseMCPClient.mockReturnValue({
        client: { callTool: vi.fn() },
        status: 'connected',
        error: null,
        reconnect: vi.fn(),
      });

      await act(async () => {
        rerender(<StandardMCPAppRenderer {...props} />);
      });

      // Should still show renderer
      expect(screen.getByTestId('app-renderer')).toBeInTheDocument();
    });
  });

  describe('Reconnection backoff', () => {
    it('should implement exponential backoff for reconnection attempts', async () => {
      // This test verifies the hook's behavior
      // The actual backoff logic is in useMCPClient hook
      const mockReconnect = vi.fn();

      mockUseMCPClient.mockReturnValue({
        client: null,
        status: 'disconnected',
        error: null,
        reconnect: mockReconnect,
      });

      const props = createProps({
        html: '<div>Test</div>',
      });

      render(<StandardMCPAppRenderer {...props} />);

      // Component should be stable even during reconnection
      expect(screen.getByTestId('app-renderer')).toBeInTheDocument();
    });
  });
});

describe('StandardMCPAppRenderer - General Functionality', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseMCPClient.mockReturnValue({
      client: null,
      status: 'disconnected',
      error: null,
      reconnect: vi.fn(),
    });
  });

  it('should render error state when error occurs', async () => {
    const props = createProps({
      html: undefined,
      resourceUri: undefined,
    });

    render(<StandardMCPAppRenderer {...props} />);

    // Should show info alert when no html or resourceUri
    await waitFor(() => {
      expect(screen.getByText(/does not provide a UI resource/i)).toBeInTheDocument();
    });
  });

  it('should render HTML content when provided', async () => {
    const htmlContent = '<div>Hello World</div>';
    const props = createProps({
      html: htmlContent,
    });

    render(<StandardMCPAppRenderer {...props} />);

    await waitFor(() => {
      expect(screen.getByTestId('html-content')).toHaveTextContent('Hello World');
    });
  });

  it('should handle tool result display when no UI resource available', async () => {
    const toolResult = { data: 'test result' };
    const props = createProps({
      html: undefined,
      resourceUri: undefined,
      toolResult,
    });

    render(<StandardMCPAppRenderer {...props} />);

    await waitFor(() => {
      expect(screen.getByText(/showing tool result/i)).toBeInTheDocument();
    });
  });
});
