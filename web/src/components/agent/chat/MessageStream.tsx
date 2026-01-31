/**
 * MessageStream - Chat message stream component
 *
 * Displays user messages, agent reasoning, tool execution, and final responses.
 * Matches the design from docs/statics/project workbench/agent/
 */

import { ReactNode, memo } from "react";
import { MarkdownContent } from "./MarkdownContent";

export interface MessageStreamProps {
    /** Messages to display */
    children?: ReactNode;
    /** Padding for content area */
    className?: string;
}

/**
 * MessageStream component
 *
 * @example
 * <MessageStream>
 *   <UserMessage content="What are the trends?" />
 *   <ReasoningLog steps={reasoningSteps} />
 *   <ToolExecutionCard toolName="Memory Search" status="running" />
 *   <FinalResponse content="# Analysis Report..." />
 * </MessageStream>
 */
export const MessageStream = memo(function MessageStream({
    children,
    className = "",
}: MessageStreamProps) {
    return (
        <div className={`w-full max-w-3xl lg:max-w-5xl xl:max-w-7xl mx-auto space-y-10 ${className}`}>{children}</div>
    );
});

/**
 * UserMessage - User's message bubble (right-aligned, primary color)
 */
export interface UserMessageProps {
    /** Message content */
    content: string;
}

export function UserMessage({ content }: UserMessageProps) {
    return (
        <div className="flex items-start gap-3 justify-end">
            <div className="bg-primary text-white rounded-2xl rounded-tr-none px-5 py-[18px] max-w-[80%] shadow-md">
                <p className="text-sm leading-relaxed">{content}</p>
            </div>
        </div>
    );
}

/**
 * AgentSection - Wrapper for agent messages (left-aligned with avatar)
 */
export interface AgentSectionProps {
    /** Icon type */
    icon?: "psychology" | "construction" | "auto_awesome";
    /** Icon background color */
    iconBg?: string;
    /** Icon color */
    iconColor?: string;
    /** Opacity for completed state */
    opacity?: boolean;
    children: ReactNode;
}

export function AgentSection({
    icon = "psychology",
    iconBg = "bg-slate-200 dark:bg-border-dark",
    iconColor = "text-primary",
    opacity = false,
    children,
}: AgentSectionProps) {
    return (
        <div className={`flex items-start gap-4 ${opacity ? "opacity-70" : ""}`}>
            <div
                className={`w-8 h-8 rounded-full ${iconBg} flex items-center justify-center shrink-0`}
            >
                <span className={`material-symbols-outlined text-lg ${iconColor}`}>
                    {icon}
                </span>
            </div>
            <div className="flex-1">{children}</div>
        </div>
    );
}

/**
 * ReasoningLogCard - Expandable reasoning log card
 */
export interface ReasoningLogCardProps {
    /** Reasoning steps */
    steps: string[];
    /** Summary text */
    summary: string;
    /** Whether completed */
    completed?: boolean;
    /** Whether expanded by default */
    expanded?: boolean;
}

export function ReasoningLogCard({
    steps,
    summary,
    completed = false,
    expanded = true,
}: ReasoningLogCardProps) {
    return (
        <div className="bg-slate-50 dark:bg-surface-dark/50 border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none p-4">
            <details className="group/reasoning" open={expanded}>
                <summary className="text-sm text-slate-600 dark:text-slate-300 cursor-pointer list-none flex items-center justify-between select-none">
                    <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-sm group-open/reasoning:rotate-90 transition-transform">
                            chevron_right
                        </span>
                        <span className="font-semibold uppercase text-[10px] text-primary">
                            Reasoning Log
                        </span>
                        <span className="text-xs">{summary}</span>
                    </div>
                    {completed && (
                        <span className="text-[10px] font-bold text-emerald-500">
                            COMPLETE
                        </span>
                    )}
                </summary>
                <div className="mt-3 pl-4 border-l-2 border-slate-200 dark:border-border-dark text-sm text-slate-500 dark:text-text-muted leading-relaxed space-y-2">
                    {steps.map((step, index) => (
                        <p key={index}>{step}</p>
                    ))}
                </div>
            </details>
        </div>
    );
}

/**
 * Format tool result to string for display
 * Handles objects, arrays, and primitives
 */
export function formatToolResult(result: unknown): string {
    if (result === null || result === undefined) {
        return '';
    }
    if (typeof result === 'string') {
        return result;
    }
    // Convert objects, arrays, numbers, booleans to JSON string
    return JSON.stringify(result, null, 2);
}

/**
 * ToolExecutionCardDisplay - Tool execution with live status
 */
export interface ToolExecutionCardDisplayProps {
    /** Tool name */
    toolName: string;
    /** Execution status */
    status: "running" | "success" | "error";
    /** Query parameters (input) */
    parameters?: Record<string, unknown>;
    /** Execution mode */
    executionMode?: string;
    /** Execution duration in milliseconds */
    duration?: number;
    /** Execution result - can be string or object */
    result?: string | unknown;
    /** Error message */
    error?: string;
    /** Whether to show details expanded by default */
    defaultExpanded?: boolean;
}

export function ToolExecutionCardDisplay({
    toolName,
    status,
    parameters,
    executionMode,
    duration,
    result,
    error,
    defaultExpanded = false,
}: ToolExecutionCardDisplayProps) {
    // Use a generic tool icon instead of hardcoded category-based icons
    // This avoids maintenance burden when new tools are added
    const getIcon = () => {
        return "construction";
    };

    const formatDuration = (ms: number) => {
        if (ms < 1000) return `${ms}ms`;
        if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
        return `${(ms / 60000).toFixed(1)}m`;
    };

    // Format result to ensure it's always a string
    const formattedResult = formatToolResult(result);

    const getStatusBadge = () => {
        switch (status) {
            case "running":
                return (
                    <div className="flex items-center gap-2 px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-500/10 text-amber-600 text-[10px] font-bold uppercase tracking-wider">
                        <span className="material-symbols-outlined text-[12px] spinner">
                            autorenew
                        </span>
                        Running
                    </div>
                );
            case "success":
                return (
                    <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-500/10 text-emerald-600 text-[10px] font-bold uppercase tracking-wider">
                        <span className="material-symbols-outlined text-[12px]">check</span>
                        Success
                        {duration !== undefined && (
                            <span className="ml-1 text-emerald-500/70">
                                ({formatDuration(duration)})
                            </span>
                        )}
                    </div>
                );
            case "error":
                return (
                    <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-100 dark:bg-red-500/10 text-red-600 text-[10px] font-bold uppercase tracking-wider">
                        <span className="material-symbols-outlined text-[12px]">close</span>
                        Failed
                        {duration !== undefined && (
                            <span className="ml-1 text-red-500/70">
                                ({formatDuration(duration)})
                            </span>
                        )}
                    </div>
                );
        }
    };

    const hasDetails = parameters || executionMode || formattedResult || error;

    return (
        <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none shadow-sm overflow-hidden">
            <div className="px-4 py-3 bg-slate-50 dark:bg-white/5 border-b border-slate-200 dark:border-border-dark flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-[20px]">
                        {getIcon()}
                    </span>
                    <span className="text-sm font-semibold">{toolName}</span>
                </div>
                {getStatusBadge()}
            </div>

            {hasDetails && (
                <details
                    className="group"
                    open={defaultExpanded || status === "running"}
                >
                    <summary className="px-4 py-2 text-xs text-slate-500 cursor-pointer hover:bg-slate-50 dark:hover:bg-white/5 flex items-center gap-1 select-none">
                        <span className="material-symbols-outlined text-sm group-open:rotate-90 transition-transform">
                            chevron_right
                        </span>
                        <span>Details</span>
                    </summary>
                    <div className="p-4 pt-0 space-y-4">
                        {/* Input Parameters */}
                        {parameters && (
                            <div className="space-y-1">
                                <label className="text-[10px] uppercase font-bold text-text-muted flex items-center gap-1">
                                    <span className="material-symbols-outlined text-[12px]">
                                        input
                                    </span>
                                    Input
                                </label>
                                <div className="px-3 py-2 bg-slate-100 dark:bg-background-dark/50 rounded-lg text-xs font-mono text-slate-600 dark:text-text-muted overflow-x-auto max-h-32 overflow-y-auto">
                                    <pre className="whitespace-pre-wrap break-words">
                                        {JSON.stringify(parameters, null, 2)}
                                    </pre>
                                </div>
                            </div>
                        )}

                        {/* Execution Mode */}
                        {executionMode && (
                            <div className="space-y-1">
                                <label className="text-[10px] uppercase font-bold text-text-muted">
                                    Execution Mode
                                </label>
                                <div className="px-3 py-2 bg-slate-100 dark:bg-background-dark/50 rounded-lg text-xs font-mono text-slate-600 dark:text-text-muted">
                                    {executionMode}
                                </div>
                            </div>
                        )}

                        {/* Running State */}
                        {status === "running" && (
                            <div className="space-y-2">
                                <label className="text-[10px] uppercase font-bold text-text-muted">
                                    Live Results
                                </label>
                                <div className="border border-dashed border-slate-200 dark:border-border-dark rounded-lg p-6 flex flex-col items-center justify-center gap-2 text-center bg-slate-50/50 dark:bg-background-dark/20">
                                    <span className="material-symbols-outlined text-slate-300 dark:text-border-dark text-3xl spinner">
                                        autorenew
                                    </span>
                                    <p className="text-xs text-text-muted italic">Executing...</p>
                                </div>
                            </div>
                        )}

                        {/* Success Result */}
                        {status === "success" && formattedResult && (
                            <div className="space-y-1">
                                <label className="text-[10px] uppercase font-bold text-emerald-600 flex items-center gap-1">
                                    <span className="material-symbols-outlined text-[12px]">
                                        output
                                    </span>
                                    Output
                                </label>
                                <div className="px-3 py-2 bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20 rounded-lg text-xs text-slate-700 dark:text-slate-300 overflow-x-auto max-h-48 overflow-y-auto">
                                    <MarkdownContent
                                        content={formattedResult}
                                        className="prose-p:my-0 prose-headings:my-1 prose-ul:my-0 prose-ol:my-0"
                                        prose={true}
                                    />
                                </div>
                            </div>
                        )}

                        {/* Error Result */}
                        {status === "error" && error && (
                            <div className="space-y-1">
                                <label className="text-[10px] uppercase font-bold text-red-600 flex items-center gap-1">
                                    <span className="material-symbols-outlined text-[12px]">
                                        error
                                    </span>
                                    Error
                                </label>
                                <div className="px-3 py-2 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-lg text-xs font-mono text-red-700 dark:text-red-300 overflow-x-auto max-h-48 overflow-y-auto">
                                    <pre className="whitespace-pre-wrap break-words">{error}</pre>
                                </div>
                            </div>
                        )}
                    </div>
                </details>
            )}
        </div>
    );
}

export default MessageStream;
