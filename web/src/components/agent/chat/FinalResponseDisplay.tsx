/**
 * FinalResponseDisplay - Agent's final response with action sidebar
 *
 * Matches the design from docs/statics/project workbench/agent/finished/
 * Features prose-styled content with export actions sidebar.
 */

import { useState } from "react";

export interface FinalResponseDisplayProps {
  /** Report content (markdown) */
  content: string;
  /** Report version */
  version?: string;
  /** Generation timestamp */
  generatedAt?: string;
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
  version = "v1.0 Final",
  generatedAt,
}: FinalResponseDisplayProps) {
  const [copied, setCopied] = useState(false);

  // Format timestamp
  const formatTimeAgo = (isoString: string) => {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 3600000);
    if (diffHours < 24) return `${diffHours}h ago`;
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy:", error);
    }
  };

  const handleExportPDF = () => {
    // TODO: Implement PDF export
    console.log("Export PDF");
  };

  const handleShare = () => {
    // TODO: Implement share
    console.log("Share");
  };

  // Simple markdown rendering
  const renderContent = (text: string) => {
    if (!text) return null;
    const lines = text.split("\n");

    return lines.map((line, index) => {
      // Headers
      if (line.startsWith("### ")) {
        return (
          <h3
            key={index}
            className="text-lg font-bold mt-6 mb-3 text-slate-900 dark:text-white"
          >
            {line.replace("### ", "")}
          </h3>
        );
      }
      if (line.startsWith("## ")) {
        return (
          <h3
            key={index}
            className="text-xl font-bold mt-6 mb-3 text-slate-900 dark:text-white"
          >
            {line.replace("## ", "")}
          </h3>
        );
      }

      // Bullet points
      if (line.trim().startsWith("- ")) {
        return (
          <li
            key={index}
            className="text-sm mb-1 text-slate-700 dark:text-slate-300 ml-4"
          >
            {line.trim().replace(/- |\*\*/g, "")}
          </li>
        );
      }

      // Bold text
      if (line.includes("**")) {
        const parts = line.split("**");
        return (
          <p
            key={index}
            className="text-sm mb-3 text-slate-700 dark:text-slate-300"
          >
            {parts.map((part, i) =>
              i % 2 === 1 ? (
                <strong
                  key={i}
                  className="font-semibold text-slate-900 dark:text-white"
                >
                  {part}
                </strong>
              ) : (
                part
              )
            )}
          </p>
        );
      }

      // Regular paragraph
      if (line.trim()) {
        return (
          <p
            key={index}
            className="text-sm mb-3 text-slate-700 dark:text-slate-300"
          >
            {line}
          </p>
        );
      }

      return <br key={index} />;
    });
  };

  return (
    <div className="flex-1 flex flex-col lg:flex-row gap-6 pb-12">
      {/* Main Content */}
      <div className="flex-1 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none shadow-xl p-8 prose prose-sm dark:prose-invert max-w-none text-slate-800 dark:text-slate-200">
        {/* Header */}
        <div className="flex items-center justify-between mb-8 border-b border-slate-100 dark:border-border-dark pb-4 -mt-4">
          <h2 className="m-0 text-2xl">Final Synthesis Report</h2>
          {version && (
            <span className="text-[10px] px-2 py-1 bg-primary/10 text-primary rounded font-bold uppercase">
              {version}
            </span>
          )}
        </div>

        {/* Content */}
        {renderContent(content)}
      </div>

      {/* Action Sidebar */}
      <div className="w-72 shrink-0 space-y-4">
        <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl p-4 shadow-sm sticky top-6">
          <h4 className="text-[10px] font-bold text-text-muted uppercase tracking-wider mb-4">
            Actions
          </h4>
          <div className="space-y-2">
            <button
              onClick={handleCopy}
              className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-700 dark:text-slate-200 bg-white dark:bg-surface-dark hover:bg-slate-50 dark:hover:bg-slate-800 rounded-lg transition-all duration-200 border border-slate-200 dark:border-border-dark hover:border-primary dark:hover:border-primary hover:shadow-md"
            >
              <span className="material-symbols-outlined text-[20px]">
                content_copy
              </span>
              {copied ? "Copied!" : "Copy to Clipboard"}
            </button>

            <button
              onClick={handleExportPDF}
              className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-700 dark:text-slate-200 bg-white dark:bg-surface-dark hover:bg-slate-50 dark:hover:bg-slate-800 rounded-lg transition-all duration-200 border border-slate-200 dark:border-border-dark hover:border-primary dark:hover:border-primary hover:shadow-md"
            >
              <span className="material-symbols-outlined text-[20px]">
                picture_as_pdf
              </span>
              Export as PDF
            </button>

            <button
              onClick={handleShare}
              className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-700 dark:text-slate-200 bg-white dark:bg-surface-dark hover:bg-slate-50 dark:hover:bg-slate-800 rounded-lg transition-all duration-200 border border-slate-200 dark:border-border-dark hover:border-primary dark:hover:border-primary hover:shadow-md"
            >
              <span className="material-symbols-outlined text-[20px]">
                share
              </span>
              Share with Team
            </button>
          </div>

          {generatedAt && (
            <div className="mt-4 pt-4 border-t border-slate-100 dark:border-border-dark">
              <div className="flex items-center gap-2 text-text-muted">
                <span className="material-symbols-outlined text-sm">
                  schedule
                </span>
                <span className="text-[10px]">
                  Generated {formatTimeAgo(generatedAt)}
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
