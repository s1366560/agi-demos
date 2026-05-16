/**
 * ExportActions - Export action buttons for agent reports
 *
 * Provides Copy to Clipboard, Export to PDF, and Share functionality.
 */

import { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { message } from 'antd';
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
  const { t } = useTranslation();
  const [copiedTarget, setCopiedTarget] = useState<'content' | 'link' | null>(null);
  const [exporting, setExporting] = useState(false);

  const markCopied = (target: 'content' | 'link') => {
    setCopiedTarget(target);
    setTimeout(() => {
      setCopiedTarget(null);
    }, 2000);
  };

  const handleCopy = async () => {
    if (!content) return;

    try {
      await navigator.clipboard.writeText(content);
      markCopied('content');
      void message.success(
        t('components.exportActions.copySuccess', { defaultValue: 'Copied to clipboard' })
      );
    } catch {
      void message.error(t('components.exportActions.copyFailed', { defaultValue: 'Copy failed' }));
    }
  };

  const handleExportPDF = async () => {
    setExporting(true);
    try {
      // Dynamic import to avoid loading html2pdf until needed
      const html2pdf = (await import('html2pdf.js')).default;

      const element = elementId ? document.getElementById(elementId) : document.body;

      if (element) {
        await html2pdf()
          .from(element)
          .set({
            margin: 10,
            filename: `${filename}.pdf`,
            image: { type: 'jpeg', quality: 0.98 },
            html2canvas: { scale: 2 },
            jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
          })
          .save();
      } else {
        void message.error(
          t('components.exportActions.exportTargetMissing', {
            defaultValue: 'Nothing available to export',
          })
        );
      }
    } catch {
      void message.error(
        t('components.exportActions.exportFailed', { defaultValue: 'Failed to export PDF' })
      );
    } finally {
      setExporting(false);
    }
  };

  const handleShare = async () => {
    if (!conversationId) return;

    try {
      const url = `${window.location.origin}/shared/${conversationId}`;
      await navigator.clipboard.writeText(url);
      markCopied('link');
      void message.success(
        t('components.exportActions.linkCopiedSuccess', { defaultValue: 'Link copied' })
      );
    } catch {
      void message.error(
        t('components.exportActions.shareFailed', { defaultValue: 'Failed to copy share link' })
      );
    }
  };

  const buttonClass =
    variant === 'sidebar'
      ? 'flex items-center gap-2 px-3 py-2 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400 transition-colors w-full text-left'
      : 'flex items-center gap-2 px-3 py-2 rounded-md border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400 transition-colors';

  return (
    <div className={variant === 'sidebar' ? 'space-y-1' : 'flex items-center gap-2'}>
      {/* Copy to Clipboard */}
      <button
        type="button"
        onClick={() => {
          void handleCopy();
        }}
        disabled={!content}
        className={buttonClass}
        aria-label={
          copiedTarget === 'content'
            ? t('components.exportActions.copiedAria', { defaultValue: 'Copied to clipboard' })
            : t('components.exportActions.copyAria', { defaultValue: 'Copy to clipboard' })
        }
        title={t('components.exportActions.copyAria', { defaultValue: 'Copy to clipboard' })}
      >
        {copiedTarget === 'content' ? <Check size={18} /> : <Copy size={18} />}
        {showLabels && (
          <span className="text-sm font-medium">
            {copiedTarget === 'content'
              ? t('components.exportActions.copied', { defaultValue: 'Copied!' })
              : t('common.copy', { defaultValue: 'Copy' })}
          </span>
        )}
      </button>

      {/* Export to PDF */}
      <button
        type="button"
        onClick={() => {
          void handleExportPDF();
        }}
        disabled={exporting}
        className={buttonClass}
        aria-label={
          exporting
            ? t('components.exportActions.exportingPdf', { defaultValue: 'Exporting PDF' })
            : t('components.exportActions.exportAsPdf', { defaultValue: 'Export as PDF' })
        }
        title={t('components.exportActions.exportToPdf', { defaultValue: 'Export to PDF' })}
      >
        {exporting ? <Hourglass size={18} /> : <FileDown size={18} />}
        {showLabels && (
          <span className="text-sm font-medium">
            {exporting
              ? t('components.exportActions.exporting', { defaultValue: 'Exporting...' })
              : t('components.exportActions.pdf', { defaultValue: 'PDF' })}
          </span>
        )}
      </button>

      {/* Share */}
      <button
        type="button"
        onClick={() => {
          void handleShare();
        }}
        disabled={!conversationId}
        className={buttonClass}
        aria-label={
          copiedTarget === 'link'
            ? t('components.exportActions.linkCopied', { defaultValue: 'Link copied' })
            : t('components.exportActions.shareAria', { defaultValue: 'Share conversation link' })
        }
        title={t('components.exportActions.shareTitle', { defaultValue: 'Share link' })}
      >
        {copiedTarget === 'link' ? <Check size={18} /> : <Share2 size={18} />}
        {showLabels && (
          <span className="text-sm font-medium">
            {copiedTarget === 'link'
              ? t('components.exportActions.linkCopiedLabel', { defaultValue: 'Link copied!' })
              : t('components.exportActions.share', { defaultValue: 'Share' })}
          </span>
        )}
      </button>
    </div>
  );
}

export default ExportActions;
