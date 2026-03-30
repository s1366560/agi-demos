/**
 * ExportActions - Export action buttons for agent reports
 *
 * Provides Copy to Clipboard, Export to PDF, and Share functionality.
 */

import { useState } from 'react';

import { Check, Copy, Hourglass, FileDown, Share2 } from 'lucide-react';

export interface ExportActionsProps {
  /** Content to export */
  content?: string | undefined;
  /** Element to capture for PDF export */
  elementId?: string | undefined;
  /** Conversation ID for sharing */
  conversationId?: string | undefined;
  /** Filename for PDF export */
  filename?: string | undefined;
  /** Whether to show labels alongside icons */
  showLabels?: boolean | undefined;
  /** Position variant (sidebar | inline) */
  variant?: 'sidebar' | 'inline' | undefined;
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
      setTimeout(() => {
        setCopied(false);
      }, 2000);
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
      setTimeout(() => {
        setCopied(false);
      }, 2000);
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
        type="button"
        onClick={handleCopy}
        disabled={!content}
        className={buttonClass}
        aria-label={copied ? 'Copied to clipboard' : 'Copy to clipboard'}
        title="Copy to clipboard"
      >
        {copied ? <Check size={18} /> : <Copy size={18} />}
        {showLabels && <span className="text-sm font-medium">{copied ? 'Copied!' : 'Copy'}</span>}
      </button>

      {/* Export to PDF */}
      <button
        type="button"
        onClick={handleExportPDF}
        disabled={exporting}
        className={buttonClass}
        aria-label={exporting ? 'Exporting PDF' : 'Export as PDF'}
        title="Export to PDF"
      >
        {exporting ? <Hourglass size={18} /> : <FileDown size={18} />}
        {showLabels && (
          <span className="text-sm font-medium">{exporting ? 'Exporting...' : 'PDF'}</span>
        )}
      </button>

      {/* Share */}
      <button
        type="button"
        onClick={handleShare}
        disabled={!conversationId}
        className={buttonClass}
        aria-label={copied ? 'Link copied' : 'Share conversation link'}
        title="Share link"
      >
        {copied ? <Check size={18} /> : <Share2 size={18} />}
        {showLabels && (
          <span className="text-sm font-medium">{copied ? 'Link copied!' : 'Share'}</span>
        )}
      </button>
    </div>
  );
}

export default ExportActions;
