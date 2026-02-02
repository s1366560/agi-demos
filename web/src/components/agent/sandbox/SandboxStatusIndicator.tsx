/**
 * SandboxStatusIndicator - Sandbox lifecycle status indicator for status bar
 *
 * Features:
 * - Click to start sandbox if not running
 * - Real-time status updates via WebSocket (replaces SSE)
 * - Hover to show detailed metrics (CPU, memory, disk, network)
 *
 * @module components/agent/sandbox/SandboxStatusIndicator
 */

import { useCallback, useEffect, useMemo, useState, type FC } from "react";
import { Popover, Spin, Progress, message, Button } from "antd";
import {
  Terminal,
  Power,
  Loader2,
  CheckCircle2,
  AlertCircle,
  PlayCircle,
  Cpu,
  HardDrive,
  Network,
  Clock,
  RefreshCw,
} from "lucide-react";
import {
  projectSandboxService,
  type ProjectSandbox,
  type SandboxStats,
  type ProjectSandboxStatus,
} from "../../../services/projectSandboxService";
import { agentService } from "../../../services/agentService";
import { type SandboxStateData } from "../../../types/agent";
import { logger } from "../../../utils/logger";

interface SandboxStatusIndicatorProps {
  /** Project ID */
  projectId: string;
  /** Tenant ID (reserved for future multi-tenant features) */
  tenantId?: string;
  /** Optional className */
  className?: string;
}

/**
 * Status configuration for different sandbox states
 */
const statusConfig: Record<
  ProjectSandboxStatus | "none",
  {
    label: string;
    icon: React.ElementType;
    color: string;
    bgColor: string;
    description: string;
    animate?: boolean;
    clickable?: boolean;
  }
> = {
  none: {
    label: "未启动",
    icon: Power,
    color: "text-slate-500",
    bgColor: "bg-slate-100 dark:bg-slate-800",
    description: "点击启动沙盒环境",
    clickable: true,
  },
  pending: {
    label: "等待中",
    icon: Clock,
    color: "text-amber-500",
    bgColor: "bg-amber-100 dark:bg-amber-900/30",
    description: "沙盒正在排队等待启动",
    animate: true,
  },
  creating: {
    label: "创建中",
    icon: Loader2,
    color: "text-blue-500",
    bgColor: "bg-blue-100 dark:bg-blue-900/30",
    description: "正在创建沙盒容器",
    animate: true,
  },
  running: {
    label: "运行中",
    icon: CheckCircle2,
    color: "text-emerald-500",
    bgColor: "bg-emerald-100 dark:bg-emerald-900/30",
    description: "沙盒环境正常运行",
  },
  unhealthy: {
    label: "不健康",
    icon: AlertCircle,
    color: "text-orange-500",
    bgColor: "bg-orange-100 dark:bg-orange-900/30",
    description: "沙盒运行异常，可能需要重启",
    clickable: true,
  },
  stopped: {
    label: "已停止",
    icon: Power,
    color: "text-slate-500",
    bgColor: "bg-slate-100 dark:bg-slate-800",
    description: "沙盒已停止，点击重新启动",
    clickable: true,
  },
  terminated: {
    label: "已终止",
    icon: Power,
    color: "text-slate-400",
    bgColor: "bg-slate-100 dark:bg-slate-800",
    description: "沙盒已终止，点击创建新沙盒",
    clickable: true,
  },
  error: {
    label: "错误",
    icon: AlertCircle,
    color: "text-red-500",
    bgColor: "bg-red-100 dark:bg-red-900/30",
    description: "沙盒出现错误",
    clickable: true,
  },
};

/**
 * Format bytes to human readable string
 */
function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

/**
 * Format seconds to human readable duration
 */
function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return `${hours}小时${mins}分`;
}

/**
 * Sandbox metrics popover content
 */
const MetricsPopover: FC<{
  sandbox: ProjectSandbox | null;
  stats: SandboxStats | null;
  loading: boolean;
  onRefresh: () => void;
  onRestart: () => void;
  onStop: () => void;
}> = ({ sandbox, stats, loading, onRefresh, onRestart, onStop }) => {
  if (!sandbox) {
    return (
      <div className="p-3 text-sm text-slate-500">
        <div className="flex items-center gap-2 mb-2">
          <Terminal size={16} />
          <span className="font-medium">沙盒环境</span>
        </div>
        <p>点击状态指示器启动沙盒环境</p>
      </div>
    );
  }

  const config = statusConfig[sandbox.status] || statusConfig.none;

  return (
    <div className="p-3 min-w-70">
      {/* Header */}
      <div className="flex items-center justify-between mb-3 pb-2 border-b border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-2">
          <Terminal size={16} className="text-slate-600 dark:text-slate-400" />
          <span className="font-medium text-slate-800 dark:text-slate-200">
            沙盒环境
          </span>
        </div>
        <div className={`flex items-center gap-1 text-xs ${config.color}`}>
          <config.icon size={12} className={config.animate ? "animate-spin" : ""} />
          <span>{config.label}</span>
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-4">
          <Spin size="small" />
          <span className="ml-2 text-sm text-slate-500">加载中...</span>
        </div>
      )}

      {/* Metrics */}
      {!loading && stats && (
        <div className="space-y-3">
          {/* CPU */}
          <div className="flex items-center gap-3">
            <Cpu size={14} className="text-blue-500 shrink-0" />
            <div className="flex-1">
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-600 dark:text-slate-400">CPU</span>
                <span className="text-slate-800 dark:text-slate-200">
                  {stats.cpu_percent.toFixed(1)}%
                </span>
              </div>
              <Progress
                percent={stats.cpu_percent}
                size="small"
                showInfo={false}
                strokeColor={stats.cpu_percent > 80 ? "#ef4444" : "#3b82f6"}
              />
            </div>
          </div>

          {/* Memory */}
          <div className="flex items-center gap-3">
            <HardDrive size={14} className="text-purple-500 shrink-0" />
            <div className="flex-1">
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-600 dark:text-slate-400">内存</span>
                <span className="text-slate-800 dark:text-slate-200">
                  {formatBytes(stats.memory_usage)} / {formatBytes(stats.memory_limit)}
                </span>
              </div>
              <Progress
                percent={stats.memory_percent}
                size="small"
                showInfo={false}
                strokeColor={stats.memory_percent > 80 ? "#ef4444" : "#8b5cf6"}
              />
            </div>
          </div>

          {/* Network (if available) */}
          {(stats.network_rx_bytes !== undefined || stats.network_tx_bytes !== undefined) && (
            <div className="flex items-center gap-3">
              <Network size={14} className="text-emerald-500 shrink-0" />
              <div className="flex-1 text-xs">
                <div className="flex justify-between">
                  <span className="text-slate-600 dark:text-slate-400">网络</span>
                  <span className="text-slate-800 dark:text-slate-200">
                    ↓{formatBytes(stats.network_rx_bytes || 0)} / ↑{formatBytes(stats.network_tx_bytes || 0)}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Processes & Uptime */}
          <div className="flex items-center justify-between text-xs pt-2 border-t border-slate-200 dark:border-slate-700">
            <div className="text-slate-500">
              进程: <span className="text-slate-700 dark:text-slate-300">{stats.pids}</span>
            </div>
            {stats.uptime_seconds !== undefined && (
              <div className="text-slate-500">
                运行时间: <span className="text-slate-700 dark:text-slate-300">{formatDuration(stats.uptime_seconds)}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2 mt-3 pt-2 border-t border-slate-200 dark:border-slate-700">
        <Button
          size="small"
          icon={<RefreshCw size={12} />}
          onClick={onRefresh}
          loading={loading}
        >
          刷新
        </Button>
        {sandbox.status === "running" && (
          <>
            <Button size="small" onClick={onRestart}>
              重启
            </Button>
            <Button size="small" danger onClick={onStop}>
              停止
            </Button>
          </>
        )}
      </div>
    </div>
  );
};

/**
 * SandboxStatusIndicator Component
 */
export const SandboxStatusIndicator: FC<SandboxStatusIndicatorProps> = ({
  projectId,
  // tenantId reserved for future multi-tenant filtering
  className,
}) => {
  const [sandbox, setSandbox] = useState<ProjectSandbox | null>(null);
  const [stats, setStats] = useState<SandboxStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [popoverOpen, setPopoverOpen] = useState(false);

  // Determine current status
  const currentStatus: ProjectSandboxStatus | "none" = sandbox?.status || "none";
  const config = statusConfig[currentStatus] || statusConfig.none;

  /**
   * Fetch sandbox info
   */
  const fetchSandbox = useCallback(async () => {
    if (!projectId) return;

    setLoading(true);
    try {
      const info = await projectSandboxService.getProjectSandbox(projectId);
      setSandbox(info);
    } catch (error) {
      // 404 means no sandbox exists - handle silently
      const apiError = error as { statusCode?: number };
      if (apiError?.statusCode !== 404) {
        logger.error("[SandboxStatusIndicator] Failed to fetch sandbox:", error);
      }
      setSandbox(null);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  /**
   * Fetch sandbox stats
   */
  const fetchStats = useCallback(async () => {
    if (!projectId || !sandbox || sandbox.status !== "running") {
      setStats(null);
      return;
    }

    setStatsLoading(true);
    try {
      const statsData = await projectSandboxService.getStats(projectId);
      setStats(statsData);
    } catch (error) {
      logger.error("[SandboxStatusIndicator] Failed to fetch stats:", error);
      setStats(null);
    } finally {
      setStatsLoading(false);
    }
  }, [projectId, sandbox]);

  /**
   * Start sandbox
   */
  const handleStartSandbox = useCallback(async () => {
    if (!projectId || starting) return;

    setStarting(true);
    try {
      const info = await projectSandboxService.ensureSandbox(projectId, {
        auto_create: true,
      });
      setSandbox(info);
      message.success("沙盒环境已启动");
    } catch (error) {
      logger.error("[SandboxStatusIndicator] Failed to start sandbox:", error);
      const errMsg = error instanceof Error ? error.message : "未知错误";
      message.error("启动沙盒失败: " + errMsg);
    } finally {
      setStarting(false);
    }
  }, [projectId, starting]);

  /**
   * Restart sandbox
   */
  const handleRestart = useCallback(async () => {
    if (!projectId) return;

    setLoading(true);
    try {
      const result = await projectSandboxService.restartSandbox(projectId);
      if (result.sandbox) {
        setSandbox(result.sandbox);
      }
      message.success("沙盒已重启");
    } catch (error) {
      logger.error("[SandboxStatusIndicator] Failed to restart sandbox:", error);
      message.error("重启沙盒失败");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  /**
   * Stop sandbox
   */
  const handleStop = useCallback(async () => {
    if (!projectId) return;

    setLoading(true);
    try {
      await projectSandboxService.terminateSandbox(projectId);
      setSandbox(null);
      setStats(null);
      message.success("沙盒已停止");
    } catch (error) {
      logger.error("[SandboxStatusIndicator] Failed to stop sandbox:", error);
      message.error("停止沙盒失败");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  /**
   * Handle indicator click
   */
  const handleClick = useCallback(() => {
    if (config.clickable && !starting && !loading) {
      if (currentStatus === "none" || currentStatus === "stopped" || currentStatus === "terminated") {
        handleStartSandbox();
      } else if (currentStatus === "unhealthy" || currentStatus === "error") {
        handleRestart();
      }
    }
  }, [config.clickable, starting, loading, currentStatus, handleStartSandbox, handleRestart]);

  // Initial fetch
  useEffect(() => {
    fetchSandbox();
  }, [fetchSandbox]);

  // Fetch stats when popover opens and sandbox is running
  useEffect(() => {
    if (popoverOpen && sandbox?.status === "running") {
      fetchStats();
    }
  }, [popoverOpen, sandbox?.status, fetchStats]);

  // Subscribe to WebSocket sandbox state events
  // Note: WebSocket connection is managed by parent components (via useUnifiedAgentStatus)
  // The subscription will receive events once connection is established
  useEffect(() => {
    if (!projectId) return;

    // Subscribe to sandbox state changes via WebSocket
    // Events will be queued internally until WebSocket is connected
    agentService.subscribeSandboxState(
      projectId,
      "", // tenantId can be empty as it's optional on backend
      (state: SandboxStateData) => {
        logger.debug("[SandboxStatusIndicator] Sandbox state change:", state);

        switch (state.eventType) {
          case "created":
          case "restarted":
            // On created/restarted, update sandbox info from event data
            if (state.status) {
              setSandbox((prev) => {
                if (prev) {
                  return {
                    ...prev,
                    status: state.status as ProjectSandboxStatus,
                    sandbox_id: state.sandboxId || prev.sandbox_id,
                    endpoint: state.endpoint || prev.endpoint,
                    websocket_url: state.websocketUrl || prev.websocket_url,
                    mcp_port: state.mcpPort ?? prev.mcp_port,
                    desktop_port: state.desktopPort ?? prev.desktop_port,
                    terminal_port: state.terminalPort ?? prev.terminal_port,
                    is_healthy: state.isHealthy,
                  };
                } else {
                  // Create new sandbox object from event data - refetch for complete data
                  fetchSandbox();
                  return null;
                }
              });
            } else {
              // If no status in event, refetch
              fetchSandbox();
            }
            break;

          case "terminated":
            logger.debug("[SandboxStatusIndicator] Sandbox terminated");
            setSandbox(null);
            setStats(null);
            break;

          case "status_changed":
            // Update status from event data
            if (state.status) {
              setSandbox((prev) =>
                prev
                  ? {
                      ...prev,
                      status: state.status as ProjectSandboxStatus,
                      is_healthy: state.isHealthy,
                    }
                  : null
              );
            }
            break;

          default:
            // For any other event type, refetch to ensure consistency
            logger.debug(`[SandboxStatusIndicator] Unknown event type: ${state.eventType}`);
            fetchSandbox();
        }
      }
    );

    return () => {
      agentService.unsubscribeSandboxState();
    };
  }, [projectId, fetchSandbox]);

  // Auto-refresh stats while popover is open
  useEffect(() => {
    if (!popoverOpen || !sandbox || sandbox.status !== "running") return;

    const interval = setInterval(fetchStats, 5000); // Refresh every 5 seconds
    return () => clearInterval(interval);
  }, [popoverOpen, sandbox, fetchStats]);

  const StatusIcon = useMemo(() => {
    if (starting) return Loader2;
    return config.icon;
  }, [starting, config.icon]);

  const isClickable = config.clickable && !starting && !loading;

  const indicatorContent = (
    <>
      <StatusIcon
        size={12}
        className={config.animate || starting ? "animate-spin" : ""}
      />
      <span>{starting ? "启动中" : config.label}</span>
      {sandbox?.status === "running" && (
        <PlayCircle size={10} className="text-emerald-500" />
      )}
    </>
  );

  return (
    <Popover
      content={
        <MetricsPopover
          sandbox={sandbox}
          stats={stats}
          loading={statsLoading}
          onRefresh={fetchStats}
          onRestart={handleRestart}
          onStop={handleStop}
        />
      }
      trigger="hover"
      placement="topLeft"
      open={popoverOpen}
      onOpenChange={setPopoverOpen}
    >
      {isClickable ? (
        <button
          type="button"
          className={`
            flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium
            ${config.bgColor} ${config.color}
            transition-all duration-300
            cursor-pointer hover:opacity-80
            border-none outline-none
            ${className || ""}
          `}
          onClick={handleClick}
        >
          {indicatorContent}
        </button>
      ) : (
        <span
          className={`
            flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium
            ${config.bgColor} ${config.color}
            transition-all duration-300
            ${className || ""}
          `}
        >
          {indicatorContent}
        </span>
      )}
    </Popover>
  );
};

export default SandboxStatusIndicator;
