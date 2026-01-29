/**
 * Sandbox Store - State management for sandbox terminal and tool execution
 *
 * Manages sandbox connection state, tool execution history, and panel visibility.
 * Extended to support desktop (noVNC) and terminal (ttyd) status management.
 */

import { create } from "zustand";
import { devtools } from "zustand/middleware";

import type { ToolExecution } from "../components/agent/sandbox/SandboxOutputViewer";
import type { DesktopStatus, TerminalStatus } from "../types/agent";
import { sandboxService } from "../services/sandboxService";

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
  activeTab: "terminal" | "output" | "desktop" | "control";

  // Sandbox connection
  activeSandboxId: string | null;
  connectionStatus: ConnectionStatus;
  terminalSessionId: string | null;

  // Desktop and Terminal status (extended)
  desktopStatus: DesktopStatus | null;
  terminalStatus: TerminalStatus | null;
  isDesktopLoading: boolean;
  isTerminalLoading: boolean;

  // Tool execution tracking
  currentTool: CurrentTool | null;
  toolExecutions: ToolExecution[];
  maxExecutions: number;

  // Actions
  openPanel: (sandboxId?: string | null) => void;
  closePanel: () => void;
  setActiveTab: (tab: "terminal" | "output" | "desktop" | "control") => void;
  setPanelMode: (mode: PanelMode) => void;

  // Sandbox connection actions
  setSandboxId: (sandboxId: string | null) => void;
  setConnectionStatus: (status: ConnectionStatus) => void;
  setTerminalSessionId: (sessionId: string | null) => void;

  // Desktop and Terminal status actions
  setDesktopStatus: (status: DesktopStatus | null) => void;
  setTerminalStatus: (status: TerminalStatus | null) => void;
  setDesktopLoading: (loading: boolean) => void;
  setTerminalLoading: (loading: boolean) => void;

  // Desktop and Terminal control actions
  startDesktop: () => Promise<void>;
  stopDesktop: () => Promise<void>;
  startTerminal: () => Promise<void>;
  stopTerminal: () => Promise<void>;

  // SSE event handler
  handleSSEEvent: (event: { type: string; data: any }) => void;

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
  desktopStatus: null as DesktopStatus | null,
  terminalStatus: null as TerminalStatus | null,
  isDesktopLoading: false,
  isTerminalLoading: false,
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
          // Reset desktop/terminal status when sandbox changes
          desktopStatus: null,
          terminalStatus: null,
        });
      },

      setConnectionStatus: (status) => {
        set({ connectionStatus: status });
      },

      setTerminalSessionId: (sessionId) => {
        set({ terminalSessionId: sessionId });
      },

      // Desktop status actions
      setDesktopStatus: (status) => {
        set({ desktopStatus: status });
      },

      setTerminalStatus: (status) => {
        set({ terminalStatus: status });
      },

      setDesktopLoading: (loading) => {
        set({ isDesktopLoading: loading });
      },

      setTerminalLoading: (loading) => {
        set({ isTerminalLoading: loading });
      },

      // Desktop control actions
      startDesktop: async () => {
        const { activeSandboxId } = get();
        if (!activeSandboxId) {
          console.warn("Cannot start desktop: no active sandbox");
          return;
        }

        set({ isDesktopLoading: true });

        try {
          const status = await sandboxService.startDesktop(activeSandboxId);
          set({ desktopStatus: status, isDesktopLoading: false });
        } catch (error) {
          console.error("Failed to start desktop:", error);
          set({ isDesktopLoading: false });
          throw error;
        }
      },

      stopDesktop: async () => {
        const { activeSandboxId } = get();
        if (!activeSandboxId) {
          console.warn("Cannot stop desktop: no active sandbox");
          return;
        }

        set({ isDesktopLoading: true });

        try {
          await sandboxService.stopDesktop(activeSandboxId);
          set({
            desktopStatus: {
              running: false,
              url: null,
              display: "",
              resolution: "",
              port: 0,
            },
            isDesktopLoading: false,
          });
        } catch (error) {
          console.error("Failed to stop desktop:", error);
          set({ isDesktopLoading: false });
          throw error;
        }
      },

      // Terminal control actions
      startTerminal: async () => {
        const { activeSandboxId } = get();
        if (!activeSandboxId) {
          console.warn("Cannot start terminal: no active sandbox");
          return;
        }

        set({ isTerminalLoading: true });

        try {
          const status = await sandboxService.startTerminal(activeSandboxId);
          set({ terminalStatus: status, isTerminalLoading: false });
        } catch (error) {
          console.error("Failed to start terminal:", error);
          set({ isTerminalLoading: false });
          throw error;
        }
      },

      stopTerminal: async () => {
        const { activeSandboxId } = get();
        if (!activeSandboxId) {
          console.warn("Cannot stop terminal: no active sandbox");
          return;
        }

        set({ isTerminalLoading: true });

        try {
          await sandboxService.stopTerminal(activeSandboxId);
          set({
            terminalStatus: {
              running: false,
              url: null,
              port: 0,
              sessionId: null,
              pid: null,
            },
            isTerminalLoading: false,
          });
        } catch (error) {
          console.error("Failed to stop terminal:", error);
          set({ isTerminalLoading: false });
          throw error;
        }
      },

      // SSE event handler for desktop/terminal events
      handleSSEEvent: (event) => {
        const { type, data } = event;

        switch (type) {
          case "desktop_started": {
            const status: DesktopStatus = {
              running: true,
              url: data.url || null,
              display: data.display || ":0",
              resolution: data.resolution || "1280x720",
              port: data.port || 6080,
            };
            set({ desktopStatus: status });
            break;
          }

          case "desktop_stopped": {
            set({
              desktopStatus: {
                running: false,
                url: null,
                display: "",
                resolution: "",
                port: 0,
              },
            });
            break;
          }

          case "desktop_status": {
            const status: DesktopStatus = {
              running: data.running || false,
              url: data.url || null,
              display: data.display || "",
              resolution: data.resolution || "",
              port: data.port || 0,
            };
            set({ desktopStatus: status });
            break;
          }

          case "terminal_started": {
            const status: TerminalStatus = {
              running: true,
              url: data.url || null,
              port: data.port || 7681,
              sessionId: data.session_id || null,
              pid: data.pid || null,
            };
            set({ terminalStatus: status });
            break;
          }

          case "terminal_stopped": {
            set({
              terminalStatus: {
                running: false,
                url: null,
                port: 0,
              },
            });
            break;
          }

          case "terminal_status": {
            const status: TerminalStatus = {
              running: data.running || false,
              url: data.url || null,
              port: data.port || 0,
              sessionId: data.session_id || null,
              pid: data.pid || null,
            };
            set({ terminalStatus: status });
            break;
          }
        }
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

// New selectors for desktop and terminal status
export const useDesktopStatus = () =>
  useSandboxStore((state) => state.desktopStatus);

export const useTerminalStatus = () =>
  useSandboxStore((state) => state.terminalStatus);

// Helper to check if a tool is a sandbox tool
export function isSandboxTool(toolName: string): boolean {
  return SANDBOX_TOOLS.includes(toolName as SandboxToolName);
}
