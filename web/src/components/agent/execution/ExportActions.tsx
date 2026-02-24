/**
 * ExportActions - Export action buttons for agent reports
 *
 * Provides Copy to Clipboard, Export to PDF, and Share functionality.
 */

import { useState } from 'react';

import { MaterialIcon } from '../shared';

export interface ExportActionsProps {
  /** Content to export */
  content?: string;
  /** Element to capture for PDF export */
  elementId?: string;
  /** Conversation ID for sharing */
  conversationId?: string;
  /** Filename for PDF export */
  filename?: string;
  /** Whether to show labels alongside icons */
  showLabels?: boolean;
  /** Position variant (sidebar | inline) */
  variant?: 'sidebar' | 'inline';
}

/**
 * ExportActions component
 *
 * @example
 * <ExportActions
 *   content="# Report Content\n..."
 *   conversationId="abc-123"
 *   onExport={(format) => console.log(format)}
 * />
 */
export function ExportActions({
  content,
  elementId,
  conversationId,
  filename = 'agent-report',
  showLabels = true,
  variant = 'sidebar',
}: ExportActionsProps) {
  const [copied, setCopied] = useState(false);
  const [exporting, setExporting] = useState(false);

  const handleCopy = async () => {
    if (!content) return;

    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => { setCopied(false); }, 2000);
    } catch (error) {
      console.error('Failed to copy:', error);
    }
  };

  const handleExportPDF = async () => {
    setExporting(true);
    try {
      // Dynamic import to avoid loading html2pdf until needed
      const html2pdf = (await import('html2pdf.js')).default;

      const element = elementId ? document.getElementById(elementId) : document.body;

      if (element) {
        html2pdf()
          .from(element)
          .set({
            margin: 10,
            filename: `${filename}.pdf`,
            image: { type: 'jpeg', quality: 0.98 },
            html2canvas: { scale: 2 },
            jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
          })
          .save();
      }
    } catch (error) {
      console.error('Failed to export PDF:', error);
    } finally {
      setExporting(false);
    }
  };

  const handleShare = async () => {
    if (!conversationId) return;

    try {
      const url = `${window.location.origin}/shared/${conversationId}`;
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => { setCopied(false); }, 2000);
    } catch (error) {
      console.error('Failed to share:', error);
    }
  };

  const buttonClass =
    variant === 'sidebar'
      ? 'flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400 transition-colors w-full text-left'
      : 'flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400 transition-colors';

  return (
    <div className={variant === 'sidebar' ? 'space-y-1' : 'flex items-center gap-2'}>
      {/* Copy to Clipboard */}
      <button
        onClick={handleCopy}
        disabled={!content}
        className={buttonClass}
        aria-label={copied ? '已复制到剪贴板' : '复制到剪贴板'}
        title="Copy to clipboard"
      >
        <MaterialIcon name={copied ? 'check' : 'content_copy'} size={18} />
        {showLabels && <span className="text-sm font-medium">{copied ? 'Copied!' : 'Copy'}</span>}
      </button>

      {/* Export to PDF */}
      <button
        onClick={handleExportPDF}
        disabled={exporting}
        className={buttonClass}
        aria-label={exporting ? '正在导出 PDF' : '导出为 PDF'}
        title="Export to PDF"
      >
        <MaterialIcon name={exporting ? 'hourglass_empty' : 'picture_as_pdf'} size={18} />
        {showLabels && (
          <span className="text-sm font-medium">{exporting ? 'Exporting...' : 'PDF'}</span>
        )}
      </button>

      {/* Share */}
      <button
        onClick={handleShare}
        disabled={!conversationId}
        className={buttonClass}
        aria-label={copied ? '链接已复制' : '分享对话链接'}
        title="Share link"
      >
        <MaterialIcon name={copied ? 'check' : 'share'} size={18} />
        {showLabels && (
          <span className="text-sm font-medium">{copied ? 'Link copied!' : 'Share'}</span>
        )}
      </button>
    </div>
  );
}

export default ExportActions;
