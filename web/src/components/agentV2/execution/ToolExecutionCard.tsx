/**
 * Tool Execution Card
 *
 * Displays tool execution progress and results with timeline style.
 */

import { useState } from 'react';
import {
  DownOutlined,
  RightOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  CopyOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { useToolExecutions } from '../../../stores/agentV2';
import type { ToolExecution } from '../../../types/agentV2';

interface ToolExecutionCardProps {
  variant?: 'card' | 'inline' | 'detailed';
}

interface ToolExecutionDataProps {
  data: Record<string, unknown>;
  title: string;
}

// JSON syntax highlighted display component
function JsonDisplay({ data, title }: ToolExecutionDataProps) {
  const jsonString = JSON.stringify(data, null, 2);
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(jsonString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Simple syntax highlighting for JSON
  const syntaxHighlight = (json: string): string => {
    return json.replace(/(\{[^}]*\}|\[[^\]]*\]|"[^"]*"|:\s*[^,\[\]{}]*|,|\b(true|false|null)\b)/g, (match: string) => {
      if (match.startsWith('{') || match.startsWith('[')) {
        return `<span class="text-purple-600 dark:text-purple-400">${match}</span>`;
      }
      if (match.startsWith('"')) {
        return `<span class="text-green-600 dark:text-green-400">${match}</span>`;
      }
      if (match.includes(':')) {
        return `<span class="text-blue-600 dark:text-blue-400">${match}</span>`;
      }
      if (match === ',') {
        return `<span class="text-gray-500">${match}</span>`;
      }
      if (match === 'true' || match === 'false' || match === 'null') {
        return `<span class="text-orange-600 dark:text-orange-400">${match}</span>`;
      }
      return match;
    });
  };

  return (
    <div className="my-3">
      <div className="flex items-center justify-between mb-2 px-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-gray-600 dark:text-gray-400">
          {title}
        </span>
        <button
          onClick={handleCopy}
          className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors flex items-center gap-1 text-xs"
          title="Copy to clipboard"
        >
          <CopyOutlined />
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre className="bg-gray-900 dark:bg-gray-950 p-3 rounded-lg overflow-x-auto">
        <code
          className="text-xs font-mono"
          dangerouslySetInnerHTML={{ __html: syntaxHighlight(jsonString) }}
        />
      </pre>
    </div>
  );
}

// Tool execution timeline item
interface ToolExecutionItemProps {
  execution: ToolExecution;
  isExpanded: boolean;
  onToggle: () => void;
}

function ToolExecutionItem({ execution, isExpanded, onToggle }: ToolExecutionItemProps) {
  const hasInput = execution.input && Object.keys(execution.input).length > 0;
  const hasResult = execution.result || execution.error;
  const hasContent = hasInput || hasResult;

  const getStatusIcon = () => {
    switch (execution.status) {
      case 'running':
        return <PlayCircleOutlined className="text-blue-500 spin" />;
      case 'success':
        return <CheckCircleOutlined className="text-green-500" />;
      case 'failed':
        return <CloseCircleOutlined className="text-red-500" />;
      default:
        return <ClockCircleOutlined className="text-gray-400" />;
    }
  };

  const getStatusText = () => {
    switch (execution.status) {
      case 'running':
        return 'Executing...';
      case 'success':
        return 'Completed';
      case 'failed':
        return 'Failed';
      default:
        return 'Pending';
    }
  };

  const formatDuration = (ms?: number) => {
    if (!ms) return null;
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const formatTime = (timeString: string) => {
    const date = new Date(timeString);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  return (
    <div className="relative pl-6 pb-4">
      {/* Timeline line */}
      <div className="absolute left-0 top-0 bottom-0 w-px bg-gray-200 dark:bg-gray-700">
        <div className={`absolute left-1/2 -translate-x-1/2 w-3 h-3 rounded-full border-2 ${
          execution.status === 'running'
            ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 animate-pulse'
            : execution.status === 'success'
            ? 'border-green-500 bg-green-50 dark:bg-green-900/20'
            : execution.status === 'failed'
            ? 'border-red-500 bg-red-50 dark:bg-red-900/20'
            : 'border-gray-400 bg-gray-50 dark:bg-gray-800'
        }`}>
          <div className="absolute inset-0 flex items-center justify-center">
            {getStatusIcon()}
          </div>
        </div>
      </div>

      {/* Card */}
      <div className="ml-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
        {/* Header */}
        <div
          onClick={hasContent ? onToggle : undefined}
          className={`flex items-center justify-between px-4 py-3 ${
            hasContent ? 'cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50' : ''
          } transition-colors`}
        >
          <div className="flex items-center gap-3">
            {getStatusIcon()}
            <div>
              <div className="font-semibold text-sm text-gray-900 dark:text-gray-100">
                {execution.tool_name}
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <span>{getStatusText()}</span>
                {execution.start_time && (
                  <span>· {formatTime(execution.start_time)}</span>
                )}
                {execution.duration_ms && (
                  <span>· {formatDuration(execution.duration_ms)}</span>
                )}
                {execution.step_number !== undefined && (
                  <span className="px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded text-xs">
                    Step {execution.step_number}
                  </span>
                )}
              </div>
            </div>
          </div>

          {hasContent && (
            <span className="text-gray-400">
              {isExpanded ? <DownOutlined /> : <RightOutlined />}
            </span>
          )}
        </div>

        {/* Expanded content */}
        {isExpanded && hasContent && (
          <div className="px-4 pb-4 bg-gray-50/50 dark:bg-gray-900/30">
            {/* Input */}
            {hasInput && (
              <JsonDisplay
                data={execution.input}
                title={`Input (${Object.keys(execution.input).length} field${Object.keys(execution.input).length > 1 ? 's' : ''})`}
              />
            )}

            {/* Result */}
            {execution.result && (
              <div className="my-3">
                <div className="flex items-center justify-between mb-2 px-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-gray-600 dark:text-gray-400">
                    Result
                  </span>
                  <button
                    onClick={() => execution.result && navigator.clipboard.writeText(execution.result)}
                    className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors flex items-center gap-1 text-xs"
                    title="Copy result"
                  >
                    <CopyOutlined />
                    Copy
                  </button>
                </div>
                <pre className="bg-gray-900 dark:bg-gray-950 p-3 rounded-lg overflow-x-auto max-h-64 overflow-y-auto">
                  <code className="text-xs font-mono text-gray-100">{execution.result}</code>
                </pre>
              </div>
            )}

            {/* Error */}
            {execution.error && (
              <div className="mt-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
                <div className="flex items-center gap-2 mb-1">
                  <CloseCircleOutlined className="text-red-600 dark:text-red-400" />
                  <span className="text-xs font-semibold uppercase tracking-wider text-red-600 dark:text-red-400">
                    Error
                  </span>
                </div>
                <p className="text-sm text-red-700 dark:text-red-300">{execution.error}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function ToolExecutionCard({ variant = 'card' }: ToolExecutionCardProps) {
  const toolExecutions = useToolExecutions();
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  if (toolExecutions.length === 0) return null;

  // Auto-expand running tool executions
  const runningTool = toolExecutions.find(t => t.status === 'running');
  if (runningTool && !expandedIds.has(runningTool.id)) {
    setExpandedIds(prev => new Set(prev).add(runningTool.id));
  }

  const toggleExpanded = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // Only show in non-inline mode
  if (variant === 'inline') return null;

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 mb-3 px-2">
        <PlayCircleOutlined className="text-gray-500" />
        <h3 className="font-semibold text-sm text-gray-700 dark:text-gray-300">
          Tool Executions ({toolExecutions.length})
        </h3>
      </div>
      {toolExecutions.map((execution) => (
        <ToolExecutionItem
          key={execution.id}
          execution={execution}
          isExpanded={expandedIds.has(execution.id)}
          onToggle={() => toggleExpanded(execution.id)}
        />
      ))}
    </div>
  );
}
