/**
 * McpServerListCompound.test.tsx
 *
 * TDD tests for McpServerList compound component pattern.
 * RED phase: Tests are written before implementation.
 */

import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock McpServerModal
vi.mock('../../../components/mcp/McpServerModal', () => ({
  McpServerModal: ({ isOpen, onClose, onSuccess }: any) =>
    isOpen ? (
      <div data-testid="mcp-server-modal">
        <button onClick={onClose}>Close Modal</button>
        <button onClick={onSuccess}>Success Modal</button>
      </div>
    ) : null,
}));

// Mock MCP store
const mockServers = [
  {
    id: '1',
    name: 'Test Server 1',
    description: 'Test description',
    server_type: 'stdio' as const,
    enabled: true,
    transport_config: { command: 'node test.js' },
    discovered_tools: [
      { name: 'tool1', description: 'Test tool 1' },
      { name: 'tool2', description: 'Test tool 2' },
      { name: 'tool3', description: 'Test tool 3' },
      { name: 'tool4', description: 'Test tool 4' },
    ],
    last_sync_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
  },
  {
    id: '2',
    name: 'Test Server 2',
    description: 'Another test server',
    server_type: 'sse' as const,
    enabled: false,
    transport_config: { url: 'http://localhost:3000/sse' },
    discovered_tools: [],
    last_sync_at: undefined,
  },
  {
    id: '3',
    name: 'HTTP Server',
    description: 'HTTP transport server',
    server_type: 'http' as const,
    enabled: true,
    transport_config: { url: 'http://localhost:8080' },
    discovered_tools: [{ name: 'http_tool', description: 'HTTP tool' }],
    last_sync_at: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
  },
];

const mockStoreState = {
  servers: mockServers,
  syncingServers: new Set<string>(),
  testingServers: new Set<string>(),
  isLoading: false,
  error: null,
  listServers: vi.fn(),
  deleteServer: vi.fn(),
  toggleEnabled: vi.fn(),
  syncServer: vi.fn(),
  testServer: vi.fn(() => Promise.resolve({ success: true, latency_ms: 50 })),
  clearError: vi.fn(),
};

vi.mock('../../../stores/mcp', () => ({
  useMCPStore: vi.fn((selector) => {
    return selector(mockStoreState);
  }),
}));

// Mock project store
vi.mock('../../../stores/project', () => ({
  useProjectStore: vi.fn((selector) => {
    return selector({ currentProject: { id: 'test-project-1', name: 'Test Project' } });
  }),
}));

// Mock message from antd
vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...actual,
    message: {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
      info: vi.fn(),
    },
  };
});

describe('McpServerList Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStoreState.syncingServers.clear();
    mockStoreState.testingServers.clear();
  });

  // ============================================================================
  // Import Tests
  // ============================================================================

  describe('Component Structure', () => {
    it('should export McpServerList compound component', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      expect(McpServerList).toBeDefined();
    });

    it('should export Header sub-component', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      expect(McpServerList.Header).toBeDefined();
    });

    it('should export Stats sub-component', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      expect(McpServerList.Stats).toBeDefined();
    });

    it('should export Filters sub-component', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      expect(McpServerList.Filters).toBeDefined();
    });

    it('should export Grid sub-component', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      expect(McpServerList.Grid).toBeDefined();
    });

    it('should export Card sub-component', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      expect(McpServerList.Card).toBeDefined();
    });

    it('should export TypeBadge sub-component', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      expect(McpServerList.TypeBadge).toBeDefined();
    });

    it('should export ToolsModal sub-component', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      expect(McpServerList.ToolsModal).toBeDefined();
    });

    it('should export Loading sub-component', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      expect(McpServerList.Loading).toBeDefined();
    });

    it('should export Empty sub-component', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      expect(McpServerList.Empty).toBeDefined();
    });

    it('should export Modal sub-component', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      expect(McpServerList.Modal).toBeDefined();
    });
  });

  // ============================================================================
  // Main Component Tests
  // ============================================================================

  describe('Main Component', () => {
    it('should render header with title', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList />);
      expect(screen.getByText('MCP Servers')).toBeInTheDocument();
    });

    it('should render stats section', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList />);
      expect(screen.getByText(/Total Servers/)).toBeInTheDocument();
    });

    it('should render filters section', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList />);
      const searchInput = screen.getByPlaceholderText('Search servers...');
      expect(searchInput).toBeInTheDocument();
    });

    it('should render server cards', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList />);
      expect(screen.getByText('Test Server 1')).toBeInTheDocument();
      expect(screen.getByText('Test Server 2')).toBeInTheDocument();
      expect(screen.getByText('HTTP Server')).toBeInTheDocument();
    });

    it('should show loading state when isLoading is true', async () => {
      mockStoreState.isLoading = true;
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList />);
      const loadingElement = document.querySelector('.ant-spin');
      expect(loadingElement).toBeInTheDocument();
      mockStoreState.isLoading = false;
    });

    it('should show empty state when no servers', async () => {
      mockStoreState.servers = [];
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList />);
      expect(screen.getByText(/No MCP servers configured/)).toBeInTheDocument();
      mockStoreState.servers = mockServers;
    });

    it('should call listServers on mount', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList />);
      expect(mockStoreState.listServers).toHaveBeenCalled();
    });
  });

  // ============================================================================
  // Header Sub-Component Tests
  // ============================================================================

  describe('Header Sub-Component', () => {
    it('should render title and subtitle', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Header onCreate={vi.fn()} />);
      expect(screen.getByText('MCP Servers')).toBeInTheDocument();
      expect(screen.getByText(/Manage your Model Context Protocol servers/)).toBeInTheDocument();
    });

    it('should render create button', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      const onCreate = vi.fn();
      render(<McpServerList.Header onCreate={onCreate} />);
      const createButton = screen.getByText('Create Server');
      expect(createButton).toBeInTheDocument();
    });

    it('should call onCreate when create button clicked', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      const onCreate = vi.fn();
      render(<McpServerList.Header onCreate={onCreate} />);
      fireEvent.click(screen.getByText('Create Server'));
      expect(onCreate).toHaveBeenCalledTimes(1);
    });
  });

  // ============================================================================
  // Stats Sub-Component Tests
  // ============================================================================

  describe('Stats Sub-Component', () => {
    it('should render all stats cards', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(
        <McpServerList.Stats
          total={3}
          enabledCount={2}
          totalToolsCount={5}
          serversByType={{ stdio: 1, sse: 1, http: 1, websocket: 0 }}
        />
      );
      expect(screen.getByText('3')).toBeInTheDocument(); // Total
      expect(screen.getByText('2')).toBeInTheDocument(); // Enabled
    });

    it('should display total tools count', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(
        <McpServerList.Stats
          total={3}
          enabledCount={2}
          totalToolsCount={5}
          serversByType={{ stdio: 1, sse: 1, http: 1, websocket: 0 }}
        />
      );
      expect(screen.getByText('5')).toBeInTheDocument();
    });

    it('should display server counts by type', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(
        <McpServerList.Stats
          total={3}
          enabledCount={2}
          totalToolsCount={5}
          serversByType={{ stdio: 1, sse: 1, http: 1, websocket: 0 }}
        />
      );
      expect(screen.getByText('stdio: 1')).toBeInTheDocument();
      expect(screen.getByText('sse: 1')).toBeInTheDocument();
      expect(screen.getByText('http: 1')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Filters Sub-Component Tests
  // ============================================================================

  describe('Filters Sub-Component', () => {
    it('should render search input', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(
        <McpServerList.Filters
          search=""
          onSearchChange={vi.fn()}
          enabledFilter="all"
          onEnabledFilterChange={vi.fn()}
          typeFilter="all"
          onTypeFilterChange={vi.fn()}
          onRefresh={vi.fn()}
        />
      );
      const searchInput = screen.getByPlaceholderText('Search servers...');
      expect(searchInput).toBeInTheDocument();
    });

    it('should call onSearchChange when typing', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      const onSearchChange = vi.fn();
      render(
        <McpServerList.Filters
          search=""
          onSearchChange={onSearchChange}
          enabledFilter="all"
          onEnabledFilterChange={vi.fn()}
          typeFilter="all"
          onTypeFilterChange={vi.fn()}
          onRefresh={vi.fn()}
        />
      );
      const searchInput = screen.getByPlaceholderText('Search servers...');
      fireEvent.change(searchInput, { target: { value: 'test' } });
      expect(onSearchChange).toHaveBeenCalledWith('test');
    });

    it('should call onRefresh when refresh button clicked', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      const onRefresh = vi.fn();
      render(
        <McpServerList.Filters
          search=""
          onSearchChange={vi.fn()}
          enabledFilter="all"
          onEnabledFilterChange={vi.fn()}
          typeFilter="all"
          onTypeFilterChange={vi.fn()}
          onRefresh={onRefresh}
        />
      );
      const refreshButton = screen.getByLabelText('refresh');
      fireEvent.click(refreshButton);
      expect(onRefresh).toHaveBeenCalledTimes(1);
    });
  });

  // ============================================================================
  // TypeBadge Sub-Component Tests
  // ============================================================================

  describe('TypeBadge Sub-Component', () => {
    it('should render STDIO type badge', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.TypeBadge type="stdio" />);
      expect(screen.getByText('STDIO')).toBeInTheDocument();
    });

    it('should render SSE type badge', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.TypeBadge type="sse" />);
      expect(screen.getByText('SSE')).toBeInTheDocument();
    });

    it('should render HTTP type badge', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.TypeBadge type="http" />);
      expect(screen.getByText('HTTP')).toBeInTheDocument();
    });

    it('should render WEBSOCKET type badge', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.TypeBadge type="websocket" />);
      expect(screen.getByText('WEBSOCKET')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Card Sub-Component Tests
  // ============================================================================

  describe('Card Sub-Component', () => {
    const defaultProps = {
      server: mockServers[0],
      syncingServers: new Set(),
      testingServers: new Set(),
      onToggle: vi.fn(),
      onSync: vi.fn(),
      onTest: vi.fn(),
      onEdit: vi.fn(),
      onDelete: vi.fn(),
      onShowTools: vi.fn(),
      formatLastSync: vi.fn(() => '5 minutes ago'),
    };

    it('should render server name', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Card {...defaultProps} />);
      expect(screen.getByText('Test Server 1')).toBeInTheDocument();
    });

    it('should render server description', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Card {...defaultProps} />);
      expect(screen.getByText('Test description')).toBeInTheDocument();
    });

    it('should render type badge', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Card {...defaultProps} />);
      expect(screen.getByText('STDIO')).toBeInTheDocument();
    });

    it('should render switch toggle', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Card {...defaultProps} />);
      const switchElement = document.querySelector('.ant-switch');
      expect(switchElement).toBeInTheDocument();
    });

    it('should render transport config', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Card {...defaultProps} />);
      expect(screen.getByText('node test.js')).toBeInTheDocument();
    });

    it('should render tool previews', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Card {...defaultProps} />);
      expect(screen.getByText('tool1')).toBeInTheDocument();
      expect(screen.getByText('tool2')).toBeInTheDocument();
      expect(screen.getByText('tool3')).toBeInTheDocument();
    });

    it('should show "more" button when tools exceed 3', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Card {...defaultProps} />);
      expect(screen.getByText('+1 more')).toBeInTheDocument();
    });

    it('should call onShowTools when more button clicked', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      const onShowTools = vi.fn();
      render(<McpServerList.Card {...{ ...defaultProps, onShowTools }} />);
      fireEvent.click(screen.getByText('+1 more'));
      expect(onShowTools).toHaveBeenCalledWith(mockServers[0]);
    });

    it('should call onToggle when switch changed', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      const onToggle = vi.fn();
      render(<McpServerList.Card {...{ ...defaultProps, onToggle }} />);
      const switchElement = document.querySelector('.ant-switch');
      if (switchElement) {
        fireEvent.click(switchElement);
        expect(onToggle).toHaveBeenCalled();
      }
    });

    it('should render sync button', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Card {...defaultProps} />);
      const syncButton = screen.getByLabelText('sync');
      expect(syncButton).toBeInTheDocument();
    });

    it('should call onSync when sync button clicked', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      const onSync = vi.fn();
      render(<McpServerList.Card {...{ ...defaultProps, onSync }} />);
      fireEvent.click(screen.getByLabelText('sync'));
      expect(onSync).toHaveBeenCalledWith(mockServers[0]);
    });

    it('should render test button', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Card {...defaultProps} />);
      const testButton = screen.getByLabelText('test');
      expect(testButton).toBeInTheDocument();
    });

    it('should call onTest when test button clicked', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      const onTest = vi.fn();
      render(<McpServerList.Card {...{ ...defaultProps, onTest }} />);
      fireEvent.click(screen.getByLabelText('test'));
      expect(onTest).toHaveBeenCalledWith(mockServers[0]);
    });

    it('should render edit button', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Card {...defaultProps} />);
      const editButton = screen.getByLabelText('edit');
      expect(editButton).toBeInTheDocument();
    });

    it('should call onEdit when edit button clicked', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      const onEdit = vi.fn();
      render(<McpServerList.Card {...{ ...defaultProps, onEdit }} />);
      fireEvent.click(screen.getByLabelText('edit'));
      expect(onEdit).toHaveBeenCalledWith(mockServers[0]);
    });

    it('should render delete button', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Card {...defaultProps} />);
      const deleteButton = screen.getByLabelText('delete');
      expect(deleteButton).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Grid Sub-Component Tests
  // ============================================================================

  describe('Grid Sub-Component', () => {
    it('should render all server cards', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(
        <McpServerList.Grid
          servers={mockServers}
          syncingServers={new Set()}
          testingServers={new Set()}
          onToggle={vi.fn()}
          onSync={vi.fn()}
          onTest={vi.fn()}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
          onShowTools={vi.fn()}
          formatLastSync={() => '5 minutes ago'}
        />
      );
      expect(screen.getByText('Test Server 1')).toBeInTheDocument();
      expect(screen.getByText('Test Server 2')).toBeInTheDocument();
      expect(screen.getByText('HTTP Server')).toBeInTheDocument();
    });

    it('should render empty state when no servers', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(
        <McpServerList.Grid
          servers={[]}
          syncingServers={new Set()}
          testingServers={new Set()}
          onToggle={vi.fn()}
          onSync={vi.fn()}
          onTest={vi.fn()}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
          onShowTools={vi.fn()}
          formatLastSync={() => ''}
        />
      );
      expect(screen.queryByText('Test Server 1')).not.toBeInTheDocument();
    });
  });

  // ============================================================================
  // ToolsModal Sub-Component Tests
  // ============================================================================

  describe('ToolsModal Sub-Component', () => {
    it('should render modal with server name', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.ToolsModal server={mockServers[0]} onClose={vi.fn()} />);
      expect(screen.getByText((content) => content.includes('Test Server 1'))).toBeInTheDocument();
    });

    it('should render all tools', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.ToolsModal server={mockServers[0]} onClose={vi.fn()} />);
      expect(screen.getByText('tool1')).toBeInTheDocument();
      expect(screen.getByText('tool2')).toBeInTheDocument();
      expect(screen.getByText('tool3')).toBeInTheDocument();
      expect(screen.getByText('tool4')).toBeInTheDocument();
    });

    it('should render tool descriptions', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.ToolsModal server={mockServers[0]} onClose={vi.fn()} />);
      expect(screen.getByText('Test tool 1')).toBeInTheDocument();
      expect(screen.getByText('Test tool 2')).toBeInTheDocument();
    });

    it('should call onClose when close button clicked', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      const onClose = vi.fn();
      render(<McpServerList.ToolsModal server={mockServers[0]} onClose={onClose} />);
      const closeButton = screen.getByLabelText('close');
      fireEvent.click(closeButton);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  // ============================================================================
  // Loading Sub-Component Tests
  // ============================================================================

  describe('Loading Sub-Component', () => {
    it('should render loading spinner', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Loading />);
      const loadingElement = document.querySelector('.ant-spin');
      expect(loadingElement).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Empty Sub-Component Tests
  // ============================================================================

  describe('Empty Sub-Component', () => {
    it('should render empty state message', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList.Empty />);
      expect(screen.getByText(/No MCP servers configured/)).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Integration Tests
  // ============================================================================

  describe('Integration', () => {
    it('should filter servers by search text', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList />);
      const searchInput = screen.getByPlaceholderText('Search servers...');
      fireEvent.change(searchInput, { target: { value: 'HTTP' } });
      await waitFor(() => {
        expect(screen.getByText('HTTP Server')).toBeInTheDocument();
        expect(screen.queryByText('Test Server 1')).not.toBeInTheDocument();
      });
    });

    it('should open modal when create button clicked', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      render(<McpServerList />);
      fireEvent.click(screen.getByText('Create Server'));
      expect(screen.getByTestId('mcp-server-modal')).toBeInTheDocument();
    });

    it('should handle sync operation', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      mockStoreState.syncServer.mockResolvedValueOnce(undefined);
      render(<McpServerList />);
      const syncButton = screen.getAllByLabelText('sync')[0];
      fireEvent.click(syncButton);
      await waitFor(() => {
        expect(mockStoreState.syncServer).toHaveBeenCalledWith('1', 'test-project-1');
      });
    });

    it('should handle delete operation', async () => {
      const { McpServerList } = await import('../../../pages/tenant/McpServerList');
      mockStoreState.deleteServer.mockResolvedValueOnce(undefined);
      render(<McpServerList />);
      const deleteButton = screen.getAllByLabelText('delete')[0];
      fireEvent.click(deleteButton);
      const confirmButton = screen.getByText('Confirm');
      fireEvent.click(confirmButton);
      await waitFor(() => {
        expect(mockStoreState.deleteServer).toHaveBeenCalled();
      });
    });
  });
});
