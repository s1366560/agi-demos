/**
 * SandboxOutputViewer - Display tool execution output with syntax highlighting
 *
 * Shows the output from sandbox tool executions (read, write, edit, etc.)
 * with proper formatting and syntax highlighting.
 */

import { useState, useMemo } from "react";
import { Typography, Tag, Empty, Collapse, Button, Tooltip, message } from "antd";
import {
  CopyOutlined,
  CheckOutlined,
  FileTextOutlined,
  CodeOutlined,
  DesktopOutlined,
  SearchOutlined,
  EditOutlined,
  FolderOutlined,
} from "@ant-design/icons";
import type { CollapseProps } from "antd";

const { Text } = Typography;

export interface ToolExecution {
  id: string;
  toolName: string;
  input: Record<string, unknown>;
  output?: string;
  error?: string;
  durationMs?: number;
  timestamp: number;
}

export interface SandboxOutputViewerProps {
  /** List of tool executions to display */
  executions: ToolExecution[];
  /** Maximum height (default: 100%) */
  maxHeight?: string | number;
  /** Called when user clicks on a file path */
  onFileClick?: (filePath: string) => void;
}

// Tool icons mapping
const TOOL_ICONS: Record<string, React.ReactNode> = {
  read: <FileTextOutlined />,
  write: <EditOutlined />,
  edit: <CodeOutlined />,
  glob: <FolderOutlined />,
  grep: <SearchOutlined />,
  bash: <DesktopOutlined />,
};

// Tool colors mapping
const TOOL_COLORS: Record<string, string> = {
  read: "blue",
  write: "green",
  edit: "orange",
  glob: "purple",
  grep: "cyan",
  bash: "default",
};

function ToolExecutionCard({
  execution,
  onFileClick,
}: {
  execution: ToolExecution;
  onFileClick?: (filePath: string) => void;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const content = execution.output || execution.error || "";
    await navigator.clipboard.writeText(content);
    setCopied(true);
    message.success("Copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  // Format input for display
  const formattedInput = useMemo(() => {
    const input = execution.input;
    if (execution.toolName === "read" || execution.toolName === "write") {
      return input.file_path as string;
    }
    if (execution.toolName === "edit") {
      return `${input.file_path} (${(input.old_string as string)?.length || 0} → ${(input.new_string as string)?.length || 0} chars)`;
    }
    if (execution.toolName === "glob") {
      return input.pattern as string;
    }
    if (execution.toolName === "grep") {
      return `${input.pattern} ${input.path ? `in ${input.path}` : ""}`;
    }
    if (execution.toolName === "bash") {
      const cmd = input.command as string;
      return cmd.length > 50 ? cmd.slice(0, 50) + "..." : cmd;
    }
    return JSON.stringify(input);
  }, [execution]);

  // Determine if output looks like code
  const isCodeOutput = useMemo(() => {
    const output = execution.output || "";
    return (
      execution.toolName === "read" ||
      execution.toolName === "bash" ||
      output.includes("\n") ||
      output.startsWith("{") ||
      output.startsWith("[")
    );
  }, [execution]);

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden bg-white">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-slate-50 border-b border-slate-200">
        <div className="flex items-center gap-2">
          <Tag
            icon={TOOL_ICONS[execution.toolName]}
            color={TOOL_COLORS[execution.toolName]}
          >
            {execution.toolName}
          </Tag>
          <Text
            className="text-sm text-slate-600 cursor-pointer hover:text-blue-600"
            onClick={() => {
              const filePath =
                (execution.input.file_path as string) ||
                (execution.input.path as string);
              if (filePath && onFileClick) {
                onFileClick(filePath);
              }
            }}
          >
            {formattedInput}
          </Text>
        </div>
        <div className="flex items-center gap-2">
          {execution.durationMs && (
            <Text className="text-xs text-slate-400">
              {execution.durationMs}ms
            </Text>
          )}
          <Tooltip title={copied ? "Copied!" : "Copy output"}>
            <Button
              type="text"
              size="small"
              icon={copied ? <CheckOutlined /> : <CopyOutlined />}
              onClick={handleCopy}
              className="text-slate-400 hover:text-slate-600"
            />
          </Tooltip>
        </div>
      </div>

      {/* Content */}
      <div className="max-h-64 overflow-auto">
        {execution.error ? (
          <div className="p-3 bg-red-50">
            <Text type="danger" className="text-sm font-mono whitespace-pre-wrap">
              {execution.error}
            </Text>
          </div>
        ) : execution.output ? (
          <div className={`p-3 ${isCodeOutput ? "bg-slate-900" : "bg-white"}`}>
            <pre
              className={`text-sm font-mono whitespace-pre-wrap m-0 ${
                isCodeOutput ? "text-slate-200" : "text-slate-700"
              }`}
            >
              {execution.output}
            </pre>
          </div>
        ) : (
          <div className="p-3 text-center">
            <Text type="secondary" className="text-sm">
              No output
            </Text>
          </div>
        )}
      </div>
    </div>
  );
}

export function SandboxOutputViewer({
  executions,
  maxHeight = "100%",
  onFileClick,
}: SandboxOutputViewerProps) {
  if (executions.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-full"
        style={{ maxHeight }}
      >
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="No tool executions yet"
        />
      </div>
    );
  }

  // Group executions for collapse view if many
  const useCollapse = executions.length > 3;

  if (useCollapse) {
    const items: CollapseProps["items"] = executions.map((exec, _index) => ({
      key: exec.id,
      label: (
        <div className="flex items-center gap-2">
          <Tag
            icon={TOOL_ICONS[exec.toolName]}
            color={TOOL_COLORS[exec.toolName]}
            className="m-0"
          >
            {exec.toolName}
          </Tag>
          <Text className="text-sm text-slate-600">
            {new Date(exec.timestamp).toLocaleTimeString()}
          </Text>
          {exec.error && <Tag color="error">Error</Tag>}
        </div>
      ),
      children: (
        <ToolExecutionCard execution={exec} onFileClick={onFileClick} />
      ),
    }));

    return (
      <div className="h-full overflow-auto p-2" style={{ maxHeight }}>
        <Collapse
          items={items}
          defaultActiveKey={[executions[executions.length - 1]?.id]}
          size="small"
        />
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-2 space-y-2" style={{ maxHeight }}>
      {executions.map((exec) => (
        <ToolExecutionCard
          key={exec.id}
          execution={exec}
          onFileClick={onFileClick}
        />
      ))}
    </div>
  );
}

export default SandboxOutputViewer;
