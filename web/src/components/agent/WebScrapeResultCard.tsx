/**
 * WebScrapeResultCard component
 *
 * Displays scraped web page content.
 */

import { MaterialIcon } from './shared';

export interface WebScrapeResultCardProps {
  title: string;
  url: string;
  description?: string;
  content: string;
}

export function WebScrapeResultCard({
  title,
  url,
  description,
  content,
}: WebScrapeResultCardProps) {
  const handleCopy = () => {
    navigator.clipboard.writeText(content);
  };

  const isTruncated = content.includes('(content truncated)');

  return (
    <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl overflow-hidden mb-4">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <MaterialIcon name="description" size={18} className="text-purple-500" />
          <span className="font-semibold text-slate-900 dark:text-white">Scraped Content</span>
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
        >
          <MaterialIcon name="content_copy" size={14} />
          Copy
        </button>
      </div>

      {/* Content */}
      <div className="p-4 space-y-3">
        {/* Title */}
        <h3 className="text-base font-semibold text-slate-900 dark:text-white">{title}</h3>

        {/* URL */}
        <div className="flex items-center gap-1 text-sm">
          <MaterialIcon name="link" size={14} className="text-slate-400" />
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-500 hover:underline truncate"
          >
            {url}
          </a>
        </div>

        {/* Description */}
        {description && <p className="text-sm text-slate-600 dark:text-slate-400">{description}</p>}

        {/* Content */}
        <div className="bg-slate-100 dark:bg-slate-900 rounded-lg p-3 max-h-80 overflow-y-auto">
          <pre className="text-xs text-slate-700 dark:text-slate-300 whitespace-pre-wrap break-words font-sans">
            {content}
          </pre>
        </div>

        {/* Truncated Notice */}
        {isTruncated && (
          <div className="flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
            <MaterialIcon name="info" size={12} />
            <span>Content was truncated due to length limits</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default WebScrapeResultCard;
