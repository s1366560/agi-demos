/**
 * Sandbox Store - State management for sandbox terminal and tool execution
 *
 * Manages sandbox connection state, tool execution history, and panel visibility.
 * Updated to use project-scoped sandbox API (v2).
 *
 * @packageDocumentation
 */

import { create } from "zustand";
import { devtools } from "zustand/middleware";

import type { ToolExecution } from "../components/agent/sandbox/SandboxOutputViewer";
import type { DesktopStatus, TerminalStatus } from "../types/agent";
import { projectSandboxService } from "../services/projectSandboxService";
import { sandboxSSEService } from "../services/sandboxSSEService";
import { logger } from "../utils/logger";

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

  // Sandbox connection - supports both v1 (sandboxId) and v2 (projectId)
  activeSandboxId: string | null;
  activeProjectId: string | null;
  connectionStatus: ConnectionStatus;
  terminalSessionId: string | null;
  sseUnsubscribe: (() => void) | null;

  // Desktop and Terminal status
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

  // Project-scoped actions (v2 API)
  setProjectId: (projectId: string | null) => void;
  ensureSandbox: () => Promise<string | null>;
  executeTool: (
    toolName: string,
    args: Record<string, unknown>,
    timeout?: number
  ) => Promise<{ success: boolean; content: string; isError: boolean }>;

  // SSE subscription actions
  subscribeSSE: (projectId: string) => void;
  unsubscribeSSE: () => void;

  // Desktop and Terminal control actions (project-scoped)
  startDesktop: (resolution?: string) => Promise<void>;
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
  activeProjectId: null,
  connectionStatus: "idle" as ConnectionStatus,
  terminalSessionId: null,
  sseUnsubscribe: null,
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
          connectionStatus: sandboxId ? "idle" : "idle",
          terminalSessionId: null,
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

      // Project ID setter
      setProjectId: (projectId) => {
        set({ activeProjectId: projectId });
      },

      // Ensure sandbox exists (v2 API)
      ensureSandbox: async () => {
        const { activeProjectId, activeSandboxId } = get();

        // Return existing sandboxId if available
        if (activeSandboxId) {
          return activeSandboxId;
        }

        if (!activeProjectId) {
          logger.warn("[SandboxStore] Cannot ensure sandbox: no active project");
          return null;
        }

        try {
          set({ connectionStatus: "connecting" });
          const sandbox = await projectSandboxService.ensureSandbox(
            activeProjectId
          );

          set({
            activeSandboxId: sandbox.sandbox_id,
            connectionStatus: sandbox.is_healthy ? "connected" : "error",
            desktopStatus: sandbox.desktop_url
              ? {
                  running: true,
                  url: sandbox.desktop_url,
                  display: ":1",
                  resolution: "1280x720",
                  port: sandbox.desktop_port || 6080,
                }
              : null,
            terminalStatus: sandbox.terminal_url
              ? {
                  running: true,
                  url: sandbox.terminal_url,
                  port: sandbox.terminal_port || 7681,
                  sessionId: null,
                  pid: null,
                }
              : null,
          });

          logger.info(
            `[SandboxStore] Sandbox ensured: ${sandbox.sandbox_id} (${sandbox.status})`
          );
          return sandbox.sandbox_id;
        } catch (error) {
          logger.error("[SandboxStore] Failed to ensure sandbox:", error);
          set({ connectionStatus: "error" });
          return null;
        }
      },

      // Execute tool directly (v2 API)
      executeTool: async (toolName, args, timeout = 30) => {
        const { activeProjectId } = get();

        if (!activeProjectId) {
          logger.warn("[SandboxStore] Cannot execute tool: no active project");
          return { success: false, content: "No active project", isError: true };
        }

        try {
          const result = await projectSandboxService.executeTool(
            activeProjectId,
            {
              tool_name: toolName,
              arguments: args,
              timeout,
            }
          );

          // Extract text content from result
          let content = "";
          if (result.content && result.content.length > 0) {
            content = result.content
              .map((c) => c.text || "")
              .filter(Boolean)
              .join("\n");
          }

          return {
            success: !result.is_error,
            content,
            isError: result.is_error,
          };
        } catch (error) {
          logger.error("[SandboxStore] Tool execution failed:", error);
          return {
            success: false,
            content: String(error),
            isError: true,
          };
        }
      },

      // SSE subscription methods
      subscribeSSE: (projectId) => {
        // Unsubscribe from previous subscription if exists
        const { sseUnsubscribe } = get();
        if (sseUnsubscribe) {
          sseUnsubscribe();
        }

        // Subscribe to new project events
        const unsubscribe = sandboxSSEService.subscribe(projectId, {
          onDesktopStarted: get().handleSSEEvent,
          onDesktopStopped: get().handleSSEEvent,
          onTerminalStarted: get().handleSSEEvent,
          onTerminalStopped: get().handleSSEEvent,
          onStatusUpdate: get().handleSSEEvent,
          onError: (error) => {
            logger.error("[SandboxSSE] Error:", error);
          },
        });

        set({ sseUnsubscribe: unsubscribe, activeProjectId: projectId });
      },

      unsubscribeSSE: () => {
        const { sseUnsubscribe } = get();
        if (sseUnsubscribe) {
          sseUnsubscribe();
          set({ sseUnsubscribe: null });
        }
      },

      // Desktop control actions (project-scoped v2 API)
      startDesktop: async (resolution = "1280x720") => {
        const { activeProjectId } = get();

        if (!activeProjectId) {
          logger.warn("[SandboxStore] Cannot start desktop: no active project");
          return;
        }

        set({ isDesktopLoading: true });

        try {
          // Use v2 API (project-scoped)
          const status = await projectSandboxService.startDesktop(
            activeProjectId,
            resolution
          );
          set({ desktopStatus: status, isDesktopLoading: false });
          logger.info(`[SandboxStore] Desktop started for project ${activeProjectId}`);
        } catch (error) {
          logger.error("[SandboxStore] Failed to start desktop:", error);
          set({ isDesktopLoading: false });
          throw error;
        }
      },

      stopDesktop: async () => {
        const { activeProjectId } = get();

        if (!activeProjectId) {
          logger.warn("[SandboxStore] Cannot stop desktop: no active project");
          return;
        }

        set({ isDesktopLoading: true });

        try {
          await projectSandboxService.stopDesktop(activeProjectId);
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
          logger.info(`[SandboxStore] Desktop stopped for project ${activeProjectId}`);
        } catch (error) {
          logger.error("[SandboxStore] Failed to stop desktop:", error);
          set({ isDesktopLoading: false });
          throw error;
        }
      },

      // Terminal control actions (project-scoped v2 API)
      startTerminal: async () => {
        const { activeProjectId } = get();

        if (!activeProjectId) {
          logger.warn("[SandboxStore] Cannot start terminal: no active project");
          return;
        }

        set({ isTerminalLoading: true });

        try {
          const status = await projectSandboxService.startTerminal(
            activeProjectId
          );
          set({ terminalStatus: status, isTerminalLoading: false });
          logger.info(`[SandboxStore] Terminal started for project ${activeProjectId}`);
        } catch (error) {
          logger.error("[SandboxStore] Failed to start terminal:", error);
          set({ isTerminalLoading: false });
          throw error;
        }
      },

      stopTerminal: async () => {
        const { activeProjectId } = get();

        if (!activeProjectId) {
          logger.warn("[SandboxStore] Cannot stop terminal: no active project");
          return;
        }

        set({ isTerminalLoading: true });

        try {
          await projectSandboxService.stopTerminal(activeProjectId);
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
          logger.info(`[SandboxStore] Terminal stopped for project ${activeProjectId}`);
        } catch (error) {
          logger.error("[SandboxStore] Failed to stop terminal:", error);
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
                sessionId: null,
                pid: null,
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
            panelVisible: true,
            activeTab: "output",
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
        // Clean up SSE subscription before reset
        const { sseUnsubscribe } = get();
        if (sseUnsubscribe) {
          sseUnsubscribe();
        }
        set(initialState);
        set({ sseUnsubscribe: null });
      },
    }),
    {
      name: "sandbox-store-v2",
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

// Project-scoped selectors
export const useActiveProjectId = () =>
  useSandboxStore((state) => state.activeProjectId);

export const useEnsureSandbox = () =>
  useSandboxStore((state) => state.ensureSandbox);

export const useExecuteTool = () =>
  useSandboxStore((state) => state.executeTool);

// Helper to check if a tool is a sandbox tool
export function isSandboxTool(toolName: string): boolean {
  return SANDBOX_TOOLS.includes(toolName as SandboxToolName);
}
