/**
 * FinalResponseDisplay - Agent's final response with action sidebar
 *
 * Matches the design from docs/statics/project workbench/agent/finished/
 * Features prose-styled content with export actions sidebar.
 * Now uses ReactMarkdown with GFM support for proper rendering.
 */

import { useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';

import { message } from 'antd';
import { Check, Copy, Download, Share2, Clock } from 'lucide-react';

import { formatDateOnly } from '@/utils/date';

import { MARKDOWN_PROSE_CLASSES } from '../styles';

import { CodeBlock } from './CodeBlock';
import { useMarkdownPlugins } from './markdownPlugins';
import { safeMarkdownComponents } from './safeMarkdownComponents';

const MARKDOWN_COMPONENTS: Components = {
  ...safeMarkdownComponents,
  pre: ({ children, ...props }) => <CodeBlock {...props}>{children}</CodeBlock>,
};

export interface FinalResponseDisplayProps {
  /** Report content (markdown) */
  content: string;
  /** Report version */
  version?: string | undefined;
  /** Generation timestamp */
  generatedAt?: string | undefined;
  /** Whether currently streaming (shows typing cursor) */
  isStreaming?: boolean | undefined;
}

/**
 * FinalResponseDisplay component
 *
 * @example
 * <FinalResponseDisplay
 *   content="# Analysis Report\n\n## Summary..."
 *   version="v1.0 Final"
 *   generatedAt="2024-01-13T10:30:00Z"
 * />
 */
export function FinalResponseDisplay({ content, version, generatedAt }: FinalResponseDisplayProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(content);
  const displayVersion =
    version ?? t('components.finalResponseDisplay.defaultVersion', { defaultValue: 'v1.0 Final' });

  // Format timestamp
  const formatTimeAgo = (isoString: string) => {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = Math.max(0, now.getTime() - date.getTime());
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 60) {
      return t('components.finalResponseDisplay.time.minutesAgo', {
        defaultValue: '{{count}}m ago',
        count: diffMins,
      });
    }
    const diffHours = Math.floor(diffMs / 3600000);
    if (diffHours < 24) {
      return t('components.finalResponseDisplay.time.hoursAgo', {
        defaultValue: '{{count}}h ago',
        count: diffHours,
      });
    }
    return formatDateOnly(date);
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      void message.success(
        t('components.finalResponseDisplay.copySuccess', { defaultValue: 'Copied to clipboard' })
      );
      setTimeout(() => {
        setCopied(false);
      }, 2000);
    } catch {
      void message.error(
        t('components.finalResponseDisplay.copyFailed', { defaultValue: 'Copy failed' })
      );
    }
  };

  const handleExportPDF = async () => {
    if (!contentRef.current) {
      void message.error(
        t('components.finalResponseDisplay.exportTargetMissing', {
          defaultValue: 'Nothing available to export',
        })
      );
      return;
    }

    setIsExporting(true);
    try {
      const element = contentRef.current;
      const opt = {
        margin: [10, 10, 10, 10] as [number, number, number, number],
        filename: `memstack-report-${new Date().toISOString().slice(0, 10)}.pdf`,
        image: { type: 'jpeg' as const, quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' as const },
      };

      const html2pdf = (await import('html2pdf.js')).default;
      await html2pdf().set(opt).from(element).save();
    } catch {
      void message.error(
        t('components.finalResponseDisplay.exportFailed', { defaultValue: 'Failed to export PDF' })
      );
    } finally {
      setIsExporting(false);
    }
  };

  const handleShare = async () => {
    const shareData = {
      title: t('components.finalResponseDisplay.shareTitle', { defaultValue: 'MemStack Report' }),
      text: t('components.finalResponseDisplay.shareText', {
        defaultValue: 'Check out this report from MemStack',
      }),
      url: window.location.href,
    };

    if (
      typeof navigator.share === 'function' &&
      (typeof navigator.canShare !== 'function' || navigator.canShare(shareData))
    ) {
      try {
        await navigator.share(shareData);
      } catch (err) {
        if (!(err instanceof DOMException && err.name === 'AbortError')) {
          void message.error(
            t('components.finalResponseDisplay.shareFailed', { defaultValue: 'Share failed' })
          );
        }
      }
    } else {
      // Fallback to copying URL
      try {
        await navigator.clipboard.writeText(window.location.href);
        void message.success(
          t('components.finalResponseDisplay.linkCopied', {
            defaultValue: 'Link copied to clipboard',
          })
        );
      } catch {
        void message.error(
          t('components.finalResponseDisplay.copyLinkFailed', {
            defaultValue: 'Failed to copy share link',
          })
        );
      }
    }
  };

  return (
    <div className="flex-1 flex flex-col lg:flex-row gap-6 pb-12">
      {/* Main Content */}
      <div
        ref={contentRef}
        className={`flex-1 min-w-0 bg-slate-50 dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-md rounded-tl-none shadow-sm p-8 ${MARKDOWN_PROSE_CLASSES} text-slate-800 dark:text-slate-200`}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-8 border-b border-slate-100 dark:border-border-dark pb-4 -mt-4">
          <h2 className="m-0 text-2xl">
            {t('components.finalResponseDisplay.title', {
              defaultValue: 'Final Synthesis Report',
            })}
          </h2>
          {displayVersion && (
            <span className="text-2xs px-2 py-1 bg-primary/10 text-primary rounded font-bold uppercase">
              {displayVersion}
            </span>
          )}
        </div>

        {/* Content with ReactMarkdown */}
        <ReactMarkdown
          remarkPlugins={remarkPlugins}
          rehypePlugins={rehypePlugins}
          components={MARKDOWN_COMPONENTS}
        >
          {content}
        </ReactMarkdown>
      </div>

      {/* Action Sidebar */}
      <div className="w-72 shrink-0 space-y-4 data-[html2canvas-ignore]:hidden">
        <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-md p-4 shadow-sm sticky top-6">
          <h3 className="text-2xs font-bold text-text-muted uppercase tracking-wider mb-4">
            {t('components.finalResponseDisplay.actions', { defaultValue: 'Actions' })}
          </h3>
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => {
                void handleCopy();
              }}
              className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-700 dark:text-slate-200 bg-white dark:bg-surface-dark hover:bg-slate-50 dark:hover:bg-slate-800 rounded-md transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 border border-slate-200 dark:border-border-dark hover:border-primary dark:hover:border-primary hover:shadow-md cursor-pointer"
            >
              {copied ? <Check className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
              {copied
                ? t('components.finalResponseDisplay.copied', { defaultValue: 'Copied!' })
                : t('components.finalResponseDisplay.copyToClipboard', {
                    defaultValue: 'Copy to Clipboard',
                  })}
            </button>

            <button
              type="button"
              onClick={() => {
                void handleExportPDF();
              }}
              disabled={isExporting}
              className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-700 dark:text-slate-200 bg-white dark:bg-surface-dark hover:bg-slate-50 dark:hover:bg-slate-800 rounded-md transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 border border-slate-200 dark:border-border-dark hover:border-primary dark:hover:border-primary hover:shadow-md cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className="w-4 h-4" />
              {isExporting
                ? t('components.finalResponseDisplay.exporting', { defaultValue: 'Exporting…' })
                : t('components.finalResponseDisplay.exportAsPdf', {
                    defaultValue: 'Export as PDF',
                  })}
            </button>

            <button
              type="button"
              onClick={() => {
                void handleShare();
              }}
              className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-700 dark:text-slate-200 bg-white dark:bg-surface-dark hover:bg-slate-50 dark:hover:bg-slate-800 rounded-md transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 border border-slate-200 dark:border-border-dark hover:border-primary dark:hover:border-primary hover:shadow-md cursor-pointer"
            >
              <Share2 className="w-4 h-4" />
              {t('components.finalResponseDisplay.shareWithTeam', {
                defaultValue: 'Share with Team',
              })}
            </button>
          </div>

          {generatedAt && (
            <div className="mt-4 pt-4 border-t border-slate-100 dark:border-border-dark">
              <div className="flex items-center gap-2 text-text-muted">
                <Clock className="w-4 h-4" />
                <span className="text-2xs">
                  {t('components.finalResponseDisplay.generated', {
                    defaultValue: 'Generated {{time}}',
                    time: formatTimeAgo(generatedAt),
                  })}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default FinalResponseDisplay;
