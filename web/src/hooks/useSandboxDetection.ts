/**
 * useSandboxDetection - Hook for detecting sandbox tool calls in agent events
 *
 * Integrates with the agent event stream to detect sandbox-related tool
 * executions and update the sandbox store accordingly.
 */

import { useEffect, useCallback, useRef } from "react";
import { useSandboxStore, isSandboxTool } from "../stores/sandbox";

export interface UseSandboxDetectionOptions {
    /** Automatically open panel when sandbox tool is detected */
    autoOpenPanel?: boolean;
    /** Automatically switch to output tab on tool execution */
    autoSwitchToOutput?: boolean;
    /** Sandbox ID to associate with detections */
    sandboxId?: string | null;
}

export interface SandboxDetectionResult {
    /** Whether a sandbox tool is currently executing */
    isExecuting: boolean;
    /** Current tool being executed */
    currentTool: { name: string; input: Record<string, unknown> } | null;
    /** Total execution count */
    executionCount: number;
    /** Handle tool start event */
    handleToolStart: (
        toolName: string,
        input: Record<string, unknown>,
        callId?: string
    ) => void;
    /** Handle tool end event */
    handleToolEnd: (
        callId: string,
        output?: string,
        error?: string,
        durationMs?: number
    ) => void;
    /** Open sandbox panel */
    openPanel: () => void;
    /** Close sandbox panel */
    closePanel: () => void;
}

/**
 * Hook for detecting and handling sandbox tool executions
 *
 * @example
 * ```tsx
 * function AgentChat() {
 *   const { handleToolStart, handleToolEnd, isExecuting } = useSandboxDetection({
 *     sandboxId: "my-sandbox",
 *     autoOpenPanel: true,
 *   });
 *
 *   // In your agent event handler:
 *   const onAct = (event) => {
 *     handleToolStart(event.data.tool_name, event.data.tool_input, event.data.call_id);
 *   };
 *
 *   const onObserve = (event) => {
 *     handleToolEnd(event.data.call_id, event.data.observation);
 *   };
 *
 *   return (
 *     <div>
 *       {isExecuting && (
 *         <div className="flex flex-col items-center gap-2">
 *           <Spin />
 *           <span>Executing sandbox tool...</span>
 *         </div>
 *       )}
 *     </div>
 *   );
 * }
 * ```
 */
export function useSandboxDetection(
    options: UseSandboxDetectionOptions = {}
): SandboxDetectionResult {
    const {
        autoOpenPanel = true,
        autoSwitchToOutput = true,
        sandboxId,
    } = options;

    const {
        currentTool,
        toolExecutions,
        onToolStart,
        onToolEnd,
        openPanel,
        closePanel,
        setSandboxId,
        setActiveTab,
    } = useSandboxStore();

    // Track if we've set the sandbox ID
    const hasSetSandboxId = useRef(false);

    // Set sandbox ID when provided
    useEffect(() => {
        if (sandboxId && !hasSetSandboxId.current) {
            setSandboxId(sandboxId);
            hasSetSandboxId.current = true;
        }
    }, [sandboxId, setSandboxId]);

    // Handle tool start
    const handleToolStart = useCallback(
        (
            toolName: string,
            input: Record<string, unknown>,
            callId?: string
        ) => {
            // Only process sandbox tools
            if (!isSandboxTool(toolName)) {
                return;
            }

            // Call store handler
            onToolStart(toolName, input, callId);

            // Auto-open panel if enabled
            if (autoOpenPanel) {
                openPanel(sandboxId);
            }

            // Auto-switch to output tab if enabled
            if (autoSwitchToOutput) {
                setActiveTab("output");
            }
        },
        [onToolStart, autoOpenPanel, autoSwitchToOutput, sandboxId, openPanel, setActiveTab]
    );

    // Handle tool end
    const handleToolEnd = useCallback(
        (
            callId: string,
            output?: string,
            error?: string,
            durationMs?: number
        ) => {
            onToolEnd(callId, output, error, durationMs);
        },
        [onToolEnd]
    );

    // Handle panel open
    const handleOpenPanel = useCallback(() => {
        openPanel(sandboxId);
    }, [openPanel, sandboxId]);

    return {
        isExecuting: currentTool !== null,
        currentTool: currentTool
            ? { name: currentTool.name, input: currentTool.input }
            : null,
        executionCount: toolExecutions.length,
        handleToolStart,
        handleToolEnd,
        openPanel: handleOpenPanel,
        closePanel,
    };
}

/**
 * Hook to create agent event handlers for sandbox detection
 *
 * Returns handlers that can be directly used with AgentStreamHandler
 */
export function useSandboxAgentHandlers(sandboxId?: string | null) {
    const { handleToolStart, handleToolEnd } = useSandboxDetection({
        sandboxId,
        autoOpenPanel: true,
        autoSwitchToOutput: true,
    });

    // Create handlers for agent events
    const onAct = useCallback(
        (event: { data: { tool_name: string; tool_input: Record<string, unknown>; call_id?: string } }) => {
            handleToolStart(
                event.data.tool_name,
                event.data.tool_input,
                event.data.call_id
            );
        },
        [handleToolStart]
    );

    const onObserve = useCallback(
        (event: { data: { call_id?: string; observation?: string; result?: unknown; error?: string; duration_ms?: number } }) => {
            // call_id may be missing, pass empty string to let store handle it
            // Support both 'observation' (legacy) and 'result' (new) fields
            let observationValue: string | undefined;
            const rawResult = event.data.result ?? event.data.observation;
            if (typeof rawResult === 'string') {
                observationValue = rawResult;
            } else if (rawResult !== null && rawResult !== undefined) {
                observationValue = JSON.stringify(rawResult);
            }

            handleToolEnd(
                event.data.call_id || "",
                observationValue,
                event.data.error,
                event.data.duration_ms
            );
        },
        [handleToolEnd]
    );

    return {
        onAct,
        onObserve,
    };
}

export default useSandboxDetection;
