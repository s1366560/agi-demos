/**
 * FinalReport - Agent final response display with export actions
 *
 * Shows the agent's completed response with markdown rendering and export sidebar.
 */

import { useState, useEffect } from 'react';

import { MaterialIcon } from '../shared';

export interface FinalReportProps {
  /** Report content (markdown or plain text) */
  content?: string;
  /** Report format */
  format?: 'markdown' | 'text';
  /** Generation timestamp */
  timestamp?: string;
  /** Report version identifier */
  version?: string;
  /** Whether to show export sidebar */
  showExport?: boolean;
  /** Conversation ID for sharing */
  conversationId?: string;
  /** Element ID for PDF export */
  elementId?: string;
}

/**
 * FinalReport component
 *
 * @example
 * <FinalReport
 *   content="# Analysis Report\n\n## Summary..."
 *   timestamp="2024-01-13T10:30:00Z"
 *   conversationId="abc-123"
 * />
 */
export function FinalReport({
  content,
  format = 'markdown',
  timestamp,
  version = 'v1.0 Final',
  showExport = true,
  conversationId,
  elementId,
}: FinalReportProps) {
  // Format timestamp for display
  const formatTimestamp = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  // Simple markdown rendering for basic formatting
  const renderContent = (text: string) => {
    if (!text) return null;

    const lines = text.split('\n');
    return lines.map((line, index) => {
      // Headers
      if (line.startsWith('# ')) {
        return (
          <h1 key={index} className="text-xl font-bold text-slate-900 dark:text-white mt-4 mb-2">
            {line.replace('# ', '')}
          </h1>
        );
      }
      if (line.startsWith('## ')) {
        return (
          <h2
            key={index}
            className="text-lg font-semibold text-slate-900 dark:text-white mt-3 mb-2"
          >
            {line.replace('## ', '')}
          </h2>
        );
      }
      if (line.startsWith('### ')) {
        return (
          <h3
            key={index}
            className="text-base font-semibold text-slate-900 dark:text-white mt-2 mb-1"
          >
            {line.replace('### ', '')}
          </h3>
        );
      }

      // Bullet points
      if (line.trim().startsWith('- ')) {
        return (
          <li key={index} className="text-sm text-slate-700 dark:text-slate-300 ml-4">
            {line.trim().replace('- ', '')}
          </li>
        );
      }

      // Bold text
      if (line.includes('**')) {
        const parts = line.split('**');
        return (
          <p key={index} className="text-sm text-slate-700 dark:text-slate-300 mb-1">
            {parts.map((part, i) =>
              i % 2 === 1 ? (
                <strong key={i} className="font-semibold text-slate-900 dark:text-white">
                  {part}
                </strong>
              ) : (
                part
              )
            )}
          </p>
        );
      }

      // Empty line
      if (!line.trim()) {
        return <br key={index} />;
      }

      // Regular paragraph
      return (
        <p key={index} className="text-sm text-slate-700 dark:text-slate-300 mb-1">
          {line}
        </p>
      );
    });
  };

  // Dynamic import ExportActions to avoid circular dependency
  const [ExportActions, setExportActions] = useState<
    typeof import('./ExportActions').ExportActions | null
  >(null);

  useEffect(() => {
    import('./ExportActions').then((mod) => {
      setExportActions(() => mod.ExportActions);
    });
  }, []);

  return (
    <div
      id={elementId}
      className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl overflow-hidden mb-4"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
            <MaterialIcon name="check_circle" size={18} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Final Response</h3>
            {timestamp && (
              <p className="text-xs text-slate-500">Generated {formatTimestamp(timestamp)}</p>
            )}
          </div>
        </div>

        {/* Version Badge */}
        <span className="text-xs bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 px-2 py-1 rounded font-medium">
          {version}
        </span>
      </div>

      {/* Content Area with Export Sidebar */}
      <div className="flex">
        {/* Main Content */}
        <div className="flex-1 p-4 prose prose-sm max-w-none dark:prose-invert">
          {format === 'markdown' ? (
            renderContent(content || '')
          ) : (
            <p className="text-sm whitespace-pre-wrap">{content}</p>
          )}
        </div>

        {/* Export Sidebar */}
        {showExport && ExportActions && (
          <div className="w-12 border-l border-slate-100 dark:border-slate-800 p-2 flex flex-col items-center gap-2 bg-slate-50 dark:bg-slate-900/20">
            <ExportActions
              content={content}
              conversationId={conversationId}
              elementId={elementId}
              showLabels={false}
              variant="sidebar"
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default FinalReport;
