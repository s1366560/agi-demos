/**
 * Sandbox Store - State management for sandbox terminal and tool execution
 *
 * Manages sandbox connection state, tool execution history, and panel visibility.
 */

import { create } from "zustand";
import { devtools } from "zustand/middleware";

import type { ToolExecution } from "../components/agent/sandbox/SandboxOutputViewer";

// Sandbox tools that should trigger panel opening
export const SANDBOX_TOOLS = [
  "read",
  "write",
  "edit",
  "glob",
  "grep",
  "bash",
] as const;

export type SandboxToolName = (typeof SANDBOX_TOOLS)[number];

export type ConnectionStatus = "idle" | "connecting" | "connected" | "error";

export type PanelMode = "terminal" | "output" | "split";

export interface CurrentTool {
  name: string;
  input: Record<string, unknown>;
  callId?: string;
  startTime: number;
}

export interface SandboxState {
  // Panel state
  panelVisible: boolean;
  panelMode: PanelMode;
  activeTab: "terminal" | "output";

  // Sandbox connection
  activeSandboxId: string | null;
  connectionStatus: ConnectionStatus;
  terminalSessionId: string | null;

  // Tool execution tracking
  currentTool: CurrentTool | null;
  toolExecutions: ToolExecution[];
  maxExecutions: number;

  // Actions
  openPanel: (sandboxId?: string | null) => void;
  closePanel: () => void;
  setActiveTab: (tab: "terminal" | "output") => void;
  setPanelMode: (mode: PanelMode) => void;

  // Sandbox connection actions
  setSandboxId: (sandboxId: string | null) => void;
  setConnectionStatus: (status: ConnectionStatus) => void;
  setTerminalSessionId: (sessionId: string | null) => void;

  // Tool execution actions
  setCurrentTool: (tool: CurrentTool | null) => void;
  addToolExecution: (execution: ToolExecution) => void;
  updateToolExecution: (
    id: string,
    update: Partial<ToolExecution>
  ) => void;
  clearToolExecutions: () => void;

  // Event handlers for agent integration
  onToolStart: (
    toolName: string,
    input: Record<string, unknown>,
    callId?: string
  ) => void;
  onToolEnd: (
    callId: string,
    output?: string,
    error?: string,
    durationMs?: number
  ) => void;

  // Reset
  reset: () => void;
}

const initialState = {
  panelVisible: false,
  panelMode: "terminal" as PanelMode,
  activeTab: "terminal" as const,
  activeSandboxId: null,
  connectionStatus: "idle" as ConnectionStatus,
  terminalSessionId: null,
  currentTool: null,
  toolExecutions: [],
  maxExecutions: 50,
};

export const useSandboxStore = create<SandboxState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // Panel actions
      openPanel: (sandboxId) => {
        set((state) => ({
          panelVisible: true,
          activeSandboxId: sandboxId ?? state.activeSandboxId,
        }));
      },

      closePanel: () => {
        set({ panelVisible: false });
      },

      setActiveTab: (tab) => {
        set({ activeTab: tab });
      },

      setPanelMode: (mode) => {
        set({ panelMode: mode });
      },

      // Sandbox connection actions
      setSandboxId: (sandboxId) => {
        set({
          activeSandboxId: sandboxId,
          // Reset connection state when sandbox changes
          connectionStatus: sandboxId ? "idle" : "idle",
          terminalSessionId: null,
        });
      },

      setConnectionStatus: (status) => {
        set({ connectionStatus: status });
      },

      setTerminalSessionId: (sessionId) => {
        set({ terminalSessionId: sessionId });
      },

      // Tool execution actions
      setCurrentTool: (tool) => {
        set({ currentTool: tool });
      },

      addToolExecution: (execution) => {
        set((state) => {
          const executions = [execution, ...state.toolExecutions].slice(
            0,
            state.maxExecutions
          );
          return { toolExecutions: executions };
        });
      },

      updateToolExecution: (id, update) => {
        set((state) => ({
          toolExecutions: state.toolExecutions.map((exec) =>
            exec.id === id ? { ...exec, ...update } : exec
          ),
        }));
      },

      clearToolExecutions: () => {
        set({ toolExecutions: [] });
      },

      // Event handlers for agent integration
      onToolStart: (toolName, input, callId) => {
        const isSandboxTool = SANDBOX_TOOLS.includes(
          toolName as SandboxToolName
        );

        if (isSandboxTool) {
          const tool: CurrentTool = {
            name: toolName,
            input,
            callId,
            startTime: Date.now(),
          };

          set(() => ({
            currentTool: tool,
            panelVisible: true, // Auto-open panel
            activeTab: "output", // Switch to output tab
          }));

          // Add to executions (pending state)
          const execution: ToolExecution = {
            id: callId || `${toolName}-${Date.now()}`,
            toolName,
            input,
            timestamp: Date.now(),
          };

          get().addToolExecution(execution);
        }
      },

      onToolEnd: (callId, output, error, durationMs) => {
        const currentTool = get().currentTool;

        // Clear current tool if matches
        if (currentTool?.callId === callId || !callId) {
          set({ currentTool: null });
        }

        // Update execution result
        if (callId) {
          get().updateToolExecution(callId, {
            output,
            error,
            durationMs,
          });
        }
      },

      // Reset
      reset: () => {
        set(initialState);
      },
    }),
    {
      name: "sandbox-store",
    }
  )
);

// Selectors
export const useSandboxPanelVisible = () =>
  useSandboxStore((state) => state.panelVisible);

export const useActiveSandboxId = () =>
  useSandboxStore((state) => state.activeSandboxId);

export const useSandboxConnectionStatus = () =>
  useSandboxStore((state) => state.connectionStatus);

export const useCurrentTool = () =>
  useSandboxStore((state) => state.currentTool);

export const useToolExecutions = () =>
  useSandboxStore((state) => state.toolExecutions);

export const useSandboxActiveTab = () =>
  useSandboxStore((state) => state.activeTab);

// Helper to check if a tool is a sandbox tool
export function isSandboxTool(toolName: string): boolean {
  return SANDBOX_TOOLS.includes(toolName as SandboxToolName);
}
