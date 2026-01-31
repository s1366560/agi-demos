/**
 * ToolCallVisualization - Tool call visualization component
 *
 * Displays tool execution information in multiple visual modes:
 * - Grid: Card-based layout for each tool
 * - Timeline: Horizontal timeline showing execution duration
 * - Flow: Flow diagram showing execution sequence
 */

import React, { useState, useMemo, memo } from "react";
import { Tooltip, Drawer, Tag, Empty, Segmented } from "antd";
import {
  CheckCircleOutlined,
  SyncOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  SearchOutlined,
  ApiOutlined,
  CloudOutlined,
  FileSearchOutlined,
  EditOutlined,
  GlobalOutlined,
  AppstoreOutlined,
  UnorderedListOutlined,
  NodeIndexOutlined,
} from "@ant-design/icons";

/**
 * Tool execution item for visualization
 */
export interface ToolExecutionItem {
  id: string;
  toolName: string;
  input: Record<string, unknown>;
  output?: string;
  status: "running" | "success" | "failed";
  startTime: number;
  endTime?: number;
  duration?: number;
  stepNumber?: number;
  error?: string;
}

export interface ToolCallVisualizationProps {
  /** Tool execution records */
  toolExecutions: ToolExecutionItem[];
  /** Display mode */
  mode?: "grid" | "timeline" | "flow";
  /** Show input/output details */
  showDetails?: boolean;
  /** Click handler for tool selection */
  onToolClick?: (execution: ToolExecutionItem) => void;
  /** Allow mode switching */
  allowModeSwitch?: boolean;
  /** Compact mode */
  compact?: boolean;
}

// Tool icon mapping
const TOOL_ICONS: Record<string, React.ReactNode> = {
  memory_search: <SearchOutlined />,
  entity_lookup: <ApiOutlined />,
  graph_query: <NodeIndexOutlined />,
  web_search: <GlobalOutlined />,
  web_scrape: <FileSearchOutlined />,
  summary: <FileSearchOutlined />,
  memory_create: <EditOutlined />,
  default: <CloudOutlined />,
};

// Get tool icon
const getToolIcon = (toolName: string): React.ReactNode => {
  return TOOL_ICONS[toolName] || TOOL_ICONS.default;
};

// Format duration
const formatDuration = (ms: number): string => {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
};

// Format timestamp
const formatTime = (timestamp: number): string => {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

/**
 * Status icon component
 */
const StatusIcon: React.FC<{ status: "running" | "success" | "failed" }> = ({
  status,
}) => {
  switch (status) {
    case "running":
      return <SyncOutlined spin className="text-blue-500" />;
    case "success":
      return <CheckCircleOutlined className="text-emerald-500" />;
    case "failed":
      return <CloseCircleOutlined className="text-red-500" />;
  }
};

/**
 * Grid mode - Card-based layout
 */
interface GridViewProps {
  executions: ToolExecutionItem[];
  onToolClick?: (execution: ToolExecutionItem) => void;
  compact?: boolean;
}

const GridView: React.FC<GridViewProps> = ({
  executions,
  onToolClick,
  compact = false,
}) => {
  return (
    <div
      className={`grid gap-3 ${
        compact
          ? "grid-cols-2 sm:grid-cols-3"
          : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
      }`}
    >
      {executions.map((exec) => (
        <div
          key={exec.id}
          onClick={() => onToolClick?.(exec)}
          className={`p-3 rounded-lg border cursor-pointer transition-all hover:shadow-md ${
            exec.status === "running"
              ? "bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800"
              : exec.status === "success"
              ? "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800"
              : "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800"
          }`}
        >
          <div className="flex items-center gap-2 mb-2">
            <span className="text-lg">{getToolIcon(exec.toolName)}</span>
            <span
              className={`font-medium ${
                compact ? "text-xs" : "text-sm"
              } text-slate-700 dark:text-slate-200 truncate`}
            >
              {exec.toolName}
            </span>
            <StatusIcon status={exec.status} />
          </div>

          <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            {exec.duration !== undefined && (
              <span className="flex items-center gap-1">
                <ClockCircleOutlined className="text-[10px]" />
                {formatDuration(exec.duration)}
              </span>
            )}
            <Tag
              color={
                exec.status === "success"
                  ? "success"
                  : exec.status === "failed"
                  ? "error"
                  : "processing"
              }
              className="mr-0 text-[10px]"
            >
              {exec.status.toUpperCase()}
            </Tag>
          </div>
        </div>
      ))}
    </div>
  );
};

/**
 * Timeline mode - Horizontal timeline
 */
interface TimelineViewProps {
  executions: ToolExecutionItem[];
  onToolClick?: (execution: ToolExecutionItem) => void;
}

const TimelineView: React.FC<TimelineViewProps> = ({
  executions,
  onToolClick,
}) => {
  // Calculate time range
  const timeRange = useMemo(() => {
    if (executions.length === 0) return { min: 0, max: 1000, range: 1000 };
    const times = executions.flatMap((e) => [
      e.startTime,
      e.endTime || e.startTime + (e.duration || 0),
    ]);
    const min = Math.min(...times);
    const max = Math.max(...times);
    return { min, max, range: max - min || 1000 };
  }, [executions]);

  // Calculate position and width for each execution
  const getBarStyle = (exec: ToolExecutionItem) => {
    const left = ((exec.startTime - timeRange.min) / timeRange.range) * 100;
    const end =
      exec.endTime || exec.startTime + (exec.duration || timeRange.range * 0.1);
    const width = ((end - exec.startTime) / timeRange.range) * 100;
    return { left: `${left}%`, width: `${Math.max(width, 2)}%` };
  };

  return (
    <div className="space-y-3">
      {/* Time axis */}
      <div className="relative h-6 border-b border-slate-200 dark:border-slate-700">
        <span className="absolute left-0 bottom-1 text-[10px] text-slate-400">
          {formatTime(timeRange.min)}
        </span>
        <span className="absolute right-0 bottom-1 text-[10px] text-slate-400">
          {formatTime(timeRange.max)}
        </span>
      </div>

      {/* Timeline bars */}
      <div className="space-y-2">
        {executions.map((exec) => {
          const barStyle = getBarStyle(exec);
          return (
            <div key={exec.id} className="relative h-8">
              {/* Label */}
              <div className="absolute left-0 top-1/2 -translate-y-1/2 w-24 pr-2 text-right">
                <span className="text-xs text-slate-600 dark:text-slate-300 truncate">
                  {exec.toolName}
                </span>
              </div>

              {/* Track */}
              <div className="absolute left-28 right-0 top-1/2 -translate-y-1/2 h-1 bg-slate-200 dark:bg-slate-700 rounded" />

              {/* Bar */}
              <Tooltip
                title={
                  <div>
                    <div>{exec.toolName}</div>
                    {exec.duration && (
                      <div>Duration: {formatDuration(exec.duration)}</div>
                    )}
                    <div>Status: {exec.status}</div>
                  </div>
                }
              >
                <div
                  onClick={() => onToolClick?.(exec)}
                  className={`absolute top-1/2 -translate-y-1/2 h-6 rounded cursor-pointer transition-all hover:opacity-80 ${
                    exec.status === "running"
                      ? "bg-blue-500 animate-pulse"
                      : exec.status === "success"
                      ? "bg-emerald-500"
                      : "bg-red-500"
                  }`}
                  style={{
                    left: `calc(7rem + ${barStyle.left})`,
                    width: barStyle.width,
                    minWidth: "8px",
                  }}
                />
              </Tooltip>
            </div>
          );
        })}
      </div>
    </div>
  );
};

/**
 * Flow mode - Sequential flow diagram
 */
interface FlowViewProps {
  executions: ToolExecutionItem[];
  onToolClick?: (execution: ToolExecutionItem) => void;
}

const FlowView: React.FC<FlowViewProps> = ({ executions, onToolClick }) => {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {executions.map((exec, index) => (
        <React.Fragment key={exec.id}>
          {/* Node */}
          <Tooltip
            title={
              <div>
                <div className="font-medium">{exec.toolName}</div>
                {exec.duration && (
                  <div>Duration: {formatDuration(exec.duration)}</div>
                )}
                <div>Status: {exec.status}</div>
              </div>
            }
          >
            <div
              onClick={() => onToolClick?.(exec)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-all hover:shadow-md ${
                exec.status === "running"
                  ? "bg-blue-100 dark:bg-blue-900/30 border-blue-300 dark:border-blue-700"
                  : exec.status === "success"
                  ? "bg-emerald-100 dark:bg-emerald-900/30 border-emerald-300 dark:border-emerald-700"
                  : "bg-red-100 dark:bg-red-900/30 border-red-300 dark:border-red-700"
              }`}
            >
              <span className="text-lg">{getToolIcon(exec.toolName)}</span>
              <div>
                <div className="text-xs font-medium text-slate-700 dark:text-slate-200">
                  {exec.toolName}
                </div>
                {exec.duration !== undefined && (
                  <div className="text-[10px] text-slate-500 dark:text-slate-400">
                    {formatDuration(exec.duration)}
                  </div>
                )}
              </div>
              <StatusIcon status={exec.status} />
            </div>
          </Tooltip>

          {/* Arrow connector */}
          {index < executions.length - 1 && (
            <div className="text-slate-300 dark:text-slate-600">→</div>
          )}
        </React.Fragment>
      ))}
    </div>
  );
};

/**
 * Detail drawer for tool execution
 */
interface DetailDrawerProps {
  execution: ToolExecutionItem | null;
  visible: boolean;
  onClose: () => void;
}

const DetailDrawer: React.FC<DetailDrawerProps> = ({
  execution,
  visible,
  onClose,
}) => {
  if (!execution) return null;

  return (
    <Drawer
      title={
        <div className="flex items-center gap-2">
          {getToolIcon(execution.toolName)}
          <span>{execution.toolName}</span>
          <StatusIcon status={execution.status} />
        </div>
      }
      open={visible}
      onClose={onClose}
      width={480}
    >
      <div className="space-y-4">
        {/* Status and timing */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">
              Status
            </div>
            <Tag
              color={
                execution.status === "success"
                  ? "success"
                  : execution.status === "failed"
                  ? "error"
                  : "processing"
              }
            >
              {execution.status.toUpperCase()}
            </Tag>
          </div>
          {execution.duration !== undefined && (
            <div>
              <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">
                Duration
              </div>
              <span className="font-mono">
                {formatDuration(execution.duration)}
              </span>
            </div>
          )}
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">
              Start Time
            </div>
            <span className="font-mono text-sm">
              {formatTime(execution.startTime)}
            </span>
          </div>
          {execution.endTime && (
            <div>
              <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">
                End Time
              </div>
              <span className="font-mono text-sm">
                {formatTime(execution.endTime)}
              </span>
            </div>
          )}
        </div>

        {/* Input */}
        <div>
          <div className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-2">
            INPUT
          </div>
          <pre className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 text-xs overflow-x-auto max-h-60">
            {JSON.stringify(execution.input, null, 2)}
          </pre>
        </div>

        {/* Output */}
        {execution.output && (
          <div>
            <div className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-2">
              OUTPUT
            </div>
            <pre className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 text-xs overflow-x-auto max-h-60 whitespace-pre-wrap">
              {execution.output}
            </pre>
          </div>
        )}

        {/* Error */}
        {execution.error && (
          <div>
            <div className="text-xs font-semibold text-red-500 mb-2">ERROR</div>
            <pre className="p-3 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800 text-xs text-red-600 dark:text-red-400 overflow-x-auto">
              {execution.error}
            </pre>
          </div>
        )}
      </div>
    </Drawer>
  );
};

/**
 * ToolCallVisualization component
 * Memoized to prevent unnecessary re-renders (rerender-memo)
 */
const ToolCallVisualizationInternal: React.FC<ToolCallVisualizationProps> = ({
  toolExecutions,
  mode: initialMode = "grid",
  showDetails = true,
  onToolClick,
  allowModeSwitch = true,
  compact = false,
}) => {
  const [mode, setMode] = useState<"grid" | "timeline" | "flow">(initialMode);
  const [selectedExecution, setSelectedExecution] =
    useState<ToolExecutionItem | null>(null);
  const [drawerVisible, setDrawerVisible] = useState(false);

  // Handle tool click
  const handleToolClick = (execution: ToolExecutionItem) => {
    if (onToolClick) {
      onToolClick(execution);
    }
    if (showDetails) {
      setSelectedExecution(execution);
      setDrawerVisible(true);
    }
  };

  // Sort executions by start time
  const sortedExecutions = useMemo(() => {
    return [...toolExecutions].sort((a, b) => a.startTime - b.startTime);
  }, [toolExecutions]);

  if (toolExecutions.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="No tool executions"
        className="py-8"
      />
    );
  }

  const modeOptions = [
    { value: "grid", icon: <AppstoreOutlined />, label: "Grid" },
    { value: "timeline", icon: <UnorderedListOutlined />, label: "Timeline" },
    { value: "flow", icon: <NodeIndexOutlined />, label: "Flow" },
  ];

  return (
    <div className="space-y-4">
      {/* Mode switcher */}
      {allowModeSwitch && (
        <div className="flex justify-end">
          <Segmented
            size="small"
            value={mode}
            onChange={(value) => setMode(value as typeof mode)}
            options={modeOptions.map((opt) => ({
              value: opt.value,
              label: (
                <Tooltip title={opt.label}>
                  <span className="px-1">{opt.icon}</span>
                </Tooltip>
              ),
            }))}
          />
        </div>
      )}

      {/* Visualization */}
      {mode === "grid" && (
        <GridView
          executions={sortedExecutions}
          onToolClick={handleToolClick}
          compact={compact}
        />
      )}
      {mode === "timeline" && (
        <TimelineView
          executions={sortedExecutions}
          onToolClick={handleToolClick}
        />
      )}
      {mode === "flow" && (
        <FlowView executions={sortedExecutions} onToolClick={handleToolClick} />
      )}

      {/* Detail drawer */}
      {showDetails && (
        <DetailDrawer
          execution={selectedExecution}
          visible={drawerVisible}
          onClose={() => setDrawerVisible(false)}
        />
      )}
    </div>
  );
};

export const ToolCallVisualization = memo(ToolCallVisualizationInternal);
ToolCallVisualization.displayName = 'ToolCallVisualization';

export default ToolCallVisualization;
