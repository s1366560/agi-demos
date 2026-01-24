/**
 * AgentPatterns - Workflow patterns view (Project-level, Read-Only)
 *
 * Displays learned workflow patterns used in this project.
 * All editing and management is done at the tenant level.
 */

import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { message, Skeleton, Empty, Tooltip } from 'antd';
import { MaterialIcon } from '../../../components/agent/shared';
import { PatternList, PatternInspector } from '../../../components/agent';
import type { WorkflowPattern as UIWorkflowPattern, PatternStatus } from '../../../components/agent/patterns/PatternList';
import { patternService, PatternServiceError } from '../../../services/patternService';
import { useProjectStore } from '../../../stores/project';
import type { WorkflowPattern as APIWorkflowPattern } from '../../../types/agent';

/**
 * Convert API pattern to UI pattern format
 */
function toUIPattern(apiPattern: APIWorkflowPattern): UIWorkflowPattern {
  let status: PatternStatus = 'active';
  if (apiPattern.success_rate >= 80) {
    status = 'preferred';
  } else if (apiPattern.success_rate < 50) {
    status = 'deprecated';
  }

  return {
    id: apiPattern.id,
    name: apiPattern.name,
    signature: apiPattern.id.slice(0, 16),
    status,
    usageCount: apiPattern.usage_count,
    successRate: Math.round(apiPattern.success_rate * 100) / 100,
    avgRuntime: apiPattern.metadata?.avg_runtime as number | undefined,
    lastUsed: apiPattern.updated_at,
    pattern: {
      name: apiPattern.name,
      description: apiPattern.description,
      tools: apiPattern.steps.map((s) => s.tool_name),
      steps: apiPattern.steps.map((s) => ({
        tool: s.tool_name,
        params: s.tool_parameters || {},
      })),
    },
  };
}

export const AgentPatterns: React.FC = () => {
  void useParams<{ projectId: string }>(); // projectId available for future use
  const navigate = useNavigate();
  const { currentProject } = useProjectStore();

  const tenantId = currentProject?.tenant_id;

  // State
  const [patterns, setPatterns] = useState<UIWorkflowPattern[]>([]);
  const [selectedPattern, setSelectedPattern] = useState<UIWorkflowPattern | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Load patterns from API
  const fetchPatterns = useCallback(async () => {
    if (!tenantId) return;

    setLoading(true);
    setError(null);

    try {
      const response = await patternService.listPatterns(tenantId);
      const uiPatterns = response.patterns.map(toUIPattern);
      setPatterns(uiPatterns);
    } catch (err) {
      const errorMessage =
        err instanceof PatternServiceError
          ? err.message
          : 'Failed to load patterns';
      setError(errorMessage);
      message.error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    fetchPatterns();
  }, [fetchPatterns]);

  // Filter patterns by search query
  const filteredPatterns = patterns.filter(
    (p) =>
      p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.signature.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Calculate stats
  const totalPatterns = patterns.length;
  const successRate =
    patterns.length > 0
      ? Math.round(patterns.reduce((sum, p) => sum + p.successRate, 0) / patterns.length)
      : 0;
  const preferredCount = patterns.filter((p) => p.status === 'preferred').length;

  const handleSelectPattern = (pattern: UIWorkflowPattern) => {
    setSelectedPattern(pattern);
  };

  const handleManagePatterns = () => {
    if (tenantId) {
      navigate(`/space/${tenantId}/patterns`);
    }
  };

  // Error state
  if (error && !loading) {
    return (
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-6xl mx-auto">
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-16 h-16 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center mb-4">
              <MaterialIcon name="error" size={32} className="text-red-500" />
            </div>
            <h2 className="text-xl font-semibold text-slate-900 dark:text-white mb-2">
              Failed to Load Patterns
            </h2>
            <p className="text-slate-500 dark:text-slate-400 mb-4">{error}</p>
            <button
              onClick={fetchPatterns}
              className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
            >
              Try Again
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center">
                <MaterialIcon name="account_tree" size={24} className="text-purple-600 dark:text-purple-400" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Workflow Patterns</h1>
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  Learned patterns from successful agent executions
                </p>
              </div>
            </div>

            <Tooltip title="Manage patterns at the workspace level">
              <button
                onClick={handleManagePatterns}
                className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors flex items-center gap-2"
              >
                <MaterialIcon name="settings" size={18} />
                Manage All Patterns
              </button>
            </Tooltip>
          </div>
        </div>

        {/* Info Banner */}
        <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4 border border-blue-200 dark:border-blue-800 mb-6">
          <div className="flex items-start gap-3">
            <MaterialIcon name="info" size={20} className="text-blue-600 dark:text-blue-400 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-slate-900 dark:text-white">
                Patterns are shared across your workspace
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                Workflow patterns are learned automatically from successful agent executions and are
                available to all projects in this workspace. To edit or delete patterns, go to the
                workspace-level Patterns management page.
              </p>
            </div>
          </div>
        </div>

        {/* Stats Cards */}
        {loading ? (
          <div className="grid grid-cols-3 gap-4 mb-6">
            {[1, 2, 3].map((i) => (
              <Skeleton.Button key={i} active block style={{ height: 80 }} />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
              <div className="flex items-center gap-2 mb-1">
                <MaterialIcon name="layers" size={16} className="text-slate-400" />
                <span className="text-sm text-slate-500">Total Patterns</span>
              </div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">{totalPatterns}</p>
            </div>
            <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
              <div className="flex items-center gap-2 mb-1">
                <MaterialIcon name="trending_up" size={16} className="text-emerald-500" />
                <span className="text-sm text-slate-500">Avg Success Rate</span>
              </div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">{successRate}%</p>
            </div>
            <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
              <div className="flex items-center gap-2 mb-1">
                <MaterialIcon name="star" size={16} className="text-purple-500" />
                <span className="text-sm text-slate-500">Preferred</span>
              </div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">{preferredCount}</p>
            </div>
          </div>
        )}

        {/* Search */}
        <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-lg px-4 py-2 mb-6">
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-[20px]">
              search
            </span>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search patterns..."
              className="w-full pl-10 pr-4 py-2 rounded-lg border-0 focus:outline-none focus:ring-0 text-sm bg-transparent text-slate-900 dark:text-white placeholder:text-slate-400"
            />
          </div>
        </div>

        {/* Content */}
        {loading ? (
          <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl p-4">
            <Skeleton active paragraph={{ rows: 8 }} />
          </div>
        ) : patterns.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <span className="text-slate-500">
                No patterns learned yet. Patterns are created automatically when the agent
                successfully completes queries.
              </span>
            }
          />
        ) : (
          <div className="flex gap-6">
            {/* Pattern List (Read-Only) */}
            <div className="flex-1 min-w-0">
              <PatternList
                patterns={filteredPatterns}
                selectedId={selectedPattern?.id}
                onSelect={handleSelectPattern}
                // No onDeprecate - read-only mode
                showAllColumns
                allowSelectDeprecated
              />
            </div>

            {/* Pattern Inspector (Read-Only) */}
            {selectedPattern && (
              <div className="w-[400px] shrink-0">
                <PatternInspector
                  pattern={selectedPattern}
                  onClose={() => setSelectedPattern(null)}
                  // No onSave or onDeprecate - read-only mode
                  adminNotes=""
                  onAdminNotesChange={() => {}}
                />
                {/* Read-only overlay message */}
                <div className="mt-2 bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 text-center">
                  <p className="text-xs text-slate-500">
                    <MaterialIcon name="lock" size={12} className="mr-1 align-middle" />
                    Read-only view.{' '}
                    <button
                      onClick={handleManagePatterns}
                      className="text-primary hover:underline"
                    >
                      Manage patterns
                    </button>{' '}
                    at workspace level.
                  </p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default AgentPatterns;
