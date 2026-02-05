/**
 * useUnifiedAgentStatus - Unified Agent Status Hook
 *
 * This hook consolidates agent state from multiple sources:
 * - Lifecycle state (from useAgentLifecycleState via WebSocket)
 * - Execution state (from agentV3 store)
 * - Plan mode state (from planModeStore)
 * - Streaming state (from streamingStore)
 * - Sandbox connection (from sandboxStore)
 *
 * Provides a single source of truth for agent status UI components.
 *
 * @module hooks/useUnifiedAgentStatus
 */

import { useMemo } from 'react';

import { usePlanModeStore } from '../stores/agent/planModeStore';
import { useStreamingStore } from '../stores/agent/streamingStore';
import { useAgentV3Store } from '../stores/agentV3';
import { useSandboxStore } from '../stores/sandbox';

import { useAgentLifecycleState } from './useAgentLifecycleState';

import type { LifecycleStateData , PlanModeStatus } from '../types/agent';

/**
 * Project Agent Lifecycle State (matches LifecycleState with 'uninitialized' added)
 */
export type ProjectAgentLifecycleState =
    | 'uninitialized'
    | 'initializing'
    | 'ready'
    | 'executing'
    | 'paused'
    | 'error'
    | 'shutting_down';

/**
 * Detailed tool statistics
 */
export interface ToolStats {
    /** Total tool count (builtin + mcp) */
    total: number;
    /** Number of built-in tools */
    builtin: number;
    /** Number of MCP tools */
    mcp: number;
}

/**
 * Detailed skill statistics
 */
export interface SkillStats {
    /** Total number of skills available in registry */
    total: number;
    /** Number of skills loaded into current context */
    loaded: number;
}

/**
 * Unified Agent Status Interface
 *
 * Combines all agent state sources into a single coherent interface.
 */
export interface UnifiedAgentStatus {
    /** Lifecycle state (from WebSocket via useAgentLifecycleState) */
    lifecycle: ProjectAgentLifecycleState;

    /** Execution state (from agentV3 store) */
    agentState: 'idle' | 'thinking' | 'acting' | 'observing' | 'awaiting_input' | 'retrying';

    /** Plan mode status */
    planMode: {
        isActive: boolean;
        currentMode?: 'build' | 'plan' | 'explore';
    };

    /** Resource counts (legacy, kept for backward compatibility) */
    resources: {
        tools: number;
        skills: number;
        activeCalls: number;
        messages: number;
    };

    /** Detailed tool statistics */
    toolStats: ToolStats;

    /** Detailed skill statistics */
    skillStats: SkillStats;

    /** Connection status */
    connection: {
        websocket: boolean;
        sandbox: boolean;
    };
}

/**
 * Hook options
 */
export interface UseUnifiedAgentStatusOptions {
    /** Project ID for lifecycle state subscription */
    projectId: string;
    /** Tenant ID for lifecycle state subscription */
    tenantId: string;
    /** Whether the hook is enabled */
    enabled?: boolean;
}

/**
 * Hook return value
 */
export interface UseUnifiedAgentStatusReturn {
    /** Unified status object */
    status: UnifiedAgentStatus;
    /** Whether currently connecting to lifecycle state */
    isLoading: boolean;
    /** Error message if any */
    error: string | null;
    /** Whether agent is currently streaming */
    isStreaming: boolean;
}

/**
 * Derive lifecycle state from WebSocket lifecycle state data
 *
 * Priority:
 * 1. Explicit lifecycleState from WebSocket
 * 2. Derived from isInitialized, isActive flags
 * 3. Default to 'uninitialized'
 */
function deriveLifecycleState(
    lifecycleData: LifecycleStateData | null
): ProjectAgentLifecycleState {
    if (!lifecycleData) {
        return 'uninitialized';
    }

    // Priority 1: Explicit lifecycle state from WebSocket
    if (lifecycleData.lifecycleState) {
        return lifecycleData.lifecycleState;
    }

    // Priority 2: Error state
    if (lifecycleData.errorMessage && !lifecycleData.isActive) {
        return 'error';
    }

    // Priority 3: Active and initialized = ready
    if (lifecycleData.isActive && lifecycleData.isInitialized) {
        return 'ready';
    }

    // Priority 4: Active but not initialized = initializing
    if (lifecycleData.isActive && !lifecycleData.isInitialized) {
        return 'initializing';
    }

    // Priority 5: Not active but was initialized = paused
    if (!lifecycleData.isActive && lifecycleData.isInitialized) {
        return 'paused';
    }

    // Default: uninitialized
    return 'uninitialized';
}

/**
 * Derive plan mode info from plan mode status
 */
function derivePlanModeInfo(
    planModeStatus: PlanModeStatus | null
): { isActive: boolean; currentMode?: 'build' | 'plan' | 'explore' } {
    if (!planModeStatus) {
        return { isActive: false };
    }

    return {
        isActive: planModeStatus.is_in_plan_mode,
        currentMode: planModeStatus.current_mode,
    };
}

/**
 * Derive resource counts from lifecycle state and agent store
 */
function deriveResources(
    lifecycleData: LifecycleStateData | null,
    activeToolCalls: Map<string, unknown>,
    messageCount: number
): {
    tools: number;
    skills: number;
    activeCalls: number;
    messages: number;
} {
    return {
        tools: lifecycleData?.toolCount ?? 0,
        skills: lifecycleData?.loadedSkillCount ?? lifecycleData?.skillCount ?? 0,
        activeCalls: activeToolCalls.size,
        messages: messageCount,
    };
}

/**
 * Derive detailed tool statistics
 */
function deriveToolStats(
    lifecycleData: LifecycleStateData | null
): ToolStats {
    return {
        total: lifecycleData?.toolCount ?? 0,
        builtin: lifecycleData?.builtinToolCount ?? 0,
        mcp: lifecycleData?.mcpToolCount ?? 0,
    };
}

/**
 * Derive detailed skill statistics
 */
function deriveSkillStats(
    lifecycleData: LifecycleStateData | null
): SkillStats {
    return {
        total: lifecycleData?.totalSkillCount ?? 0,
        loaded: lifecycleData?.loadedSkillCount ?? lifecycleData?.skillCount ?? 0,
    };
}

/**
 * Derive connection status from streaming and sandbox stores
 */
function deriveConnectionStatus(
    streamStatus: string,
    activeSandboxId: string | null
): {
    websocket: boolean;
    sandbox: boolean;
} {
    return {
        websocket: streamStatus === 'streaming' || streamStatus === 'connecting',
        sandbox: !!activeSandboxId,
    };
}

/**
 * Primary hook for unified agent status
 *
 * Uses WebSocket-based lifecycle state from useAgentLifecycleState
 * instead of HTTP polling.
 *
 * @example
 * ```tsx
 * function StatusBar() {
 *   const { status, isLoading } = useUnifiedAgentStatus({
 *     projectId: 'proj-123',
 *     tenantId: 'tenant-456',
 *     enabled: true,
 *   });
 *
 *   return (
 *     <div>
 *       <span>{status.lifecycle}</span>
 *       <span>{status.agentState}</span>
 *     </div>
 *   );
 * }
 * ```
 */
export function useUnifiedAgentStatus({
    projectId,
    tenantId,
    enabled = true,
}: UseUnifiedAgentStatusOptions): UseUnifiedAgentStatusReturn {
    // Store selectors
    const agentState = useAgentV3Store((s) => s.agentState);
    const isStreamingAgent = useAgentV3Store((s) => s.isStreaming);
    const activeToolCalls = useAgentV3Store((s) => s.activeToolCalls);
    const timeline = useAgentV3Store((s) => s.timeline);

    const planModeStatus = usePlanModeStore((s) => s.planModeStatus);

    const streamStatus = useStreamingStore((s) => s.streamStatus);
    const activeSandboxId = useSandboxStore((s) => s.activeSandboxId);

    // WebSocket-based lifecycle state (replaces HTTP polling)
    const { lifecycleState, isConnected: isLifecycleConnected, error: lifecycleError } =
        useAgentLifecycleState({
            projectId,
            tenantId,
            enabled,
        });

    // Compute unified status (using useMemo to avoid unnecessary recalculations)
    const status = useMemo<UnifiedAgentStatus>(
        () => ({
            lifecycle: deriveLifecycleState(lifecycleState),
            agentState,
            planMode: derivePlanModeInfo(planModeStatus),
            resources: deriveResources(lifecycleState, activeToolCalls, timeline.length),
            toolStats: deriveToolStats(lifecycleState),
            skillStats: deriveSkillStats(lifecycleState),
            connection: deriveConnectionStatus(streamStatus, activeSandboxId),
        }),
        [
            lifecycleState,
            agentState,
            planModeStatus,
            activeToolCalls,
            timeline.length,
            streamStatus,
            activeSandboxId,
        ]
    );

    return {
        status,
        isLoading: !isLifecycleConnected,
        error: lifecycleError,
        isStreaming: isStreamingAgent,
    };
}

export default useUnifiedAgentStatus;
