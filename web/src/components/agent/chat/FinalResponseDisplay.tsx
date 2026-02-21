/**
 * FinalResponseDisplay - Agent's final response with action sidebar
 *
 * Matches the design from docs/statics/project workbench/agent/finished/
 * Features prose-styled content with export actions sidebar.
 * Now uses ReactMarkdown with GFM support for proper rendering.
 */

import { useRef, useState } from 'react';

import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';

import { Check, Copy, Download, Share2, Clock } from 'lucide-react';

import { formatDateOnly } from '@/utils/date';

import { MARKDOWN_PROSE_CLASSES } from '../styles';

import { CodeBlock } from './CodeBlock';
import { useMarkdownPlugins } from './markdownPlugins';


const MARKDOWN_COMPONENTS: Components = {
  pre: ({ children, ...props }) => <CodeBlock {...props}>{children}</CodeBlock>,
};

export interface FinalResponseDisplayProps {
  /** Report content (markdown) */
  content: string;
  /** Report version */
  version?: string;
  /** Generation timestamp */
  generatedAt?: string;
  /** Whether currently streaming (shows typing cursor) */
  isStreaming?: boolean;
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
export function FinalResponseDisplay({
  content,
  version = 'v1.0 Final',
  generatedAt,
}: FinalResponseDisplayProps) {
  const [copied, setCopied] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(content);

  // Format timestamp
  const formatTimeAgo = (isoString: string) => {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 3600000);
    if (diffHours < 24) return `${diffHours}h ago`;
    return formatDateOnly(date);
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error('Failed to copy:', error);
    }
  };

  const handleExportPDF = async () => {
    if (!contentRef.current) return;
    
    setIsExporting(true);
    try {
      const element = contentRef.current;
      const opt = {
        margin: [10, 10, 10, 10] as [number, number, number, number],
        filename: `memstack-report-${new Date().toISOString().slice(0, 10)}.pdf`,
        image: { type: 'jpeg' as const, quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' as const }
      };

      // @ts-ignore - html2pdf types might be missing
      // @ts-ignore - Dynamic import
      const html2pdf = (await import('html2pdf.js')).default;
      await html2pdf().set(opt).from(element).save();
    } catch (error) {
      console.error('PDF Export failed:', error);
    } finally {
      setIsExporting(false);
    }
  };

  const handleShare = async () => {
    const shareData = {
      title: 'MemStack Report',
      text: 'Check out this report from MemStack',
      url: window.location.href,
    };

    if (navigator.share && navigator.canShare(shareData)) {
      try {
        await navigator.share(shareData);
      } catch (err) {
        console.error('Share failed:', err);
      }
    } else {
      // Fallback to copying URL
      try {
        await navigator.clipboard.writeText(window.location.href);
        alert('Link copied to clipboard!');
      } catch (err) {
        console.error('Copy link failed:', err);
      }
    }
  };

  return (
    <div className="flex-1 flex flex-col lg:flex-row gap-6 pb-12">
      {/* Main Content */}
      <div 
        ref={contentRef}
        className={`flex-1 min-w-0 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none shadow-xl p-8 ${MARKDOWN_PROSE_CLASSES} text-slate-800 dark:text-slate-200`}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-8 border-b border-slate-100 dark:border-border-dark pb-4 -mt-4">
          <h2 className="m-0 text-2xl">Final Synthesis Report</h2>
          {version && (
            <span className="text-[10px] px-2 py-1 bg-primary/10 text-primary rounded font-bold uppercase">
              {version}
            </span>
          )}
        </div>

        {/* Content with ReactMarkdown */}
        <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={MARKDOWN_COMPONENTS}>
          {content}
        </ReactMarkdown>
      </div>

      {/* Action Sidebar */}
      <div className="w-72 shrink-0 space-y-4 data-[html2canvas-ignore]:hidden">
        <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl p-4 shadow-sm sticky top-6">
          <h4 className="text-[10px] font-bold text-text-muted uppercase tracking-wider mb-4">
            Actions
          </h4>
          <div className="space-y-2">
            <button
              onClick={handleCopy}
              className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-700 dark:text-slate-200 bg-white dark:bg-surface-dark hover:bg-slate-50 dark:hover:bg-slate-800 rounded-lg transition-all duration-200 border border-slate-200 dark:border-border-dark hover:border-primary dark:hover:border-primary hover:shadow-md cursor-pointer"
            >
              {copied ? <Check className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
              {copied ? 'Copied!' : 'Copy to Clipboard'}
            </button>

            <button
              onClick={handleExportPDF}
              disabled={isExporting}
              className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-700 dark:text-slate-200 bg-white dark:bg-surface-dark hover:bg-slate-50 dark:hover:bg-slate-800 rounded-lg transition-all duration-200 border border-slate-200 dark:border-border-dark hover:border-primary dark:hover:border-primary hover:shadow-md cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className="w-4 h-4" />
              {isExporting ? 'Exporting...' : 'Export as PDF'}
            </button>

            <button
              onClick={handleShare}
              className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-700 dark:text-slate-200 bg-white dark:bg-surface-dark hover:bg-slate-50 dark:hover:bg-slate-800 rounded-lg transition-all duration-200 border border-slate-200 dark:border-border-dark hover:border-primary dark:hover:border-primary hover:shadow-md cursor-pointer"
            >
              <Share2 className="w-4 h-4" />
              Share with Team
            </button>
          </div>

          {generatedAt && (
            <div className="mt-4 pt-4 border-t border-slate-100 dark:border-border-dark">
              <div className="flex items-center gap-2 text-text-muted">
                <Clock className="w-4 h-4" />
                <span className="text-[10px]">Generated {formatTimeAgo(generatedAt)}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default FinalResponseDisplay;
