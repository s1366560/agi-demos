/**
 * MCP Server List Page
 *
 * Management page for MCP (Model Context Protocol) servers with CRUD operations,
 * tool sync, connection testing, and filtering functionality.
 *
 * Performance optimizations:
 * - React.memo on ServerTypeBadge, StatsCard, McpServerCard, ToolsModal
 * - useCallback for all event handlers
 * - useMemo for computed values (filtered servers, counts)
 */

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useRef,
} from "react";
import { useTranslation } from "react-i18next";
import {
  message,
  Popconfirm,
  Select,
  Empty,
  Spin,
  Input,
  Switch,
  Tooltip,
} from "antd";
import { useMCPStore } from "../../stores/mcp";
import { McpServerModal } from "../../components/mcp/McpServerModal";
import type {
  MCPServerResponse,
  MCPServerType,
  MCPToolInfo,
} from "../../types/agent";

const { Search } = Input;

// Server type badge colors
const SERVER_TYPE_COLORS: Record<MCPServerType, { bg: string; text: string }> =
  {
    stdio: {
      bg: "bg-blue-100 dark:bg-blue-900/30",
      text: "text-blue-800 dark:text-blue-300",
    },
    sse: {
      bg: "bg-green-100 dark:bg-green-900/30",
      text: "text-green-800 dark:text-green-300",
    },
    http: {
      bg: "bg-purple-100 dark:bg-purple-900/30",
      text: "text-purple-800 dark:text-purple-300",
    },
    websocket: {
      bg: "bg-orange-100 dark:bg-orange-900/30",
      text: "text-orange-800 dark:text-orange-300",
    },
  };

// Server Type Badge - Memoized component
const ServerTypeBadge = React.memo(({ type }: { type: MCPServerType }) => {
  const { bg, text } = SERVER_TYPE_COLORS[type];
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${bg} ${text}`}
    >
      {type.toUpperCase()}
    </span>
  );
});
ServerTypeBadge.displayName = "ServerTypeBadge";

// Stats Card - Memoized component
interface StatsCardProps {
  title: string;
  value: string | number;
  icon: string;
  iconColor?: string;
  valueColor?: string;
  extra?: React.ReactNode;
}

const StatsCard = React.memo<StatsCardProps>(({
  title,
  value,
  icon,
  iconColor = "text-primary-500",
  valueColor = "text-slate-900 dark:text-white",
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
));
StatsCard.displayName = "StatsCard";

// MCP Server Card - Memoized component
interface McpServerCardProps {
  server: MCPServerResponse;
  syncingServers: Set<string>;
  testingServers: Set<string>;
  onToggle: (server: MCPServerResponse, enabled: boolean) => void;
  onSync: (server: MCPServerResponse) => void;
  onTest: (server: MCPServerResponse) => void;
  onEdit: (server: MCPServerResponse) => void;
  onDelete: (id: string) => void;
  onShowTools: (server: MCPServerResponse) => void;
  formatLastSync: (dateStr?: string) => string;
}

const McpServerCard = React.memo<McpServerCardProps>(({
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
  const { t } = useTranslation();

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700 hover:shadow-lg transition-shadow">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
              {server.name}
            </h3>
            <ServerTypeBadge type={server.server_type} />
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
          {t("tenant.mcpServers.config")}:
        </p>
        <code className="text-xs text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-700 px-2 py-1 rounded block truncate">
          {server.server_type === "stdio"
            ? (server.transport_config as { command?: string })
                ?.command || "N/A"
            : (server.transport_config as { url?: string })?.url ||
              "N/A"}
        </code>
      </div>

      {/* Tools Preview */}
      <div className="mb-4">
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
          {t("tenant.mcpServers.tools")} (
          {server.discovered_tools?.length || 0})
        </p>
        <div className="flex flex-wrap gap-1">
          {server.discovered_tools
            ?.slice(0, 3)
            .map((tool: MCPToolInfo, idx: number) => (
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
          {t("tenant.mcpServers.lastSync")}:{" "}
          {formatLastSync(server.last_sync_at)}
        </p>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-4 border-t border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-2">
          <Tooltip title={t("tenant.mcpServers.actions.sync")}>
            <button
              onClick={() => onSync(server)}
              disabled={syncingServers.has(server.id)}
              className="inline-flex items-center justify-center px-3 py-1.5 text-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50"
            >
              {syncingServers.has(server.id) ? (
                <Spin size="small" />
              ) : (
                <span className="material-symbols-outlined text-sm">
                  sync
                </span>
              )}
              <span className="ml-1">
                {t("tenant.mcpServers.actions.sync")}
              </span>
            </button>
          </Tooltip>
          <Tooltip title={t("tenant.mcpServers.actions.test")}>
            <button
              onClick={() => onTest(server)}
              disabled={testingServers.has(server.id)}
              className="inline-flex items-center justify-center px-3 py-1.5 text-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50"
            >
              {testingServers.has(server.id) ? (
                <Spin size="small" />
              ) : (
                <span className="material-symbols-outlined text-sm">
                  speed
                </span>
              )}
            </button>
          </Tooltip>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onEdit(server)}
            className="p-2 text-slate-600 dark:text-slate-400 hover:text-primary-600 dark:hover:text-primary-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
          >
            <span className="material-symbols-outlined text-lg">
              edit
            </span>
          </button>
          <Popconfirm
            title={t("tenant.mcpServers.deleteConfirm")}
            onConfirm={() => onDelete(server.id)}
            okText={t("common.confirm")}
            cancelText={t("common.cancel")}
          >
            <button className="p-2 text-slate-600 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700">
              <span className="material-symbols-outlined text-lg">
                delete
              </span>
            </button>
          </Popconfirm>
        </div>
      </div>
    </div>
  );
});
McpServerCard.displayName = "McpServerCard";

// Tools Modal - Memoized component
interface ToolsModalProps {
  server: MCPServerResponse;
  onClose: () => void;
}

const ToolsModal = React.memo<ToolsModalProps>(({ server, onClose }) => {
  const { t } = useTranslation();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-lg p-6 w-full max-w-lg max-h-[80vh] overflow-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
            {server.name} - {t("tenant.mcpServers.tools")}
          </h3>
          <button
            onClick={onClose}
            className="p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>
        <div className="space-y-3">
          {server.discovered_tools?.map(
            (tool: MCPToolInfo, idx: number) => (
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
            )
          )}
        </div>
      </div>
    </div>
  );
});
ToolsModal.displayName = "ToolsModal";

export const McpServerList: React.FC = () => {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [enabledFilter, setEnabledFilter] = useState<
    "all" | "enabled" | "disabled"
  >("all");
  const [typeFilter, setTypeFilter] = useState<"all" | MCPServerType>("all");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<MCPServerResponse | null>(
    null
  );
  const [toolsModalServer, setToolsModalServer] =
    useState<MCPServerResponse | null>(null);

  // Store state - use single subscription
  const servers = useMCPStore((state) => state.servers);
  const syncingServers = useMCPStore((state) => state.syncingServers);
  const testingServers = useMCPStore((state) => state.testingServers);
  const isLoading = useMCPStore((state) => state.isLoading);
  const error = useMCPStore((state) => state.error);

  // Computed values using useMemo to avoid infinite loops
  const enabledCount = useMemo(
    () => servers.filter((s) => s.enabled).length,
    [servers]
  );
  const totalToolsCount = useMemo(
    () =>
      servers.reduce((sum, s) => sum + (s.discovered_tools?.length || 0), 0),
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

  // Filter servers locally
  const filteredServers = useMemo(() => {
    return servers.filter((server) => {
      // Search filter
      if (search) {
        const searchLower = search.toLowerCase();
        const matchesName = server.name.toLowerCase().includes(searchLower);
        const matchesDescription = server.description
          ?.toLowerCase()
          .includes(searchLower);
        if (!matchesName && !matchesDescription) {
          return false;
        }
      }

      // Enabled filter
      if (enabledFilter === "enabled" && !server.enabled) return false;
      if (enabledFilter === "disabled" && server.enabled) return false;

      // Type filter
      if (typeFilter !== "all" && server.server_type !== typeFilter) {
        return false;
      }

      return true;
    });
  }, [servers, search, enabledFilter, typeFilter]);

  // Store actions - these are stable references from Zustand
  const listServers = useMCPStore((state) => state.listServers);
  const deleteServer = useMCPStore((state) => state.deleteServer);
  const toggleEnabled = useMCPStore((state) => state.toggleEnabled);
  const syncServer = useMCPStore((state) => state.syncServer);
  const testServer = useMCPStore((state) => state.testServer);
  const clearError = useMCPStore((state) => state.clearError);

  // Track if initial load has been done
  const hasLoadedRef = useRef(false);

  // Load data on mount only once
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
        message.success(
          enabled
            ? t("tenant.mcpServers.enabledSuccess")
            : t("tenant.mcpServers.disabledSuccess")
        );
      } catch {
        // Error handled by store
      }
    },
    [toggleEnabled, t]
  );

  const handleSync = useCallback(
    async (server: MCPServerResponse) => {
      try {
        await syncServer(server.id);
        message.success(t("tenant.mcpServers.syncSuccess"));
      } catch {
        // Error handled by store
      }
    },
    [syncServer, t]
  );

  const handleTest = useCallback(
    async (server: MCPServerResponse) => {
      try {
        const result = await testServer(server.id);
        if (result.success) {
          message.success(
            `${t("tenant.mcpServers.testSuccess")} (${result.latency_ms}ms)`
          );
        } else {
          message.error(
            `${t("tenant.mcpServers.testFailed")}: ${result.message}`
          );
        }
      } catch {
        // Error handled by store
      }
    },
    [testServer, t]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteServer(id);
        message.success(t("tenant.mcpServers.deleteSuccess"));
      } catch {
        // Error handled by store
      }
    },
    [deleteServer, t]
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

  // Format last sync time
  const formatLastSync = useCallback((dateStr?: string) => {
    if (!dateStr) return t("tenant.mcpServers.neverSynced");
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return t("tenant.mcpServers.justNow");
    if (diffMins < 60)
      return t("tenant.mcpServers.minutesAgo", { count: diffMins });
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24)
      return t("tenant.mcpServers.hoursAgo", { count: diffHours });
    const diffDays = Math.floor(diffHours / 24);
    return t("tenant.mcpServers.daysAgo", { count: diffDays });
  }, [t]);

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t("tenant.mcpServers.title")}
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            {t("tenant.mcpServers.subtitle")}
          </p>
        </div>
        <button
          onClick={handleCreate}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
        >
          <span className="material-symbols-outlined text-lg">add</span>
          {t("tenant.mcpServers.createNew")}
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatsCard
          title={t("tenant.mcpServers.stats.total")}
          value={total}
          icon="dns"
          iconColor="text-primary-500"
        />
        <StatsCard
          title={t("tenant.mcpServers.stats.enabled")}
          value={enabledCount}
          icon="check_circle"
          iconColor="text-green-500"
          valueColor="text-green-600 dark:text-green-400"
        />
        <StatsCard
          title={t("tenant.mcpServers.stats.totalTools")}
          value={totalToolsCount}
          icon="build"
          iconColor="text-blue-500"
          valueColor="text-blue-600 dark:text-blue-400"
        />
        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t("tenant.mcpServers.stats.byType")}
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

      {/* Filters */}
      <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <Search
              placeholder={t("tenant.mcpServers.searchPlaceholder")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              allowClear
            />
          </div>
          <Select
            value={enabledFilter}
            onChange={setEnabledFilter}
            className="w-full sm:w-40"
            options={[
              { label: t("common.status.all"), value: "all" },
              {
                label: t("tenant.mcpServers.filters.enabled"),
                value: "enabled",
              },
              {
                label: t("tenant.mcpServers.filters.disabled"),
                value: "disabled",
              },
            ]}
          />
          <Select
            value={typeFilter}
            onChange={setTypeFilter}
            className="w-full sm:w-40"
            options={[
              { label: t("tenant.mcpServers.allTypes"), value: "all" },
              { label: "STDIO", value: "stdio" },
              { label: "SSE", value: "sse" },
              { label: "HTTP", value: "http" },
              { label: "WebSocket", value: "websocket" },
            ]}
          />
          <button
            onClick={handleRefresh}
            className="inline-flex items-center justify-center px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700"
          >
            <span className="material-symbols-outlined">refresh</span>
          </button>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Spin size="large" />
        </div>
      ) : servers.length === 0 ? (
        <Empty description={t("tenant.mcpServers.empty")} className="py-12" />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {filteredServers.map((server) => (
            <McpServerCard
              key={server.id}
              server={server}
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
          ))}
        </div>
      )}

      {/* Server Modal */}
      {isModalOpen && (
        <McpServerModal
          isOpen={isModalOpen}
          server={editingServer}
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
        />
      )}

      {/* Tools List Modal */}
      {toolsModalServer && (
        <ToolsModal server={toolsModalServer} onClose={handleCloseToolsModal} />
      )}
    </div>
  );
};

export default McpServerList;
