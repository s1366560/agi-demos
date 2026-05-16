/**
 * Sandbox Store - State management for sandbox terminal and tool execution
 *
 * Manages sandbox connection state, tool execution history, and panel visibility.
 * Updated to use project-scoped sandbox API (v2).
 *
 * @packageDocumentation
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import { projectSandboxService } from '../services/projectSandboxService';
import { sandboxSSEService } from '../services/sandboxSSEService';
import { buildDesktopWebSocketUrl } from '../services/sandboxWebSocketUtils';
import { logger } from '../utils/logger';

import { useCanvasStore } from './canvasStore';
import { useLayoutModeStore } from './layoutMode';

import type { ToolExecution } from '../components/agent/sandbox/SandboxOutputViewer';
import type { Artifact, DesktopStatus, TerminalStatus } from '../types/agent';

// Sandbox tools that should trigger panel opening
export const SANDBOX_TOOLS = ['read', 'write', 'edit', 'glob', 'grep', 'bash'] as const;

export type SandboxToolName = (typeof SANDBOX_TOOLS)[number];

export type ConnectionStatus = 'idle' | 'connecting' | 'connected' | 'error';

export type PanelMode = 'terminal' | 'output' | 'split';

export interface CurrentTool {
  name: string;
  input: Record<string, unknown>;
  callId?: string | undefined;
  startTime: number;
}

export interface HttpServiceStatus {
  serviceId: string;
  name: string;
  sourceType: 'sandbox_internal' | 'external_url';
  status: 'running' | 'stopped' | 'error';
  serviceUrl: string;
  previewUrl: string;
  wsPreviewUrl: string | null;
  autoOpen: boolean;
  restartToken: string | null;
  updatedAt: string;
}

interface SandboxStoreEvent {
  type: string;
  data: unknown;
}

export interface SandboxState {
  // Panel state
  panelVisible: boolean;
  panelMode: PanelMode;
  activeTab: 'terminal' | 'output' | 'desktop' | 'control' | 'artifacts';

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

  // Error state
  error: string | null;
  // Registered sandbox HTTP preview services
  httpServices: Record<string, HttpServiceStatus>;

  // Tool execution tracking
  currentTool: CurrentTool | null;
  toolExecutions: ToolExecution[];
  maxExecutions: number;

  // Artifact tracking
  artifacts: Map<string, Artifact>;
  artifactsByToolExecution: Map<string, string[]>; // toolExecutionId -> artifactIds

  // Actions
  openPanel: (sandboxId?: string | null) => void;
  closePanel: () => void;
  setActiveTab: (tab: 'terminal' | 'output' | 'desktop' | 'control') => void;
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
  ensureSandbox: (projectId?: string) => Promise<string | null>;
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
  handleSSEEvent: (event: SandboxStoreEvent) => void;

  // Tool execution actions
  setCurrentTool: (tool: CurrentTool | null) => void;
  addToolExecution: (execution: ToolExecution) => void;
  updateToolExecution: (id: string, update: Partial<ToolExecution>) => void;
  clearToolExecutions: () => void;

  // Event handlers for agent integration
  onToolStart: (toolName: string, input: Record<string, unknown>, callId?: string) => void;
  onToolEnd: (callId: string, output?: string, error?: string, durationMs?: number) => void;

  // Artifact actions
  addArtifact: (artifact: Artifact) => void;
  updateArtifact: (id: string, update: Partial<Artifact>) => void;
  getArtifactsByToolExecution: (toolExecutionId: string) => Artifact[];
  clearArtifacts: () => void;

  // Reset
  reset: () => void;
}

const initialState = {
  panelVisible: false,
  panelMode: 'terminal' as PanelMode,
  activeTab: 'terminal' as const,
  activeSandboxId: null,
  activeProjectId: null,
  connectionStatus: 'idle' as ConnectionStatus,
  terminalSessionId: null,
  sseUnsubscribe: null,
  desktopStatus: null as DesktopStatus | null,
  terminalStatus: null as TerminalStatus | null,
  isDesktopLoading: false,
  isTerminalLoading: false,
  httpServices: {} as Record<string, HttpServiceStatus>,
  currentTool: null,
  toolExecutions: [],
  maxExecutions: 50,
  artifacts: new Map<string, Artifact>(),
  artifactsByToolExecution: new Map<string, string[]>(),
  error: null as string | null,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function getField(record: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(record, key)) {
      return record[key];
    }
  }
  return undefined;
}

function getStringField(record: Record<string, unknown>, ...keys: string[]): string | undefined {
  const value = getField(record, ...keys);
  return typeof value === 'string' ? value : undefined;
}

function getNumberField(record: Record<string, unknown>, ...keys: string[]): number | undefined {
  const value = getField(record, ...keys);
  return typeof value === 'number' ? value : undefined;
}

function getBooleanField(record: Record<string, unknown>, ...keys: string[]): boolean | undefined {
  const value = getField(record, ...keys);
  return typeof value === 'boolean' ? value : undefined;
}

function getRecordArrayField(
  record: Record<string, unknown>,
  key: string
): Array<Record<string, unknown>> {
  const value = record[key];
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

const ARTIFACT_CATEGORIES = new Set<Artifact['category']>([
  'image',
  'video',
  'audio',
  'document',
  'code',
  'data',
  'archive',
  'other',
]);

function getArtifactCategory(value: unknown): Artifact['category'] {
  return typeof value === 'string' && ARTIFACT_CATEGORIES.has(value as Artifact['category'])
    ? (value as Artifact['category'])
    : 'other';
}

function getErrorMessage(error: unknown): string | undefined {
  if (error instanceof Error) {
    return error.message;
  }
  if (isRecord(error)) {
    return getStringField(error, 'message');
  }
  return undefined;
}

function getErrorCode(error: unknown): string | undefined {
  if (isRecord(error)) {
    return getStringField(error, 'code');
  }
  return undefined;
}

function getToolContentText(content: Array<{ text?: string | undefined }>): string {
  return content
    .map((item) => item.text ?? '')
    .filter((text) => text.length > 0)
    .join('\n');
}

function appendRestartToken(url: string, restartToken?: string | null): string {
  const base = typeof window !== 'undefined' ? window.location.origin : 'http://localhost';
  const parsed = new URL(url, base);
  if (restartToken) {
    parsed.searchParams.set('_ms_restart', restartToken);
  }
  if (!url.startsWith('/') && /^https?:\/\//i.test(url)) {
    return parsed.toString();
  }
  return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}

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
        set((state) => ({
          activeSandboxId: sandboxId,
          connectionStatus: sandboxId ? 'connected' : 'idle',
          // Preserve terminal and desktop status if sandboxId is set
          terminalSessionId: sandboxId ? state.terminalSessionId : null,
          desktopStatus: sandboxId ? state.desktopStatus : null,
          terminalStatus: sandboxId ? state.terminalStatus : null,
        }));
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
      ensureSandbox: async (projectId?: string) => {
        const { activeProjectId, activeSandboxId } = get();

        // Return existing sandboxId if available
        if (activeSandboxId) {
          return activeSandboxId;
        }

        // Use provided projectId or fall back to activeProjectId
        const targetProjectId = projectId || activeProjectId;
        if (!targetProjectId) {
          logger.warn('[SandboxStore] Cannot ensure sandbox: no active project');
          return null;
        }

        try {
          set({ connectionStatus: 'connecting' });
          const sandbox = await projectSandboxService.ensureSandbox(targetProjectId);

          if (sandbox.desktop_url || sandbox.websocket_url) {
            await projectSandboxService.ensureProxyAuthCookie(targetProjectId);
          }

          // Browser iframe and WebSocket proxy requests authenticate with a scoped cookie.
          const proxyDesktopUrl = sandbox.desktop_url
            ? `/api/v1/projects/${targetProjectId}/sandbox/desktop/proxy/vnc.html`
            : null;
          const desktopWsUrl = sandbox.desktop_url
            ? buildDesktopWebSocketUrl(targetProjectId)
            : null;
          // Terminal uses the existing WebSocket endpoint
          // The TerminalImpl component will build the correct WebSocket URL
          const terminalWsUrl = sandbox.terminal_url
            ? `/api/v1/terminal/${sandbox.sandbox_id}/ws`
            : null;

          set({
            activeSandboxId: sandbox.sandbox_id,
            connectionStatus: sandbox.is_healthy ? 'connected' : 'error',
            desktopStatus: proxyDesktopUrl
              ? {
                  running: true,
                  url: proxyDesktopUrl,
                  wsUrl: desktopWsUrl,
                  display: ':1',
                  resolution: '1280x720',
                  port: sandbox.desktop_port || 6080,
                }
              : null,
            terminalStatus: terminalWsUrl
              ? {
                  running: true,
                  url: terminalWsUrl,
                  port: sandbox.terminal_port || 7681,
                  sessionId: null,
                  pid: null,
                }
              : null,
          });

          logger.info(`[SandboxStore] Sandbox ensured: ${sandbox.sandbox_id} (${sandbox.status})`);
          return sandbox.sandbox_id;
        } catch (error: unknown) {
          logger.error('[SandboxStore] Failed to ensure sandbox:', error);

          // Provide more specific error messages for common issues
          let errorMessage = 'Failed to connect to sandbox';
          const message = getErrorMessage(error);
          const code = getErrorCode(error);
          if (message?.includes('timeout')) {
            errorMessage =
              'Sandbox creation timed out. The service may be starting up, please try again in a moment.';
          } else if (message?.includes('Network Error')) {
            errorMessage = 'Network error. Please check your connection and try again.';
          } else if (code === 'ECONNABORTED') {
            errorMessage = 'Connection aborted. Sandbox creation may still be in progress.';
          }

          set({
            connectionStatus: 'error',
            error: errorMessage,
          });
          return null;
        }
      },

      // Execute tool directly (v2 API)
      executeTool: async (toolName, args, timeout = 30) => {
        const { activeProjectId } = get();

        if (!activeProjectId) {
          logger.warn('[SandboxStore] Cannot execute tool: no active project');
          return { success: false, content: 'No active project', isError: true };
        }

        try {
          const result = await projectSandboxService.executeTool(activeProjectId, {
            tool_name: toolName,
            arguments: args,
            timeout,
          });

          const content = getToolContentText(result.content);

          return {
            success: !result.is_error,
            content,
            isError: result.is_error,
          };
        } catch (error) {
          logger.error('[SandboxStore] Tool execution failed:', error);
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
          onHttpServiceStarted: get().handleSSEEvent,
          onHttpServiceUpdated: get().handleSSEEvent,
          onHttpServiceStopped: get().handleSSEEvent,
          onHttpServiceError: get().handleSSEEvent,
          onStatusUpdate: get().handleSSEEvent,
          onError: (error) => {
            logger.error('[SandboxSSE] Error:', error);
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
      startDesktop: async (resolution = '1920x1080') => {
        const { activeProjectId } = get();

        if (!activeProjectId) {
          logger.warn('[SandboxStore] Cannot start desktop: no active project');
          return;
        }

        set({ isDesktopLoading: true });

        try {
          // Use v2 API (project-scoped)
          const status = await projectSandboxService.startDesktop(activeProjectId, resolution);
          set({ desktopStatus: status, isDesktopLoading: false });
          logger.info(`[SandboxStore] Desktop started for project ${activeProjectId}`);
        } catch (error) {
          logger.error('[SandboxStore] Failed to start desktop:', error);
          set({ isDesktopLoading: false });
          throw error;
        }
      },

      stopDesktop: async () => {
        const { activeProjectId } = get();

        if (!activeProjectId) {
          logger.warn('[SandboxStore] Cannot stop desktop: no active project');
          return;
        }

        set({ isDesktopLoading: true });

        try {
          await projectSandboxService.stopDesktop(activeProjectId);
          set({
            desktopStatus: {
              running: false,
              url: null,
              display: '',
              resolution: '',
              port: 0,
            },
            isDesktopLoading: false,
          });
          logger.info(`[SandboxStore] Desktop stopped for project ${activeProjectId}`);
        } catch (error) {
          logger.error('[SandboxStore] Failed to stop desktop:', error);
          set({ isDesktopLoading: false });
          throw error;
        }
      },

      // Terminal control actions (project-scoped v2 API)
      startTerminal: async () => {
        const { activeProjectId } = get();

        if (!activeProjectId) {
          logger.warn('[SandboxStore] Cannot start terminal: no active project');
          return;
        }

        set({ isTerminalLoading: true });

        try {
          const status = await projectSandboxService.startTerminal(activeProjectId);
          set({ terminalStatus: status, isTerminalLoading: false });
          logger.info(`[SandboxStore] Terminal started for project ${activeProjectId}`);
        } catch (error) {
          logger.error('[SandboxStore] Failed to start terminal:', error);
          set({ isTerminalLoading: false });
          throw error;
        }
      },

      stopTerminal: async () => {
        const { activeProjectId } = get();

        if (!activeProjectId) {
          logger.warn('[SandboxStore] Cannot stop terminal: no active project');
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
          logger.error('[SandboxStore] Failed to stop terminal:', error);
          set({ isTerminalLoading: false });
          throw error;
        }
      },

      // SSE event handler for desktop/terminal events
      handleSSEEvent: (event) => {
        const { type, data: rawData } = event;
        const data = isRecord(rawData) ? rawData : {};
        const { activeProjectId } = get();

        // Build desktop WebSocket URL from project context
        const buildWsUrl = () => {
          if (!activeProjectId) return null;
          return buildDesktopWebSocketUrl(activeProjectId);
        };

        switch (type) {
          case 'desktop_started': {
            const status: DesktopStatus = {
              running: true,
              url: getStringField(data, 'url') ?? null,
              wsUrl: buildWsUrl(),
              display: getStringField(data, 'display') ?? ':0',
              resolution: getStringField(data, 'resolution') ?? '1280x720',
              port: getNumberField(data, 'port') ?? 6080,
            };
            set({ desktopStatus: status });
            break;
          }

          case 'desktop_stopped': {
            set({
              desktopStatus: {
                running: false,
                url: null,
                wsUrl: null,
                display: '',
                resolution: '',
                port: 0,
              },
            });
            break;
          }

          case 'desktop_status': {
            const running = getBooleanField(data, 'running') ?? false;
            const status: DesktopStatus = {
              running,
              url: getStringField(data, 'url') ?? null,
              wsUrl: running ? buildWsUrl() : null,
              display: getStringField(data, 'display') ?? '',
              resolution: getStringField(data, 'resolution') ?? '',
              port: getNumberField(data, 'port') ?? 0,
            };
            set({ desktopStatus: status });
            break;
          }

          case 'terminal_started': {
            const status: TerminalStatus = {
              running: true,
              url: getStringField(data, 'url') ?? null,
              port: getNumberField(data, 'port') ?? 7681,
              sessionId: getStringField(data, 'session_id') ?? null,
              pid: getNumberField(data, 'pid') ?? null,
            };
            set({ terminalStatus: status });
            break;
          }

          case 'terminal_stopped': {
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

          case 'terminal_status': {
            const status: TerminalStatus = {
              running: getBooleanField(data, 'running') ?? false,
              url: getStringField(data, 'url') ?? null,
              port: getNumberField(data, 'port') ?? 0,
              sessionId: getStringField(data, 'session_id') ?? null,
              pid: getNumberField(data, 'pid') ?? null,
            };
            set({ terminalStatus: status });
            break;
          }

          case 'http_service_started':
          case 'http_service_updated':
          case 'http_service_stopped':
          case 'http_service_error': {
            const serviceId = getStringField(data, 'service_id', 'serviceId');
            if (!serviceId) {
              break;
            }

            const rawSourceType = getStringField(data, 'source_type', 'sourceType');
            const sourceType: HttpServiceStatus['sourceType'] =
              rawSourceType === 'external_url' ? 'external_url' : 'sandbox_internal';
            const eventStatus =
              type === 'http_service_stopped'
                ? 'stopped'
                : type === 'http_service_error'
                  ? 'error'
                  : 'running';
            const previewUrl = getStringField(
              data,
              'preview_url',
              'previewUrl',
              'service_url',
              'serviceUrl'
            );

            if (!previewUrl) {
              break;
            }

            const restartToken = getStringField(data, 'restart_token', 'restartToken');
            const autoOpen = getBooleanField(data, 'auto_open', 'autoOpen') ?? true;
            const serviceName = getStringField(data, 'service_name', 'serviceName') ?? serviceId;
            const updatedAt =
              getStringField(data, 'updated_at', 'updatedAt') ?? new Date().toISOString();
            const wsPreviewUrl = getStringField(data, 'ws_preview_url', 'wsPreviewUrl');
            const serviceUrl = getStringField(data, 'service_url', 'serviceUrl') ?? previewUrl;

            const serviceStatus: HttpServiceStatus = {
              serviceId,
              name: serviceName,
              sourceType,
              status: eventStatus,
              serviceUrl,
              previewUrl,
              wsPreviewUrl: wsPreviewUrl || null,
              autoOpen,
              restartToken: restartToken || null,
              updatedAt,
            };

            set((state) => ({
              httpServices: {
                ...state.httpServices,
                [serviceId]: serviceStatus,
              },
            }));

            if ((type === 'http_service_started' || type === 'http_service_updated') && autoOpen) {
              const projectScope = activeProjectId || 'unknown-project';
              const tabId = `sandbox-http:${projectScope}:${serviceId}`;
              const previewTabUrl = appendRestartToken(previewUrl, restartToken);

              useCanvasStore.getState().openTab({
                id: tabId,
                title: serviceName,
                type: 'preview',
                content: previewTabUrl,
                mimeType: 'text/html',
                previewMode: 'url',
                previewUrlPolicy: 'allow-any-url',
                sandboxServiceId: serviceId,
                sandboxServiceSourceType: sourceType,
              });

              const currentMode = useLayoutModeStore.getState().mode;
              if (currentMode !== 'canvas') {
                useLayoutModeStore.getState().setMode('canvas');
              }
            }
            break;
          }

          // Artifact events
          case 'artifact_created': {
            const artifactId = getStringField(data, 'artifact_id');
            const filename = getStringField(data, 'filename');
            const mimeType = getStringField(data, 'mime_type') ?? 'application/octet-stream';
            if (!artifactId || !filename) {
              break;
            }

            // Create pending artifact
            const artifact: Artifact = {
              id: artifactId,
              projectId: '', // Will be set on ready
              tenantId: '',
              sandboxId: getStringField(data, 'sandbox_id'),
              toolExecutionId: getStringField(data, 'tool_execution_id'),
              filename,
              mimeType,
              category: getArtifactCategory(getField(data, 'category')),
              sizeBytes: getNumberField(data, 'size_bytes') ?? 0,
              status: 'uploading',
              sourceTool: getStringField(data, 'source_tool'),
              sourcePath: getStringField(data, 'source_path'),
              createdAt: new Date().toISOString(),
            };
            get().addArtifact(artifact);
            logger.debug('[SandboxStore] Artifact created', { artifactId });
            break;
          }

          case 'artifact_ready': {
            const artifactId = getStringField(data, 'artifact_id');
            if (!artifactId) {
              break;
            }

            // Update artifact with URL
            get().updateArtifact(artifactId, {
              url: getStringField(data, 'url'),
              previewUrl: getStringField(data, 'preview_url'),
              status: 'ready',
              metadata: isRecord(data.metadata) ? data.metadata : undefined,
            });
            logger.debug('[SandboxStore] Artifact ready', {
              artifactId,
              url: getStringField(data, 'url'),
            });
            break;
          }

          case 'artifact_error': {
            const artifactId = getStringField(data, 'artifact_id');
            if (!artifactId) {
              break;
            }

            get().updateArtifact(artifactId, {
              status: 'error',
              errorMessage: getStringField(data, 'error'),
            });
            logger.warn('[SandboxStore] Artifact error', {
              artifactId,
              error: getStringField(data, 'error'),
            });
            break;
          }

          case 'artifacts_batch': {
            // Add multiple artifacts at once
            const artifacts = getRecordArrayField(data, 'artifacts');
            if (artifacts.length > 0) {
              for (const info of artifacts) {
                const artifactId = getStringField(info, 'id');
                const filename = getStringField(info, 'filename');
                const mimeType =
                  getStringField(info, 'mimeType', 'mime_type') ?? 'application/octet-stream';
                if (!artifactId || !filename) {
                  continue;
                }

                const url = getStringField(info, 'url');
                const artifact: Artifact = {
                  id: artifactId,
                  projectId: '',
                  tenantId: '',
                  sandboxId: getStringField(data, 'sandbox_id'),
                  toolExecutionId: getStringField(data, 'tool_execution_id'),
                  filename,
                  mimeType,
                  category: getArtifactCategory(getField(info, 'category')),
                  sizeBytes: getNumberField(info, 'sizeBytes', 'size_bytes') ?? 0,
                  url,
                  previewUrl: getStringField(info, 'previewUrl', 'preview_url'),
                  status: url ? 'ready' : 'pending',
                  sourceTool:
                    getStringField(info, 'sourceTool', 'source_tool') ??
                    getStringField(data, 'source_tool'),
                  metadata: isRecord(info.metadata) ? info.metadata : undefined,
                  createdAt: new Date().toISOString(),
                };
                get().addArtifact(artifact);
              }
              logger.debug('[SandboxStore] Artifacts batch added', {
                count: artifacts.length,
              });
            }
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
          const executions = [execution, ...state.toolExecutions].slice(0, state.maxExecutions);
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
        const isSandboxTool = SANDBOX_TOOLS.includes(toolName as SandboxToolName);

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
            activeTab: 'output',
          }));

          // Add to executions (pending state)
          const execution: ToolExecution = {
            id: callId || `${toolName}-${String(Date.now())}`,
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
          // Get artifacts for this tool execution
          const artifacts = get().getArtifactsByToolExecution(callId);
          get().updateToolExecution(callId, {
            output,
            error,
            durationMs,
            artifacts: artifacts.length > 0 ? artifacts : undefined,
          });
        }
      },

      // Artifact actions
      addArtifact: (artifact) => {
        set((state) => {
          const newArtifacts = new Map(state.artifacts);
          newArtifacts.set(artifact.id, artifact);

          // Track by tool execution if available
          const newByToolExecution = new Map(state.artifactsByToolExecution);
          if (artifact.toolExecutionId) {
            const existing = newByToolExecution.get(artifact.toolExecutionId) || [];
            newByToolExecution.set(artifact.toolExecutionId, [...existing, artifact.id]);
          }

          return {
            artifacts: newArtifacts,
            artifactsByToolExecution: newByToolExecution,
          };
        });

        logger.debug('[SandboxStore] Added artifact', { artifactId: artifact.id });
      },

      updateArtifact: (id, update) => {
        set((state) => {
          const artifact = state.artifacts.get(id);
          if (!artifact) return state;

          const newArtifacts = new Map(state.artifacts);
          newArtifacts.set(id, { ...artifact, ...update });

          return { artifacts: newArtifacts };
        });
      },

      getArtifactsByToolExecution: (toolExecutionId) => {
        const state = get();
        const artifactIds = state.artifactsByToolExecution.get(toolExecutionId) || [];
        return artifactIds
          .map((id) => state.artifacts.get(id))
          .filter((a): a is Artifact => a !== undefined);
      },

      clearArtifacts: () => {
        set({
          artifacts: new Map(),
          artifactsByToolExecution: new Map(),
        });
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
      name: 'sandbox-store-v2',
    }
  )
);

// Selectors
export const useSandboxPanelVisible = () => useSandboxStore((state) => state.panelVisible);

export const useActiveSandboxId = () => useSandboxStore((state) => state.activeSandboxId);

export const useSandboxConnectionStatus = () => useSandboxStore((state) => state.connectionStatus);

export const useCurrentTool = () => useSandboxStore((state) => state.currentTool);

export const useToolExecutions = () => useSandboxStore((state) => state.toolExecutions);

export const useSandboxActiveTab = () => useSandboxStore((state) => state.activeTab);

// New selectors for desktop and terminal status
export const useDesktopStatus = () => useSandboxStore((state) => state.desktopStatus);

export const useTerminalStatus = () => useSandboxStore((state) => state.terminalStatus);

// Project-scoped selectors
export const useActiveProjectId = () => useSandboxStore((state) => state.activeProjectId);

export const useEnsureSandbox = () => useSandboxStore((state) => state.ensureSandbox);

export const useExecuteTool = () => useSandboxStore((state) => state.executeTool);

// Artifact selectors
export const useArtifacts = () => useSandboxStore((state) => Array.from(state.artifacts.values()));

export const useArtifactById = (id: string) => useSandboxStore((state) => state.artifacts.get(id));

export const useArtifactsByToolExecution = (toolExecutionId: string) =>
  useSandboxStore((state) => state.getArtifactsByToolExecution(toolExecutionId));

// Helper to check if a tool is a sandbox tool
export function isSandboxTool(toolName: string): boolean {
  return SANDBOX_TOOLS.includes(toolName as SandboxToolName);
}
