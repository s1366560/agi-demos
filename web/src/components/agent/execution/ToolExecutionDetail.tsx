/**
 * ToolExecutionDetail - Detailed tool execution display
 *
 * Shows complete tool execution information:
 * - Tool name and icon
 * - Execution status with timing
 * - Input parameters (collapsible JSON)
 * - Result/error with truncation and expand support
 * - Image rendering for URL and base64 results
 */

import { useState } from "react";
import type { ToolExecution } from "../../../types/agent";
import { MaterialIcon } from "../shared";
import {
  isImageUrl as _isImageUrl,
  parseBase64Image,
  extractImageUrl,
  foldTextWithMetadata,
} from "../../../utils/toolResultUtils";

// Keep reference to suppress unused warning - may be used in future
void _isImageUrl;

export interface ToolExecutionDetailProps {
  /** Tool execution data */
  execution: ToolExecution;
  /** Whether to show compact version */
  compact?: boolean;
}

/**
 * Get tool icon based on name
 */
function getToolIcon(name: string): string {
  const lowerName = name.toLowerCase();
  if (
    lowerName.includes("web_search") ||
    (lowerName.includes("web") && lowerName.includes("search"))
  )
    return "language";
  if (lowerName.includes("web_scrape") || lowerName.includes("scrape"))
    return "public";
  if (lowerName.includes("search") || lowerName.includes("memory"))
    return "search";
  if (lowerName.includes("entity")) return "account_tree";
  if (lowerName.includes("episode")) return "history";
  if (lowerName.includes("create")) return "add_circle";
  if (lowerName.includes("graph") || lowerName.includes("query")) return "hub";
  if (lowerName.includes("summary")) return "summarize";
  return "extension";
}

/**
 * Format duration
 */
function formatDuration(ms: number | undefined): string {
  if (!ms) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

/**
 * Format timestamp
 */
function formatTime(isoString: string | undefined): string {
  if (!isoString) return "-";
  try {
    const date = new Date(isoString);
    return date.toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "-";
  }
}

/**
 * ToolExecutionDetail component
 */
export function ToolExecutionDetail({
  execution,
  compact = false,
}: ToolExecutionDetailProps) {
  const [showFullInput, setShowFullInput] = useState(false);
  const [showFullResult, setShowFullResult] = useState(false);

  const inputJson = JSON.stringify(execution.input, null, 2);
  const resultText = execution.result || execution.error || "";
  const { text: foldedResult, folded: isResultFolded } = foldTextWithMetadata(resultText, 5);

  // Detect image content in result
  const imageUrl =
    execution.result && !execution.error
      ? extractImageUrl(execution.result)
      : null;
  const base64Image =
    execution.result && !execution.error
      ? parseBase64Image(execution.result)
      : null;
  const hasImageResult = imageUrl !== null || base64Image !== null;

  const statusConfig = {
    running: {
      bg: "bg-amber-100 dark:bg-amber-900/30",
      text: "text-amber-600 dark:text-amber-400",
      icon: "hourglass_empty",
      label: "Running",
    },
    success: {
      bg: "bg-emerald-100 dark:bg-emerald-900/30",
      text: "text-emerald-600 dark:text-emerald-400",
      icon: "check_circle",
      label: "Success",
    },
    failed: {
      bg: "bg-red-100 dark:bg-red-900/30",
      text: "text-red-600 dark:text-red-400",
      icon: "error",
      label: "Failed",
    },
  }[execution.status];

  if (compact) {
    return (
      <div className="flex items-center justify-between p-2 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
        <div className="flex items-center gap-2">
          <MaterialIcon
            name={getToolIcon(execution.toolName) as any}
            size={16}
            className="text-slate-500"
          />
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {execution.toolName}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-medium ${statusConfig.text}`}>
            {statusConfig.label}
          </span>
          {execution.duration && (
            <span className="text-xs text-slate-500">
              {formatDuration(execution.duration)}
            </span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-primary/10 flex items-center justify-center">
            <MaterialIcon
              name={getToolIcon(execution.toolName) as any}
              size={16}
              className="text-primary"
            />
          </div>
          <span className="text-sm font-semibold text-slate-900 dark:text-white">
            {execution.toolName}
          </span>
        </div>

        {/* Status Badge */}
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${statusConfig.bg} ${statusConfig.text}`}
          >
            {execution.status === "running" && (
              <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
            )}
            {execution.status !== "running" && (
              <MaterialIcon name={statusConfig.icon as any} size={12} />
            )}
            {statusConfig.label}
          </span>
          {execution.duration && (
            <span className="text-xs text-slate-500">
              {formatDuration(execution.duration)}
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="p-3 space-y-3">
        {/* Input Parameters */}
        <div>
          <button
            onClick={() => setShowFullInput(!showFullInput)}
            className="flex items-center gap-1 text-xs font-semibold text-slate-500 uppercase tracking-wider hover:text-slate-700 dark:hover:text-slate-300"
          >
            <MaterialIcon
              name={showFullInput ? "expand_less" : "expand_more"}
              size={14}
            />
            Input Parameters
          </button>
          {showFullInput && (
            <div className="mt-2 bg-slate-900 dark:bg-slate-950 rounded-md p-2 overflow-x-auto">
              <pre className="text-xs text-slate-300 font-mono whitespace-pre-wrap break-all">
                {inputJson}
              </pre>
            </div>
          )}
        </div>

        {/* Timing Info */}
        <div className="flex items-center gap-4 text-xs text-slate-500">
          <span className="flex items-center gap-1">
            <MaterialIcon name="schedule" size={12} />
            Start: {formatTime(execution.startTime)}
          </span>
          {execution.endTime && (
            <span className="flex items-center gap-1">
              <MaterialIcon name="timer" size={12} />
              Duration: {formatDuration(execution.duration)}
            </span>
          )}
        </div>

        {/* Result/Error */}
        {(execution.result || execution.error) && (
          <div>
            <div className="flex items-center justify-between">
              <h6 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                {execution.error
                  ? "Error"
                  : hasImageResult
                  ? "Image Result"
                  : "Result"}
              </h6>
              {!hasImageResult && isResultFolded && (
                <button
                  onClick={() => setShowFullResult(!showFullResult)}
                  className="text-xs text-primary hover:underline"
                >
                  {showFullResult ? "Show Less" : "Show Full"}
                </button>
              )}
            </div>
            {/* Image Result Rendering */}
            {hasImageResult && !execution.error ? (
              <div className="mt-2 p-3 bg-slate-100 dark:bg-slate-800 rounded-md text-center">
                {imageUrl ? (
                  <div>
                    <img
                      src={imageUrl}
                      alt="Tool result"
                      className="max-w-full max-h-96 rounded-md mx-auto border border-slate-200 dark:border-slate-600"
                      loading="lazy"
                      onError={(e) => {
                        // If image fails to load, show the URL as fallback
                        const target = e.target as HTMLImageElement;
                        target.style.display = "none";
                        target.nextElementSibling?.classList.remove("hidden");
                      }}
                    />
                    <div className="hidden mt-2 text-sm text-slate-500">
                      Failed to load image.{" "}
                      <a
                        href={imageUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary hover:underline"
                      >
                        Open URL
                      </a>
                    </div>
                    <a
                      href={imageUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 mt-2 text-xs text-primary hover:underline"
                    >
                      <MaterialIcon name="open_in_new" size={12} />
                      Open in new tab
                    </a>
                  </div>
                ) : base64Image ? (
                  <div>
                    <img
                      src={`data:image/${base64Image.format};base64,${base64Image.data}`}
                      alt="Screenshot"
                      className="max-w-full max-h-96 rounded-md mx-auto border border-slate-200 dark:border-slate-600"
                    />
                    <p className="mt-2 text-xs text-slate-500">
                      Screenshot captured
                    </p>
                  </div>
                ) : null}
              </div>
            ) : (
              <div
                className={`mt-1 p-2 rounded-md text-sm break-words whitespace-pre-wrap ${
                  execution.error
                    ? "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400"
                    : "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300"
                }`}
              >
                {showFullResult ? resultText : foldedResult}
              </div>
            )}
          </div>
        )}

        {/* Running State Placeholder */}
        {execution.status === "running" &&
          !execution.result &&
          !execution.error && (
            <div className="flex items-center justify-center py-4">
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <span className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                Executing...
              </div>
            </div>
          )}
      </div>
    </div>
  );
}

export default ToolExecutionDetail;
