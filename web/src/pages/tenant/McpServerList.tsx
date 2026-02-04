/**
 * McpServerList Page
 *
 * Management page for MCP (Model Context Protocol) servers with CRUD operations,
 * tool sync, connection testing, and filtering functionality.
 *
 * Compound component pattern with sub-components:
 * - Header: Page header with create button
 * - Stats: Statistics cards showing server counts
 * - Filters: Search and filter controls
 * - Grid: Grid of server cards
 * - Card: Individual server card
 * - TypeBadge: Server type badge
 * - ToolsModal: Modal showing server tools
 * - Loading: Loading state
 * - Empty: Empty state
 * - Modal: Server create/edit modal
 */

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useRef,
} from 'react';
import {
  message,
  Popconfirm,
  Select,
  Empty,
  Spin,
  Input,
  Switch,
  Tooltip,
} from 'antd';
import { useMCPStore } from '../../stores/mcp';
import { McpServerModal } from '../../components/mcp/McpServerModal';
import type {
  MCPServerResponse,
  MCPServerType,
  MCPToolInfo,
} from '../../types/agent';
import type {
  McpServerListHeaderProps,
  McpServerListStatsProps,
  McpServerListStatsCardProps,
  McpServerListFiltersProps,
  McpServerCardProps,
  ServerTypeBadgeProps,
  ToolsModalProps,
  McpServerListLoadingProps,
  McpServerListEmptyProps,
  McpServerListGridProps,
  McpServerListModalProps,
  McpServerListProps,
} from './McpServerList/types';

const { Search } = Input;

// ============================================================================
// Constants
// ============================================================================

const TEXTS = {
  title: 'MCP Servers',
  subtitle: 'Manage your Model Context Protocol servers',
  createNew: 'Create Server',

  // Stats
  stats: {
    total: 'Total Servers',
    enabled: 'Enabled',
    totalTools: 'Total Tools',
    byType: 'By Type',
  },

  // Filters
  searchPlaceholder: 'Search servers...',
  allTypes: 'All Types',
  all: 'All',
  enabled: 'Enabled',
  disabled: 'Disabled',

  // Server card
  config: 'Config',
  tools: 'Tools',
  lastSync: 'Last Sync',
  neverSynced: 'Never',
  justNow: 'Just now',
  minutesAgo: '{{count}} min ago',
  hoursAgo: '{{count}}h ago',
  daysAgo: '{{count}}d ago',

  // Actions
  actions: {
    sync: 'Sync',
    test: 'Test',
  },

  // Modals
  deleteConfirm: 'Are you sure you want to delete this server?',
  confirm: 'Confirm',
  cancel: 'Cancel',
  empty: 'No MCP servers configured. Create your first server to get started.',

  // Messages
  enabledSuccess: 'Server enabled',
  disabledSuccess: 'Server disabled',
  syncSuccess: 'Server synced successfully',
  testSuccess: 'Connection successful',
  testFailed: 'Connection failed',
  deleteSuccess: 'Server deleted',
} as const;

// Server type badge colors
const SERVER_TYPE_COLORS: Record<MCPServerType, { bg: string; text: string }> = {
  stdio: {
    bg: 'bg-blue-100 dark:bg-blue-900/30',
    text: 'text-blue-800 dark:text-blue-300',
  },
  sse: {
    bg: 'bg-green-100 dark:bg-green-900/30',
    text: 'text-green-800 dark:text-green-300',
  },
  http: {
    bg: 'bg-purple-100 dark:bg-purple-900/30',
    text: 'text-purple-800 dark:text-purple-300',
  },
  websocket: {
    bg: 'bg-orange-100 dark:bg-orange-900/30',
    text: 'text-orange-800 dark:text-orange-300',
  },
};

// Helper function for template formatting
function formatTemplate(template: string, values: Record<string, string | number>): string {
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replace(`{{${key}}}`, String(value)),
    template
  );
}

// ============================================================================
// Sub-Components
// ============================================================================

// Header Sub-Component
const Header: React.FC<McpServerListHeaderProps> = ({ onCreate }) => (
  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
    <div>
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
        {TEXTS.title}
      </h1>
      <p className="text-sm text-slate-500 mt-1">
        {TEXTS.subtitle}
      </p>
    </div>
    <button
      onClick={onCreate}
      className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
    >
      <span className="material-symbols-outlined text-lg">add</span>
      {TEXTS.createNew}
    </button>
  </div>
);
Header.displayName = 'McpServerList.Header';

// Stats Card Component
const StatsCard: React.FC<McpServerListStatsCardProps> = ({
  title,
  value,
  icon,
  iconColor = 'text-primary-500',
  valueColor = 'text-slate-900 dark:text-white',
  extra,
}) => (
  <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm text-slate-600 dark:text-slate-400">{title}</p>
        <p className={`text-2xl font-bold ${valueColor} mt-1`}>
          {value}
        </p>
        {extra && <div className="mt-1">{extra}</div>}
      </div>
      <span className={`material-symbols-outlined text-4xl ${iconColor}`}>
        {icon}
      </span>
    </div>
  </div>
);
StatsCard.displayName = 'McpServerList.StatsCard';

// Stats Sub-Component
const Stats: React.FC<McpServerListStatsProps> = ({
  total,
  enabledCount,
  totalToolsCount,
  serversByType,
}) => (
  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
    <StatsCard
      title={TEXTS.stats.total}
      value={total}
      icon="dns"
      iconColor="text-primary-500"
    />
    <StatsCard
      title={TEXTS.stats.enabled}
      value={enabledCount}
      icon="check_circle"
      iconColor="text-green-500"
      valueColor="text-green-600 dark:text-green-400"
    />
    <StatsCard
      title={TEXTS.stats.totalTools}
      value={totalToolsCount}
      icon="build"
      iconColor="text-blue-500"
      valueColor="text-blue-600 dark:text-blue-400"
    />
    <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {TEXTS.stats.byType}
          </p>
          <div className="flex gap-2 mt-1">
            {Object.entries(serversByType).map(
              ([type, count]) =>
                count > 0 && (
                  <span
                    key={type}
                    className="text-xs text-slate-600 dark:text-slate-400"
                  >
                    {type}: {count}
                  </span>
                )
            )}
          </div>
        </div>
        <span className="material-symbols-outlined text-4xl text-purple-500">
          category
        </span>
      </div>
    </div>
  </div>
);
Stats.displayName = 'McpServerList.Stats';

// Filters Sub-Component
const Filters: React.FC<McpServerListFiltersProps> = ({
  search,
  onSearchChange,
  enabledFilter,
  onEnabledFilterChange,
  typeFilter,
  onTypeFilterChange,
  onRefresh,
}) => (
  <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
    <div className="flex flex-col sm:flex-row gap-4">
      <div className="flex-1">
        <Search
          placeholder={TEXTS.searchPlaceholder}
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          allowClear
        />
      </div>
      <Select
        value={enabledFilter}
        onChange={onEnabledFilterChange}
        className="w-full sm:w-40"
        options={[
          { label: TEXTS.all, value: 'all' },
          { label: TEXTS.enabled, value: 'enabled' },
          { label: TEXTS.disabled, value: 'disabled' },
        ]}
      />
      <Select
        value={typeFilter}
        onChange={onTypeFilterChange}
        className="w-full sm:w-40"
        options={[
          { label: TEXTS.allTypes, value: 'all' },
          { label: 'STDIO', value: 'stdio' },
          { label: 'SSE', value: 'sse' },
          { label: 'HTTP', value: 'http' },
          { label: 'WebSocket', value: 'websocket' },
        ]}
      />
      <button
        onClick={onRefresh}
        className="inline-flex items-center justify-center px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700"
        aria-label="refresh"
      >
        <span className="material-symbols-outlined">refresh</span>
      </button>
    </div>
  </div>
);
Filters.displayName = 'McpServerList.Filters';

// TypeBadge Sub-Component
const TypeBadge: React.FC<ServerTypeBadgeProps> = ({ type }) => {
  const { bg, text } = SERVER_TYPE_COLORS[type];
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${bg} ${text}`}
    >
      {type.toUpperCase()}
    </span>
  );
};
TypeBadge.displayName = 'McpServerList.TypeBadge';

// Card Sub-Component
const Card: React.FC<McpServerCardProps> = React.memo(({
  server,
  syncingServers,
  testingServers,
  onToggle,
  onSync,
  onTest,
  onEdit,
  onDelete,
  onShowTools,
  formatLastSync,
}) => {
  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700 hover:shadow-lg transition-shadow">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
              {server.name}
            </h3>
            <TypeBadge type={server.server_type} />
          </div>
        </div>
        <Switch
          checked={server.enabled}
          onChange={(checked) => onToggle(server, checked)}
          size="small"
        />
      </div>

      {/* Description */}
      {server.description && (
        <p className="text-sm text-slate-600 dark:text-slate-400 mb-4 line-clamp-2">
          {server.description}
        </p>
      )}

      {/* Transport Config Preview */}
      <div className="mb-4">
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">
          {TEXTS.config}:
        </p>
        <code className="text-xs text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-700 px-2 py-1 rounded block truncate">
          {server.server_type === 'stdio'
            ? (server.transport_config as { command?: string })?.command || 'N/A'
            : (server.transport_config as { url?: string })?.url || 'N/A'}
        </code>
      </div>

      {/* Tools Preview */}
      <div className="mb-4">
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
          {TEXTS.tools} ({server.discovered_tools?.length || 0})
        </p>
        <div className="flex flex-wrap gap-1">
          {server.discovered_tools?.slice(0, 3).map((tool: MCPToolInfo, idx: number) => (
            <Tooltip key={idx} title={tool.description}>
              <span className="inline-flex px-2 py-0.5 bg-slate-100 dark:bg-slate-700 text-xs text-slate-700 dark:text-slate-300 rounded">
                {tool.name}
              </span>
            </Tooltip>
          ))}
          {(server.discovered_tools?.length || 0) > 3 && (
            <button
              onClick={() => onShowTools(server)}
              className="inline-flex px-2 py-0.5 bg-primary-100 dark:bg-primary-900/30 text-xs text-primary-700 dark:text-primary-300 rounded hover:bg-primary-200 dark:hover:bg-primary-900/50"
            >
              +{server.discovered_tools.length - 3} more
            </button>
          )}
        </div>
      </div>

      {/* Last Sync */}
      <div className="mb-4">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {TEXTS.lastSync}: {formatLastSync(server.last_sync_at)}
        </p>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-4 border-t border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-2">
          <Tooltip title={TEXTS.actions.sync}>
            <button
              onClick={() => onSync(server)}
              disabled={syncingServers.has(server.id)}
              className="inline-flex items-center justify-center px-3 py-1.5 text-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50"
              aria-label="sync"
            >
              {syncingServers.has(server.id) ? (
                <Spin size="small" />
              ) : (
                <span className="material-symbols-outlined text-sm">sync</span>
              )}
              <span className="ml-1">{TEXTS.actions.sync}</span>
            </button>
          </Tooltip>
          <Tooltip title={TEXTS.actions.test}>
            <button
              onClick={() => onTest(server)}
              disabled={testingServers.has(server.id)}
              className="inline-flex items-center justify-center px-3 py-1.5 text-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50"
              aria-label="test"
            >
              {testingServers.has(server.id) ? (
                <Spin size="small" />
              ) : (
                <span className="material-symbols-outlined text-sm">speed</span>
              )}
            </button>
          </Tooltip>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onEdit(server)}
            className="p-2 text-slate-600 dark:text-slate-400 hover:text-primary-600 dark:hover:text-primary-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
            aria-label="edit"
          >
            <span className="material-symbols-outlined text-lg">edit</span>
          </button>
          <Popconfirm
            title={TEXTS.deleteConfirm}
            onConfirm={() => onDelete(server.id)}
            okText={TEXTS.confirm}
            cancelText={TEXTS.cancel}
          >
            <button
              className="p-2 text-slate-600 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
              aria-label="delete"
            >
              <span className="material-symbols-outlined text-lg">delete</span>
            </button>
          </Popconfirm>
        </div>
      </div>
    </div>
  );
});
Card.displayName = 'McpServerList.Card';

// Grid Sub-Component
const Grid: React.FC<McpServerListGridProps> = React.memo(({
  servers,
  syncingServers,
  testingServers,
  onToggle,
  onSync,
  onTest,
  onEdit,
  onDelete,
  onShowTools,
  formatLastSync,
}) => {
  if (servers.length === 0) {
    return null;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
      {servers.map((server) => (
        <Card
          key={server.id}
          server={server}
          syncingServers={syncingServers}
          testingServers={testingServers}
          onToggle={onToggle}
          onSync={onSync}
          onTest={onTest}
          onEdit={onEdit}
          onDelete={onDelete}
          onShowTools={onShowTools}
          formatLastSync={formatLastSync}
        />
      ))}
    </div>
  );
});
Grid.displayName = 'McpServerList.Grid';

// ToolsModal Sub-Component
const ToolsModal: React.FC<ToolsModalProps> = ({ server, onClose }) => {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-lg p-6 w-full max-w-lg max-h-[80vh] overflow-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
            {server.name} - {TEXTS.tools}
          </h3>
          <button
            onClick={onClose}
            className="p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded"
            aria-label="close"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>
        <div className="space-y-3">
          {server.discovered_tools?.map((tool: MCPToolInfo, idx: number) => (
            <div
              key={idx}
              className="p-3 bg-slate-50 dark:bg-slate-700/50 rounded-lg"
            >
              <p className="font-medium text-slate-900 dark:text-white">
                {tool.name}
              </p>
              {tool.description && (
                <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
                  {tool.description}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
ToolsModal.displayName = 'McpServerList.ToolsModal';

// Loading Sub-Component
const Loading: React.FC<McpServerListLoadingProps> = () => (
  <div className="flex justify-center py-12">
    <Spin size="large" />
  </div>
);
Loading.displayName = 'McpServerList.Loading';

// Empty Sub-Component
const EmptyState: React.FC<McpServerListEmptyProps> = () => (
  <Empty description={TEXTS.empty} className="py-12" />
);
EmptyState.displayName = 'McpServerList.Empty';

// Modal Sub-Component
const Modal: React.FC<McpServerListModalProps> = ({
  isOpen,
  server,
  onClose,
  onSuccess,
}) => {
  if (!isOpen) return null;
  return (
    <McpServerModal
      isOpen={isOpen}
      server={server}
      onClose={onClose}
      onSuccess={onSuccess}
    />
  );
};
Modal.displayName = 'McpServerList.Modal';

// ============================================================================
// Main Component
// ============================================================================

export const McpServerList: React.FC<McpServerListProps> & {
  Header: typeof Header;
  Stats: typeof Stats;
  Filters: typeof Filters;
  Grid: typeof Grid;
  Card: typeof Card;
  TypeBadge: typeof TypeBadge;
  ToolsModal: typeof ToolsModal;
  Loading: typeof Loading;
  Empty: typeof EmptyState;
  Modal: typeof Modal;
} = ({ className = '' }) => {
  const [search, setSearch] = useState('');
  const [enabledFilter, setEnabledFilter] = useState<'all' | 'enabled' | 'disabled'>('all');
  const [typeFilter, setTypeFilter] = useState<'all' | MCPServerType>('all');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<MCPServerResponse | null>(null);
  const [toolsModalServer, setToolsModalServer] = useState<MCPServerResponse | null>(null);

  // Store state
  const servers = useMCPStore((state) => state.servers);
  const syncingServers = useMCPStore((state) => state.syncingServers);
  const testingServers = useMCPStore((state) => state.testingServers);
  const isLoading = useMCPStore((state) => state.isLoading);
  const error = useMCPStore((state) => state.error);

  // Store actions
  const listServers = useMCPStore((state) => state.listServers);
  const deleteServer = useMCPStore((state) => state.deleteServer);
  const toggleEnabled = useMCPStore((state) => state.toggleEnabled);
  const syncServer = useMCPStore((state) => state.syncServer);
  const testServer = useMCPStore((state) => state.testServer);
  const clearError = useMCPStore((state) => state.clearError);

  // Track if initial load has been done
  const hasLoadedRef = useRef(false);

  // Computed values
  const enabledCount = useMemo(
    () => servers.filter((s) => s.enabled).length,
    [servers]
  );
  const totalToolsCount = useMemo(
    () => servers.reduce((sum, s) => sum + (s.discovered_tools?.length || 0), 0),
    [servers]
  );
  const total = servers.length;
  const serversByType = useMemo(() => {
    const result: Record<MCPServerType, number> = {
      stdio: 0,
      sse: 0,
      http: 0,
      websocket: 0,
    };
    servers.forEach((s) => {
      result[s.server_type]++;
    });
    return result;
  }, [servers]);

  // Filter servers
  const filteredServers = useMemo(() => {
    return servers.filter((server) => {
      if (search) {
        const searchLower = search.toLowerCase();
        const matchesName = server.name.toLowerCase().includes(searchLower);
        const matchesDescription = server.description?.toLowerCase().includes(searchLower);
        if (!matchesName && !matchesDescription) {
          return false;
        }
      }
      if (enabledFilter === 'enabled' && !server.enabled) return false;
      if (enabledFilter === 'disabled' && server.enabled) return false;
      if (typeFilter !== 'all' && server.server_type !== typeFilter) {
        return false;
      }
      return true;
    });
  }, [servers, search, enabledFilter, typeFilter]);

  // Load data on mount
  useEffect(() => {
    if (!hasLoadedRef.current) {
      hasLoadedRef.current = true;
      listServers();
    }
  }, [listServers]);

  // Clear error on unmount
  useEffect(() => {
    return () => clearError();
  }, [clearError]);

  // Show error message
  useEffect(() => {
    if (error) {
      message.error(error);
    }
  }, [error]);

  // Handlers
  const handleCreate = useCallback(() => {
    setEditingServer(null);
    setIsModalOpen(true);
  }, []);

  const handleEdit = useCallback((server: MCPServerResponse) => {
    setEditingServer(server);
    setIsModalOpen(true);
  }, []);

  const handleToggleEnabled = useCallback(
    async (server: MCPServerResponse, enabled: boolean) => {
      try {
        await toggleEnabled(server.id, enabled);
        message.success(enabled ? TEXTS.enabledSuccess : TEXTS.disabledSuccess);
      } catch {
        // Error handled by store
      }
    },
    [toggleEnabled]
  );

  const handleSync = useCallback(
    async (server: MCPServerResponse) => {
      try {
        await syncServer(server.id);
        message.success(TEXTS.syncSuccess);
      } catch {
        // Error handled by store
      }
    },
    [syncServer]
  );

  const handleTest = useCallback(
    async (server: MCPServerResponse) => {
      try {
        const result = await testServer(server.id);
        if (result.success) {
          message.success(`${TEXTS.testSuccess} (${result.latency_ms}ms)`);
        } else {
          message.error(`${TEXTS.testFailed}: ${result.message}`);
        }
      } catch {
        // Error handled by store
      }
    },
    [testServer]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteServer(id);
        message.success(TEXTS.deleteSuccess);
      } catch {
        // Error handled by store
      }
    },
    [deleteServer]
  );

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
    setEditingServer(null);
  }, []);

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    setEditingServer(null);
    listServers();
  }, [listServers]);

  const handleRefresh = useCallback(() => {
    listServers();
  }, [listServers]);

  const handleShowTools = useCallback((server: MCPServerResponse) => {
    setToolsModalServer(server);
  }, []);

  const handleCloseToolsModal = useCallback(() => {
    setToolsModalServer(null);
  }, []);

  const formatLastSync = useCallback((dateStr?: string) => {
    if (!dateStr) return TEXTS.neverSynced;
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return TEXTS.justNow;
    if (diffMins < 60) return formatTemplate(TEXTS.minutesAgo, { count: diffMins });
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return formatTemplate(TEXTS.hoursAgo, { count: diffHours });
    const diffDays = Math.floor(diffHours / 24);
    return formatTemplate(TEXTS.daysAgo, { count: diffDays });
  }, []);

  return (
    <div className={`max-w-full mx-auto w-full flex flex-col gap-8 ${className}`}>
      <Header onCreate={handleCreate} />
      <Stats
        total={total}
        enabledCount={enabledCount}
        totalToolsCount={totalToolsCount}
        serversByType={serversByType}
      />
      <Filters
        search={search}
        onSearchChange={setSearch}
        enabledFilter={enabledFilter}
        onEnabledFilterChange={setEnabledFilter}
        typeFilter={typeFilter}
        onTypeFilterChange={setTypeFilter}
        onRefresh={handleRefresh}
      />
      {isLoading ? (
        <Loading />
      ) : servers.length === 0 ? (
        <EmptyState />
      ) : (
        <Grid
          servers={filteredServers}
          syncingServers={syncingServers}
          testingServers={testingServers}
          onToggle={handleToggleEnabled}
          onSync={handleSync}
          onTest={handleTest}
          onEdit={handleEdit}
          onDelete={handleDelete}
          onShowTools={handleShowTools}
          formatLastSync={formatLastSync}
        />
      )}
      <Modal
        isOpen={isModalOpen}
        server={editingServer}
        onClose={handleModalClose}
        onSuccess={handleModalSuccess}
      />
      {toolsModalServer && (
        <ToolsModal server={toolsModalServer} onClose={handleCloseToolsModal} />
      )}
    </div>
  );
};

McpServerList.displayName = 'McpServerList';

// Attach sub-components
McpServerList.Header = Header;
McpServerList.Stats = Stats;
McpServerList.Filters = Filters;
McpServerList.Grid = Grid;
McpServerList.Card = Card;
McpServerList.TypeBadge = TypeBadge;
McpServerList.ToolsModal = ToolsModal;
McpServerList.Loading = Loading;
McpServerList.Empty = EmptyState;
McpServerList.Modal = Modal;

export default McpServerList;
