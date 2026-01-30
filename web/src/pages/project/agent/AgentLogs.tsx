/**
 * AgentLogs - Execution history and logs view
 *
 * Displays agent execution history, step-by-step logs,
 * and debugging information for agent interactions.
 */

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { Select, Collapse, Empty, Skeleton, Tag, Timeline, message, Button } from 'antd';
import { MaterialIcon } from '../../../components/agent/shared';
import { ExecutionStatsCard } from '../../../components/agent/ExecutionStatsCard';
import { ExecutionTimelineChart } from '../../../components/agent/ExecutionTimelineChart';
import { useProjectStore } from '../../../stores/project';
import { agentService } from '../../../services/agentService';
import type {
  Conversation,
  AgentExecutionWithDetails,
  ExecutionStatsResponse,
} from '../../../types/agent';

/**
 * Format timestamp to readable string
 */
function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Format duration in milliseconds to human readable string
 */
function formatDuration(startedAt: string, completedAt?: string): string {
  if (!completedAt) return 'In progress';
  const start = new Date(startedAt).getTime();
  const end = new Date(completedAt).getTime();
  const durationMs = end - start;

  if (durationMs < 1000) return `${durationMs}ms`;
  if (durationMs < 60000) return `${(durationMs / 1000).toFixed(1)}s`;
  return `${Math.floor(durationMs / 60000)}m ${Math.floor((durationMs % 60000) / 1000)}s`;
}

/**
 * Get status color for execution status
 */
function getStatusColor(status: string): string {
  switch (status) {
    case 'completed':
      return 'green';
    case 'thinking':
    case 'planning':
    case 'work_planning':
      return 'blue';
    case 'acting':
    case 'step_executing':
      return 'processing';
    case 'observing':
      return 'cyan';
    case 'failed':
      return 'red';
    default:
      return 'default';
  }
}

/**
 * ExecutionCard component - displays a single execution record
 */
interface ExecutionCardProps {
  execution: AgentExecutionWithDetails;
  isExpanded: boolean;
  onToggle: () => void;
}

function ExecutionCard({ execution, isExpanded, onToggle }: ExecutionCardProps) {
  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
      {/* Header */}
      <div
        className="px-4 py-3 flex items-center justify-between cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/70"
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          <Tag color={getStatusColor(execution.status)}>{execution.status}</Tag>
          <span className="text-sm text-slate-600 dark:text-slate-400">
            {formatTime(execution.started_at)}
          </span>
          <span className="text-sm text-slate-400">
            Duration: {formatDuration(execution.started_at, execution.completed_at)}
          </span>
        </div>
        <MaterialIcon
          name={isExpanded ? 'expand_less' : 'expand_more'}
          size={20}
          className="text-slate-400"
        />
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="px-4 pb-4 border-t border-slate-100 dark:border-slate-700">
          {/* Work Plan Section */}
          {execution.plan_steps && execution.plan_steps.length > 0 && (
            <div className="mt-4">
              <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2 flex items-center gap-2">
                <MaterialIcon name="account_tree" size={16} />
                Work Plan ({execution.plan_steps.length} steps)
              </h4>
              <Timeline
                items={execution.plan_steps.map((step, index) => ({
                  color: index < (execution.current_step || 0) ? 'green' : 'gray',
                  children: (
                    <div key={step.step_number}>
                      <p className="text-sm font-medium text-slate-800 dark:text-slate-200">
                        Step {step.step_number}: {step.description}
                      </p>
                      <p className="text-xs text-slate-500 mt-1">
                        Tools: {step.required_tools.join(', ')}
                      </p>
                    </div>
                  ),
                }))}
              />
            </div>
          )}

          {/* Work-level Thought */}
          {execution.work_level_thought && (
            <div className="mt-4">
              <h4 className="text-sm font-semibold text-purple-600 dark:text-purple-400 mb-2 flex items-center gap-2">
                <MaterialIcon name="psychology" size={16} />
                Work-level Thinking
              </h4>
              <div className="bg-purple-50 dark:bg-purple-900/20 rounded-lg p-3 text-sm text-slate-700 dark:text-slate-300">
                {execution.work_level_thought}
              </div>
            </div>
          )}

          {/* Task-level Thought */}
          {execution.task_level_thought && (
            <div className="mt-4">
              <h4 className="text-sm font-semibold text-cyan-600 dark:text-cyan-400 mb-2 flex items-center gap-2">
                <MaterialIcon name="lightbulb" size={16} />
                Task-level Thinking
              </h4>
              <div className="bg-cyan-50 dark:bg-cyan-900/20 rounded-lg p-3 text-sm text-slate-700 dark:text-slate-300">
                {execution.task_level_thought}
              </div>
            </div>
          )}

          {/* General Thought */}
          {execution.thought && !execution.work_level_thought && !execution.task_level_thought && (
            <div className="mt-4">
              <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2 flex items-center gap-2">
                <MaterialIcon name="psychology" size={16} />
                Thought
              </h4>
              <div className="bg-slate-50 dark:bg-slate-700/50 rounded-lg p-3 text-sm text-slate-700 dark:text-slate-300">
                {execution.thought}
              </div>
            </div>
          )}

          {/* Tool Execution */}
          {execution.tool_name && (
            <div className="mt-4">
              <h4 className="text-sm font-semibold text-amber-600 dark:text-amber-400 mb-2 flex items-center gap-2">
                <MaterialIcon name="build" size={16} />
                Tool Execution: {execution.tool_name}
              </h4>
              {execution.tool_input && (
                <Collapse
                  size="small"
                  items={[
                    {
                      key: 'input',
                      label: 'Input Parameters',
                      children: (
                        <pre className="text-xs bg-slate-100 dark:bg-slate-900 p-2 rounded overflow-x-auto">
                          {JSON.stringify(execution.tool_input, null, 2)}
                        </pre>
                      ),
                    },
                  ]}
                />
              )}
              {execution.tool_output && (
                <Collapse
                  size="small"
                  className="mt-2"
                  items={[
                    {
                      key: 'output',
                      label: 'Output Result',
                      children: (
                        <pre className="text-xs bg-slate-100 dark:bg-slate-900 p-2 rounded overflow-x-auto max-h-48">
                          {execution.tool_output}
                        </pre>
                      ),
                    },
                  ]}
                />
              )}
            </div>
          )}

          {/* Observation */}
          {execution.observation && (
            <div className="mt-4">
              <h4 className="text-sm font-semibold text-emerald-600 dark:text-emerald-400 mb-2 flex items-center gap-2">
                <MaterialIcon name="visibility" size={16} />
                Observation
              </h4>
              <div className="bg-emerald-50 dark:bg-emerald-900/20 rounded-lg p-3 text-sm text-slate-700 dark:text-slate-300">
                {execution.observation}
              </div>
            </div>
          )}

          {/* Workflow Pattern */}
          {execution.workflow_pattern_id && (
            <div className="mt-4 flex items-center gap-2">
              <Tag color="purple">
                <MaterialIcon name="auto_awesome" size={12} className="mr-1" />
                Pattern: {execution.workflow_pattern_id.slice(0, 8)}...
              </Tag>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export const AgentLogs: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  void useProjectStore(); // For future project context usage

  // State
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [executions, setExecutions] = useState<AgentExecutionWithDetails[]>([]);
  const [stats, setStats] = useState<ExecutionStatsResponse | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [executionsLoading, setExecutionsLoading] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  
  // Filters
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [toolFilter, setToolFilter] = useState<string | undefined>(undefined);

  // Load conversations on mount
  // Separate function from auto-selection logic to prevent infinite loop
  const loadConversations = useCallback(async () => {
    if (!projectId) return;

    setLoading(true);
    try {
      const convs = await agentService.listConversations(projectId);
      setConversations(convs);
      return convs;
    } catch (err) {
      message.error('Failed to load conversations');
      console.error(err);
      return [];
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  // Load conversations when project changes
  useEffect(() => {
    loadConversations().then((convs) => {
      // Auto-select first conversation only if none is selected
      if (convs.length > 0 && !selectedConversationId) {
        setSelectedConversationId(convs[0].id);
      }
    });
  }, [projectId, loadConversations]);

  // Load execution history when conversation changes
  useEffect(() => {
    if (!selectedConversationId || !projectId) {
      setExecutions([]);
      setStats(null);
      return;
    }

    const loadExecutions = async () => {
      setExecutionsLoading(true);
      try {
        const response = await agentService.getExecutionHistory(
          selectedConversationId,
          projectId,
          100,
          statusFilter,
          toolFilter
        );
        setExecutions(response.executions);
      } catch (err) {
        message.error('Failed to load execution history');
        console.error(err);
      } finally {
        setExecutionsLoading(false);
      }
    };

    const loadStats = async () => {
      setStatsLoading(true);
      try {
        const response = await agentService.getExecutionStats(
          selectedConversationId,
          projectId
        );
        setStats(response);
      } catch (err) {
        message.error('Failed to load execution statistics');
        console.error(err);
      } finally {
        setStatsLoading(false);
      }
    };

    loadExecutions();
    loadStats();
  }, [selectedConversationId, projectId, statusFilter, toolFilter]);

  const toggleExpand = (id: string) => {
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

  const expandAll = () => {
    setExpandedIds(new Set(executions.map((e) => e.id)));
  };

  const collapseAll = () => {
    setExpandedIds(new Set());
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
              <MaterialIcon name="history" size={24} className="text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Execution Logs</h1>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                View detailed execution history and debugging information
              </p>
            </div>
          </div>
        </div>

        {/* Conversation Selector */}
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4 mb-6">
          <div className="flex items-center justify-between gap-4 mb-4">
            <div className="flex items-center gap-3 flex-1">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300 whitespace-nowrap">
                Select Conversation:
              </label>
              <Select
                className="flex-1 max-w-md"
                placeholder="Select a conversation"
                value={selectedConversationId}
                onChange={setSelectedConversationId}
                loading={loading}
                options={conversations.map((conv) => ({
                  value: conv.id,
                  label: (
                    <div className="flex items-center justify-between">
                      <span className="truncate">{conv.title || `Conversation ${conv.id.slice(0, 8)}`}</span>
                      <span className="text-xs text-slate-400 ml-2">
                        {conv.message_count} messages
                      </span>
                    </div>
                  ),
                }))}
              />
            </div>

            {/* Expand/Collapse Controls */}
            {executions.length > 0 && (
              <div className="flex gap-2">
                <button
                  onClick={expandAll}
                  className="px-3 py-1.5 text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
                >
                  Expand All
                </button>
                <button
                  onClick={collapseAll}
                  className="px-3 py-1.5 text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
                >
                  Collapse All
                </button>
              </div>
            )}
          </div>

          {/* Filters */}
          <div className="flex items-center gap-4 pt-4 border-t border-slate-200 dark:border-slate-700">
            <div className="flex items-center gap-2">
              <label className="text-sm text-slate-600 dark:text-slate-400">Status:</label>
              <Select
                className="w-40"
                placeholder="All statuses"
                allowClear
                value={statusFilter}
                onChange={setStatusFilter}
                options={[
                  { value: 'COMPLETED', label: 'Completed' },
                  { value: 'FAILED', label: 'Failed' },
                  { value: 'THINKING', label: 'Thinking' },
                  { value: 'ACTING', label: 'Acting' },
                  { value: 'OBSERVING', label: 'Observing' },
                ]}
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-sm text-slate-600 dark:text-slate-400">Tool:</label>
              <Select
                className="w-48"
                placeholder="All tools"
                allowClear
                value={toolFilter}
                onChange={setToolFilter}
                options={Array.from(new Set(executions.map(e => e.tool_name).filter(Boolean))).map(tool => ({
                  value: tool,
                  label: tool,
                }))}
              />
            </div>
            {(statusFilter || toolFilter) && (
              <Button
                size="small"
                onClick={() => {
                  setStatusFilter(undefined);
                  setToolFilter(undefined);
                }}
              >
                Clear Filters
              </Button>
            )}
          </div>
        </div>

        {/* Statistics */}
        {stats && !statsLoading && (
          <>
            <ExecutionStatsCard stats={stats} />
            <ExecutionTimelineChart stats={stats} />
          </>
        )}

        {/* Execution History */}
        {loading || executionsLoading ? (
          <div className="space-y-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
                <Skeleton active paragraph={{ rows: 2 }} />
              </div>
            ))}
          </div>
        ) : executions.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              selectedConversationId
                ? 'No execution history found for this conversation'
                : 'Select a conversation to view execution logs'
            }
          />
        ) : (
          <div className="space-y-4">
            {executions.map((execution) => (
              <ExecutionCard
                key={execution.id}
                execution={execution}
                isExpanded={expandedIds.has(execution.id)}
                onToggle={() => toggleExpand(execution.id)}
              />
            ))}
          </div>
        )}

        {/* Stats Summary */}
        {executions.length > 0 && (
          <div className="mt-6 grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
              <div className="flex items-center gap-2 mb-1">
                <MaterialIcon name="check_circle" size={16} className="text-emerald-500" />
                <span className="text-sm text-slate-500">Completed</span>
              </div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">
                {executions.filter((e) => e.status === 'completed').length}
              </p>
            </div>
            <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
              <div className="flex items-center gap-2 mb-1">
                <MaterialIcon name="error" size={16} className="text-red-500" />
                <span className="text-sm text-slate-500">Failed</span>
              </div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">
                {executions.filter((e) => e.status === 'failed').length}
              </p>
            </div>
            <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
              <div className="flex items-center gap-2 mb-1">
                <MaterialIcon name="build" size={16} className="text-amber-500" />
                <span className="text-sm text-slate-500">Tool Calls</span>
              </div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">
                {executions.filter((e) => e.tool_name).length}
              </p>
            </div>
            <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
              <div className="flex items-center gap-2 mb-1">
                <MaterialIcon name="auto_awesome" size={16} className="text-purple-500" />
                <span className="text-sm text-slate-500">Pattern Matches</span>
              </div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">
                {executions.filter((e) => e.workflow_pattern_id).length}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default AgentLogs;
