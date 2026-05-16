/**
 * PatternInspector - Detail view for a selected workflow pattern
 *
 * Shows pattern details with JSON code viewer and admin notes.
 */

import { useState, useCallback, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { message } from 'antd';
import { Network, Save, X, Check, Copy, Trash2 } from 'lucide-react';

import type { PatternDefinition } from './PatternList';

export interface PatternInspectorProps {
  /** Pattern to display */
  pattern?:
    | {
        id: string;
        name: string;
        signature: string;
        status: 'preferred' | 'active' | 'deprecated';
        avgRuntime?: number | undefined;
        successRate?: number | undefined;
        usageCount?: number | undefined;
        pattern?: PatternDefinition | undefined;
      }
    | null
    | undefined;
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
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  // Stable callback for copying JSON to clipboard
  const handleCopyJson = useCallback(async () => {
    if (!pattern) return;

    try {
      await navigator.clipboard.writeText(JSON.stringify(pattern.pattern, null, 2));
      setCopied(true);
      void message.success(
        t('components.patternInspector.copySuccess', { defaultValue: 'Copied to clipboard' })
      );
      setTimeout(() => {
        setCopied(false);
      }, 2000);
    } catch {
      void message.error(
        t('components.patternInspector.copyFailed', { defaultValue: 'Copy failed' })
      );
    }
  }, [pattern, t]);

  // Memoized status badge component
  const statusBadge = useMemo(() => {
    if (!pattern) return null;

    switch (pattern.status) {
      case 'preferred':
        return (
          <span className="px-2 py-1 rounded-full text-xs font-semibold bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
            {t('components.patternInspector.status.preferred', { defaultValue: 'Preferred' })}
          </span>
        );
      case 'active':
        return (
          <span className="px-2 py-1 rounded-full text-xs font-semibold bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
            {t('components.patternInspector.status.active', { defaultValue: 'Active' })}
          </span>
        );
      case 'deprecated':
        return (
          <span className="px-2 py-1 rounded-full text-xs font-semibold bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400">
            {t('components.patternInspector.status.deprecated', { defaultValue: 'Deprecated' })}
          </span>
        );
      default:
        return null;
    }
  }, [pattern, t]);

  if (!pattern) {
    return (
      <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-md p-8 flex flex-col items-center justify-center text-center min-h-[400px]">
        <Network size={48} className="text-slate-300 dark:text-slate-700 mb-3" />
        <p className="text-slate-500">
          {t('components.patternInspector.empty', {
            defaultValue: 'Select a pattern to view details',
          })}
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-md flex flex-col h-full">
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
              type="button"
              onClick={() => {
                onSave(pattern.pattern as unknown as Record<string, unknown>);
              }}
              className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-primary hover:bg-primary/90 text-white text-sm font-medium transition-colors"
            >
              <Save size={16} />
              {t('common.save', { defaultValue: 'Save' })}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 transition-colors"
          >
            <X size={20} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Metadata Grid */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
              {t('components.patternInspector.labels.status', { defaultValue: 'Status' })}
            </p>
            {statusBadge}
          </div>
          {pattern.avgRuntime && (
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                {t('components.patternInspector.labels.avgRuntime', {
                  defaultValue: 'Avg Runtime',
                })}
              </p>
              <p className="text-sm text-slate-900 dark:text-white">{pattern.avgRuntime}ms</p>
            </div>
          )}
          {pattern.successRate !== undefined && (
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                {t('components.patternInspector.labels.successRate', {
                  defaultValue: 'Success Rate',
                })}
              </p>
              <p className="text-sm text-slate-900 dark:text-white">{pattern.successRate}%</p>
            </div>
          )}
          {pattern.usageCount !== undefined && (
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                {t('components.patternInspector.labels.usageCount', {
                  defaultValue: 'Usage Count',
                })}
              </p>
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
              {t('components.patternInspector.patternDefinition', {
                defaultValue: 'Pattern Definition',
              })}
            </h3>
            <button
              type="button"
              onClick={() => {
                void handleCopyJson();
              }}
              aria-label={t('components.patternInspector.copyJson', { defaultValue: 'Copy JSON' })}
              className="flex items-center gap-1 px-2 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 transition-colors text-xs"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
              {copied
                ? t('components.patternInspector.copied', { defaultValue: 'Copied!' })
                : t('components.patternInspector.copyJson', { defaultValue: 'Copy JSON' })}
            </button>
          </div>

          {/* Code Block */}
          <div className="bg-slate-900 dark:bg-slate-950 rounded-md p-4 overflow-x-auto code-scroll">
            <pre className="text-xs text-slate-300 font-mono whitespace-pre-wrap">
              {JSON.stringify(pattern.pattern, null, 2)}
            </pre>
          </div>
        </div>

        {/* Admin Notes */}
        {onAdminNotesChange && (
          <div>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white mb-2">
              {t('components.patternInspector.adminNotes', { defaultValue: 'Admin Notes' })}
            </h3>
            <textarea
              value={adminNotes}
              onChange={(e) => {
                onAdminNotesChange(e.target.value);
              }}
              placeholder={t('components.patternInspector.adminNotesPlaceholder', {
                defaultValue: 'Add notes about this pattern...',
              })}
              className="w-full px-3 py-2 rounded-md border border-slate-200 dark:border-border-dark bg-white dark:bg-surface-dark text-slate-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary resize-none"
              rows={4}
            />
          </div>
        )}
      </div>

      {/* Footer */}
      {onDeprecate && (
        <div className="px-6 py-4 border-t border-slate-200 dark:border-border-dark">
          <button
            type="button"
            onClick={onDeprecate}
            className="flex items-center gap-2 px-3 py-2 rounded-md text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors text-sm font-medium"
          >
            <Trash2 size={18} />
            {t('components.patternInspector.deletePattern', { defaultValue: 'Delete Pattern' })}
          </button>
        </div>
      )}
    </div>
  );
}

export default PatternInspector;
