/**
 * PatternInspector - Detail view for a selected workflow pattern
 *
 * Shows pattern details with JSON code viewer and admin notes.
 */

import { useState, useCallback, useMemo } from 'react';

import { MaterialIcon } from '../shared';

import type { PatternDefinition } from './PatternList';

export interface PatternInspectorProps {
  /** Pattern to display */
  pattern?: {
    id: string;
    name: string;
    signature: string;
    status: 'preferred' | 'active' | 'deprecated';
    avgRuntime?: number | undefined;
    successRate?: number | undefined;
    usageCount?: number | undefined;
    pattern?: PatternDefinition | undefined;
  } | null | undefined;
  /** Callback when close is clicked */
  onClose?: (() => void) | undefined;
  /** Callback when save is clicked */
  onSave?: ((pattern: Record<string, unknown>) => void) | undefined;
  /** Callback when deprecate is clicked */
  onDeprecate?: (() => void) | undefined;
  /** Admin notes value */
  adminNotes?: string | undefined;
  /** Callback when admin notes change */
  onAdminNotesChange?: ((notes: string) => void) | undefined;
}

/**
 * PatternInspector component
 *
 * @example
 * <PatternInspector
 *   pattern={selectedPattern}
 *   onClose={() => setSelected(null)}
 *   onSave={(p) => updatePattern(p)}
 * />
 */
export function PatternInspector({
  pattern,
  onClose,
  onSave,
  onDeprecate,
  adminNotes = '',
  onAdminNotesChange,
}: PatternInspectorProps) {
  const [copied, setCopied] = useState(false);

  // Stable callback for copying JSON to clipboard
  const handleCopyJson = useCallback(() => {
    if (!pattern) return;

    try {
      navigator.clipboard.writeText(JSON.stringify(pattern.pattern, null, 2));
      setCopied(true);
      setTimeout(() => { setCopied(false); }, 2000);
    } catch (error) {
      console.error('Failed to copy JSON:', error);
    }
  }, [pattern]);

  // Memoized status badge component
  const statusBadge = useMemo(() => {
    if (!pattern) return null;

    switch (pattern.status) {
      case 'preferred':
        return (
          <span className="px-2 py-1 rounded-full text-xs font-semibold bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
            Preferred
          </span>
        );
      case 'active':
        return (
          <span className="px-2 py-1 rounded-full text-xs font-semibold bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
            Active
          </span>
        );
      case 'deprecated':
        return (
          <span className="px-2 py-1 rounded-full text-xs font-semibold bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400">
            Deprecated
          </span>
        );
      default:
        return null;
    }
  }, [pattern]);

  if (!pattern) {
    return (
      <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl p-8 flex flex-col items-center justify-center text-center min-h-[400px]">
        <MaterialIcon
          name="account_tree"
          size={48}
          className="text-slate-300 dark:text-slate-700 mb-3"
        />
        <p className="text-slate-500">Select a pattern to view details</p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl flex flex-col h-full">
      {/* Header */}
      <div className="flex items-start justify-between px-6 py-4 border-b border-slate-200 dark:border-border-dark">
        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-3">
            <h2 className="text-lg font-bold text-slate-900 dark:text-white truncate">
              {pattern.name}
            </h2>
            {statusBadge}
          </div>
          <p className="text-xs text-slate-500 font-mono mt-1">{pattern.signature}</p>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2 ml-4">
          {onSave && pattern.pattern && (
            <button
              onClick={() => { onSave?.(pattern.pattern as unknown as Record<string, unknown>); }}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-white text-sm font-medium transition-colors"
            >
              <MaterialIcon name="save" size={16} />
              Save
            </button>
          )}
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 transition-colors"
          >
            <MaterialIcon name="close" size={20} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Metadata Grid */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Status</p>
            {statusBadge}
          </div>
          {pattern.avgRuntime && (
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Avg Runtime</p>
              <p className="text-sm text-slate-900 dark:text-white">{pattern.avgRuntime}ms</p>
            </div>
          )}
          {pattern.successRate !== undefined && (
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Success Rate</p>
              <p className="text-sm text-slate-900 dark:text-white">{pattern.successRate}%</p>
            </div>
          )}
          {pattern.usageCount !== undefined && (
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Usage Count</p>
              <p className="text-sm text-slate-900 dark:text-white">
                {pattern.usageCount.toLocaleString()}
              </p>
            </div>
          )}
        </div>

        {/* JSON Pattern Definition */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
              Pattern Definition
            </h3>
            <button
              onClick={handleCopyJson}
              className="flex items-center gap-1 px-2 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 transition-colors text-xs"
            >
              <MaterialIcon name={copied ? 'check' : 'content_copy'} size={14} />
              {copied ? 'Copied!' : 'Copy JSON'}
            </button>
          </div>

          {/* Code Block */}
          <div className="bg-slate-900 dark:bg-slate-950 rounded-lg p-4 overflow-x-auto code-scroll">
            <pre className="text-xs text-slate-300 font-mono whitespace-pre-wrap">
              {JSON.stringify(pattern.pattern, null, 2)}
            </pre>
          </div>
        </div>

        {/* Admin Notes */}
        {onAdminNotesChange && (
          <div>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white mb-2">
              Admin Notes
            </h3>
            <textarea
              value={adminNotes}
              onChange={(e) => { onAdminNotesChange(e.target.value); }}
              placeholder="Add notes about this pattern..."
              className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-border-dark bg-white dark:bg-surface-dark text-slate-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary resize-none"
              rows={4}
            />
          </div>
        )}
      </div>

      {/* Footer */}
      {onDeprecate && (
        <div className="px-6 py-4 border-t border-slate-200 dark:border-border-dark">
          <button
            onClick={onDeprecate}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors text-sm font-medium"
          >
            <MaterialIcon name="delete" size={18} />
            Deprecate Pattern
          </button>
        </div>
      )}
    </div>
  );
}

export default PatternInspector;
