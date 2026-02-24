/**
 * WorkflowPatterns - Workflow Patterns management page
 *
 * Admin interface for managing learned agent patterns.
 * Displays stats, pattern list, and pattern inspector.
 *
 * Note: This page is rendered within TenantLayout, so it only provides
 * the main content area without sidebar/header.
 */

import { useState, useEffect, useCallback } from 'react';

import { useParams } from 'react-router-dom';

import { Modal } from 'antd';

import { useLazyMessage, LazySkeleton, Skeleton as AntSkeleton } from '@/components/ui/lazyAntd';

import {
  PatternStats,
  PatternList,
  PatternInspector,
  type WorkflowPattern as UIWorkflowPattern,
  type PatternStatus,
} from '../../components/agent';
import { MaterialIcon } from '../../components/agent/shared';
import { patternService, PatternServiceError } from '../../services/patternService';

import type { WorkflowPattern as APIWorkflowPattern } from '../../types/agent';

/**
 * Convert API pattern to UI pattern format
 */
function toUIPattern(apiPattern: APIWorkflowPattern): UIWorkflowPattern {
  // Determine status based on success_rate
  let status: PatternStatus = 'active';
  if (apiPattern.success_rate >= 80) {
    status = 'preferred';
  } else if (apiPattern.success_rate < 50) {
    status = 'deprecated';
  }

  return {
    id: apiPattern.id,
    name: apiPattern.name,
    signature: apiPattern.id.slice(0, 16), // Use part of ID as signature
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

/**
 * WorkflowPatterns page component
 *
 * Route: /space/:tenantId/patterns
 * Rendered within TenantLayout
 */

export function WorkflowPatterns() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const message = useLazyMessage();

  // Data state
  const [patterns, setPatterns] = useState<UIWorkflowPattern[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // UI state
  const [selectedPattern, setSelectedPattern] = useState<UIWorkflowPattern | null>(null);
  const [adminNotes, setAdminNotes] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<'name' | 'usage' | 'success'>('usage');
  const [deleting, setDeleting] = useState(false);
  void deleting; // Used in handleDeprecatePattern

  // Fetch patterns from API
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
        err instanceof PatternServiceError ? err.message : 'Failed to load patterns';
      setError(errorMessage);
      message?.error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [tenantId, message]);

  // Load patterns on mount
  useEffect(() => {
    fetchPatterns();
  }, [fetchPatterns]);

  // Calculate stats from patterns
  const totalPatterns = patterns.length;
  const successRate =
    patterns.length > 0
      ? Math.round(patterns.reduce((sum, p) => sum + p.successRate, 0) / patterns.length)
      : 0;
  const deprecatedCount = patterns.filter((p) => p.status === 'deprecated').length;

  // Filter and sort patterns
  const filteredPatterns = patterns
    .filter(
      (p) =>
        p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.signature.toLowerCase().includes(searchQuery.toLowerCase())
    )
    .sort((a, b) => {
      switch (sortBy) {
        case 'name':
          return a.name.localeCompare(b.name);
        case 'usage':
          return b.usageCount - a.usageCount;
        case 'success':
          return b.successRate - a.successRate;
        default:
          return 0;
      }
    });

  const handleSelectPattern = (pattern: UIWorkflowPattern) => {
    setSelectedPattern(pattern);
    setAdminNotes('');
  };

  const handleSavePattern = (_updatedPattern: Record<string, unknown>) => {
    message?.info('Pattern update is not yet implemented');
  };

  const handleDeprecatePattern = async (patternId: string) => {
    if (!tenantId) return;

    Modal.confirm({
      title: 'Delete Pattern',
      content: 'Are you sure you want to delete this pattern? This action cannot be undone.',
      okText: 'Delete',
      okType: 'danger',
      cancelText: 'Cancel',
      onOk: async () => {
        setDeleting(true);
        try {
          await patternService.deletePattern(patternId, tenantId);
          message?.success('Pattern deleted successfully');

          // Remove from local state
          setPatterns((prev) => prev.filter((p) => p.id !== patternId));

          // Clear selection if deleted pattern was selected
          if (selectedPattern?.id === patternId) {
            setSelectedPattern(null);
          }
        } catch (err) {
          const errorMessage =
            err instanceof PatternServiceError ? err.message : 'Failed to delete pattern';
          message?.error(errorMessage);
        } finally {
          setDeleting(false);
        }
      },
    });
  };

  const handleNewPattern = () => {
    message?.info(
      'Pattern creation is not yet implemented. Patterns are learned automatically from successful agent executions.'
    );
  };

  // Error state
  if (error && !loading) {
    return (
      <div className="max-w-full mx-auto">
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
    );
  }

  return (
    <div className="max-w-full mx-auto">
      {/* Page Heading & Actions */}
      <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
        <div>
          <h2 className="text-3xl font-black text-slate-900 dark:text-white tracking-tight">
            Workflow Patterns
          </h2>
          <p className="text-slate-500 dark:text-slate-400 mt-1 max-w-2xl">
            Audit, optimize, and manage the AI agent's learned execution behaviors and strategies.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={fetchPatterns}
            disabled={loading}
            className="px-4 py-2.5 rounded-lg text-sm font-medium border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[18px] align-middle mr-1">refresh</span>
            Refresh
          </button>
          <button
            onClick={handleNewPattern}
            className="bg-primary hover:bg-primary/90 text-white px-4 py-2.5 rounded-lg text-sm font-bold flex items-center gap-2 shadow-lg shadow-primary/20 transition-all"
          >
            <span className="material-symbols-outlined text-[20px]">add</span>
            Define New Pattern
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      {loading ? (
        <div className="grid grid-cols-3 gap-4 mb-6">
          {[1, 2, 3].map((i) => (
            <AntSkeleton.Button key={i} active block style={{ height: 100 }} />
          ))}
        </div>
      ) : (
        <PatternStats
          totalPatterns={totalPatterns}
          totalTrend={0}
          successRate={successRate}
          successTrend={0}
          deprecatedCount={deprecatedCount}
          deprecatedTrend={0}
        />
      )}

      {/* Toolbar */}
      <div className="flex items-center gap-3 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-lg px-4 py-2 my-6">
        {/* Search */}
        <div className="relative flex-1">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-[20px]">
            search
          </span>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => { setSearchQuery(e.target.value); }}
            placeholder="Search patterns..."
            className="w-full pl-10 pr-4 py-2 rounded-lg border-0 focus:outline-none focus:ring-0 text-sm bg-transparent text-slate-900 dark:text-white placeholder:text-slate-400"
          />
        </div>

        {/* Filter */}
        <select
          value={sortBy}
          onChange={(e) => { setSortBy(e.target.value as 'name' | 'usage' | 'success'); }}
          className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-surface-dark text-slate-700 dark:text-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          <option value="usage">Sort by Usage</option>
          <option value="success">Sort by Success Rate</option>
          <option value="name">Sort by Name</option>
        </select>
      </div>

      {/* Split View: List + Inspector */}
      <div className="flex gap-6">
        {/* Pattern List */}
        <div className="flex-1 min-w-0">
          {loading ? (
            <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl p-4">
              <LazySkeleton active paragraph={{ rows: 8 }} />
            </div>
          ) : (
            <PatternList
              patterns={filteredPatterns}
              selectedId={selectedPattern?.id}
              onSelect={handleSelectPattern}
              onDeprecate={handleDeprecatePattern}
              showAllColumns
            />
          )}
        </div>

        {/* Pattern Inspector */}
        <div className="w-[480px] shrink-0">
          <PatternInspector
            pattern={selectedPattern}
            onClose={() => { setSelectedPattern(null); }}
            onSave={handleSavePattern}
            onDeprecate={() => selectedPattern && handleDeprecatePattern(selectedPattern.id)}
            adminNotes={adminNotes}
            onAdminNotesChange={setAdminNotes}
          />
        </div>
      </div>
    </div>
  );
}

export default WorkflowPatterns;
