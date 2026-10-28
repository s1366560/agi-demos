import type { McpAppGuestHostEvent } from '../../src/features/chat/mcpAppGuestProtocol';
const MCP_APP_GUEST_EVENT = 'agistack:mcp-app-guest-event';
import { requireDeviceMcpRequestV2 } from '../../src/api/deviceMcpContractV2';
import { contextBridge, ipcRenderer } from 'electron';
import { parseComputerUseInputEvent, type ComputerUseInputEvent } from '../../src/api/computerUseInput';

import type { DesktopDisplayCapture } from '../main/displayCapturePolicy';
import type {
  DesktopNativeCapabilitySnapshot,
  WebControlPlaneRequest,
} from '../main/webControlPlanePolicy';
import type {
  NativeFileIngestRequest,
  NativeFileIngestResult,
  NativeFileOpenRequest,
  NativeFileOpenResult,
  NativeFileSaveRequest,
  NativeFileSaveResult,
} from '../main/nativeFileDialogPolicy';
import {
  parseUpdateLifecycleState,
  type UpdateLifecycleState,
} from '../main/updateLifecycle';
import {
  compactNativeFileIngestRequest,
  compactNativeFileIngestResult,
  compactNativeFileOpenResult,
  compactNativeFileSaveRequest,
  validateNativeFileOpenRequest,
  validateNativeFileSaveResult,
} from './nativeFilePreloadPolicy';

const DESKTOP_COMMAND_CHANNEL = 'agistack:desktop-command';
const NATIVE_FILE_SAVE_CHANNEL = 'agistack:native-file-save';
const NATIVE_FILE_OPEN_CHANNEL = 'agistack:native-file-open';
const NATIVE_FILE_INGEST_CHANNEL = 'agistack:native-file-ingest';
const SIDECAR_RECOVERED_CHANNEL = 'agistack:sidecar-recovered';
const OAUTH_SESSION_CHANGED_CHANNEL = 'agistack:oauth-session-changed';
const CLOUD_SOCKET_EVENT_CHANNEL = 'agistack:cloud-socket-event';
const IAB_TABS_CHANGED_CHANNEL = 'agistack:iab-tabs-changed';
const IAB_VISIBILITY_REQUESTED_CHANNEL = 'agistack:iab-visibility-requested';
const COMPUTER_USE_ACTIVITY_CHANNEL = 'agistack:computer-use-activity';
const COMPUTER_USE_INPUT_CHANNEL = 'agistack:computer-use-input';
const UPDATE_STATE_CHANNEL = 'agistack:update-state';
const UPDATE_CHECK_CHANNEL = 'agistack:update-check';
const UPDATE_RESTART_TO_APPLY_CHANNEL = 'agistack:update-restart-to-apply';
const UPDATE_STATE_CHANGED_CHANNEL = 'agistack:update-state-changed';
const allowedCommands = new Set([
  'frontend_ready',
  'platform_plugin_authority_select_v2',
  'platform_plugin_renderer_distribution_current_v2',
  'platform_plugin_renderer_delivery_current_v2',
  'platform_plugin_renderer_receipt_submit_v2',
  'platform_plugin_renderer_owner_retire_v2',
  'trusted_session_clear',
  'local_trusted_session_save',
  'local_trusted_session_load',
  'local_trusted_session_clear',
  'open_device_authorization_url',
  'get_desktop_capabilities',
  'capture_current_display',
  'open_web_control_plane',
  'cloud_request',
  'cloud_session_projection',
  'cloud_socket_open',
  'cloud_socket_send',
  'cloud_socket_close',
  'sandbox_desktop_grant_open',
  'sandbox_desktop_grant_close',
  'cloud_auth_password',
  'cloud_auth_force_password_change',
  'cloud_auth_device_begin',
  'cloud_auth_device_poll',
  'cloud_auth_device_cancel',
  'cloud_auth_signout',
  'cloud_auth_cancel_pending',
  'cloud_auth_status',
  'oauth_list_providers',
  'oauth_begin_authorization',
  'oauth_restore_authorization',
  'oauth_cancel_authorization',
  'cloud_request_cancel',
  'local_runtime_status',
  'local_runtime_configure',
  'workspace_core_status',
  'browser_bridge_install',
  'browser_bridge_uninstall',
  'browser_bridge_status',
  'computer_use_manage_v2',
  'device_mcp_manage_v2',
  'mcp_app_guest_open',
  'mcp_app_guest_start',
  'mcp_app_guest_update',
  'mcp_app_guest_layout',
  'mcp_app_guest_respond',
  'mcp_app_guest_release',
  'mcp_app_guest_prune',
  'mcp_app_guest_clear',
  'mcp_app_frame_register',
  'mcp_app_frame_unregister',
  'mcp_app_operation',
  'mcp_app_operation_prepare',
  'mcp_app_operation_cancel',
  'browser_auth_pending',
  'browser_auth_respond',
  'request_microphone_access',
  'focus_main_window',
  'window_controls',
  'iab_status',
  'iab_list_tabs',
  'iab_create_tab',
  'iab_close_tab',
  'iab_focus_tab',
  'iab_show_pane',
  'iab_set_bounds',
  'iab_hide_pane',
]);

async function invokeDesktopCommand<T = unknown>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  if (!allowedCommands.has(command)) {
    throw new Error('desktop command is not supported');
  }
  if (command === 'device_mcp_manage_v2') requireDeviceMcpRequestV2(args);
  return ipcRenderer.invoke(DESKTOP_COMMAND_CHANNEL, command, args) as Promise<T>;
}

const commandBridge = Object.freeze({
  invoke: invokeDesktopCommand,
});

function captureCurrentDisplay(): Promise<DesktopDisplayCapture> {
  return invokeDesktopCommand('capture_current_display');
}

function getCapabilities(): Promise<DesktopNativeCapabilitySnapshot> {
  return invokeDesktopCommand('get_desktop_capabilities');
}

function openWebControlPlane({
  destination,
  tenantId,
  projectId,
}: WebControlPlaneRequest): Promise<void> {
  return invokeDesktopCommand('open_web_control_plane', {
    destination,
    tenantId,
    projectId,
  });
}

function focusMainWindow(): Promise<void> {
  return invokeDesktopCommand('focus_main_window');
}

const windowControls = Object.freeze({
  minimize: (): Promise<void> => invokeDesktopCommand('window_controls', { action: 'minimize' }),
  maximize: (): Promise<void> => invokeDesktopCommand('window_controls', { action: 'maximize' }),
  unmaximize: (): Promise<void> =>
    invokeDesktopCommand('window_controls', { action: 'unmaximize' }),
  toggleMaximize: (): Promise<void> =>
    invokeDesktopCommand('window_controls', { action: 'toggle_maximize' }),
  isMaximized: (): Promise<boolean> =>
    invokeDesktopCommand('window_controls', { action: 'is_maximized' }).then(
      (result: unknown) => result === true,
    ),
  close: (): Promise<void> => invokeDesktopCommand('window_controls', { action: 'close' }),
});

async function saveNativeFile(request: NativeFileSaveRequest): Promise<NativeFileSaveResult> {
  const result: unknown = await ipcRenderer.invoke(
    NATIVE_FILE_SAVE_CHANNEL,
    compactNativeFileSaveRequest(request),
  );
  return validateNativeFileSaveResult(result);
}

async function openNativeFile(request: NativeFileOpenRequest): Promise<NativeFileOpenResult> {
  const validatedRequest = validateNativeFileOpenRequest(request);
  const result: unknown = await ipcRenderer.invoke(NATIVE_FILE_OPEN_CHANNEL, validatedRequest);
  return compactNativeFileOpenResult(result, validatedRequest.purpose);
}

async function ingestNativeFile(request: NativeFileIngestRequest): Promise<NativeFileIngestResult> {
  const result: unknown = await ipcRenderer.invoke(
    NATIVE_FILE_INGEST_CHANNEL,
    compactNativeFileIngestRequest(request),
  );
  return compactNativeFileIngestResult(result);
}

const fileBridge = Object.freeze({
  save: saveNativeFile,
  open: openNativeFile,
  ingest: ingestNativeFile,
});

async function getUpdateState(): Promise<UpdateLifecycleState> {
  return parseUpdateLifecycleState(await ipcRenderer.invoke(UPDATE_STATE_CHANNEL));
}

async function checkForUpdate(): Promise<UpdateLifecycleState> {
  return parseUpdateLifecycleState(await ipcRenderer.invoke(UPDATE_CHECK_CHANNEL));
}

async function restartToApplyUpdate(): Promise<UpdateLifecycleState> {
  return parseUpdateLifecycleState(await ipcRenderer.invoke(UPDATE_RESTART_TO_APPLY_CHANNEL));
}

function subscribeToUpdateState(listener: (state: UpdateLifecycleState) => void): () => void {
  if (typeof listener !== 'function') throw new Error('update state listener is invalid');
  const wrappedListener = (_event: Electron.IpcRendererEvent, payload: unknown): void => {
    listener(parseUpdateLifecycleState(payload));
  };
  ipcRenderer.on(UPDATE_STATE_CHANGED_CHANNEL, wrappedListener);
  return () => ipcRenderer.removeListener(UPDATE_STATE_CHANGED_CHANNEL, wrappedListener);
}

const updateBridge = Object.freeze({
  getState: getUpdateState,
  check: checkForUpdate,
  restartToApply: restartToApplyUpdate,
  subscribe: subscribeToUpdateState,
  // Read-only compatibility for renderers built before the v2 lifecycle.
  onStateChanged: subscribeToUpdateState,
});

function onSidecarRecovered(listener: () => void): () => void {
  if (typeof listener !== 'function') {
    throw new Error('sidecar recovery listener is invalid');
  }
  const wrappedListener = (): void => listener();
  ipcRenderer.on(SIDECAR_RECOVERED_CHANNEL, wrappedListener);
  return () => ipcRenderer.removeListener(SIDECAR_RECOVERED_CHANNEL, wrappedListener);
}

function onOAuthSessionChanged(listener: (payload: unknown) => void): () => void {
  if (typeof listener !== 'function') {
    throw new Error('OAuth session listener is invalid');
  }
  const wrappedListener = (_event: Electron.IpcRendererEvent, payload: unknown): void =>
    listener(payload);
  ipcRenderer.on(OAUTH_SESSION_CHANGED_CHANNEL, wrappedListener);
  return () => ipcRenderer.removeListener(OAUTH_SESSION_CHANGED_CHANNEL, wrappedListener);
}

function onCloudSocketEvent(listener: (payload: unknown) => void): () => void {
  if (typeof listener !== 'function') {
    throw new Error('Cloud socket listener is invalid');
  }
  const wrappedListener = (_event: Electron.IpcRendererEvent, payload: unknown): void =>
    listener(payload);
  ipcRenderer.on(CLOUD_SOCKET_EVENT_CHANNEL, wrappedListener);
  return () => ipcRenderer.removeListener(CLOUD_SOCKET_EVENT_CHANNEL, wrappedListener);
}

function onComputerUseActivity(listener:(payload:unknown)=>void):()=>void {
  if(typeof listener!=='function')throw new Error('Computer use listener is invalid');
  const wrapped=(_event:unknown,payload:unknown)=>listener(payload);
  ipcRenderer.on(COMPUTER_USE_ACTIVITY_CHANNEL,wrapped);
  return ()=>ipcRenderer.removeListener(COMPUTER_USE_ACTIVITY_CHANNEL,wrapped);
}

function onComputerUseInput(listener: (payload: ComputerUseInputEvent) => void): () => void {
  if (typeof listener !== 'function') throw new Error('Computer use listener is invalid');
  const wrapped = (_event: unknown, payload: unknown) => {
    const event = parseComputerUseInputEvent(payload);
    if (event) listener(event);
  };
  ipcRenderer.on(COMPUTER_USE_INPUT_CHANNEL, wrapped);
  return () => ipcRenderer.removeListener(COMPUTER_USE_INPUT_CHANNEL, wrapped);
}

export type IabTabSnapshot = Readonly<{
  tabId: number;
  windowId: number;
  title: string;
  url: string;
  active: boolean;
}>;

export type IabTabsChangedPayload = Readonly<{
  tabs: readonly IabTabSnapshot[];
  activeTabId: number | null;
}>;

function onIabTabsChanged(listener: (payload: IabTabsChangedPayload) => void): () => void {
  if (typeof listener !== 'function') {
    throw new Error('iab tabs-changed listener is invalid');
  }
  const wrappedListener = (_event: unknown, payload: IabTabsChangedPayload): void =>
    listener(payload);
  ipcRenderer.on(IAB_TABS_CHANGED_CHANNEL, wrappedListener);
  return () => ipcRenderer.removeListener(IAB_TABS_CHANGED_CHANNEL, wrappedListener);
}

function onIabVisibilityRequested(listener: (visible: boolean) => void): () => void {
  if (typeof listener !== 'function') throw new Error('iab visibility listener is invalid');
  const wrapped = (_event: unknown, visible: unknown): void => {
    if (typeof visible === 'boolean') listener(visible);
  };
  ipcRenderer.on(IAB_VISIBILITY_REQUESTED_CHANNEL, wrapped);
  return () => ipcRenderer.removeListener(IAB_VISIBILITY_REQUESTED_CHANNEL, wrapped);
}

const iabBridge = Object.freeze({
  status: (): Promise<{ status: string }> => invokeDesktopCommand('iab_status'),
  listTabs: (): Promise<IabTabsChangedPayload> => invokeDesktopCommand('iab_list_tabs'),
  createTab: (url?: string): Promise<{ tabId: number }> =>
    invokeDesktopCommand('iab_create_tab', url === undefined ? {} : { url }),
  closeTab: (tabId: number): Promise<void> =>
    invokeDesktopCommand('iab_close_tab', { tabId }),
  focusTab: (tabId: number): Promise<void> =>
    invokeDesktopCommand('iab_focus_tab', { tabId }),
  showPane: (bounds: {
    x: number;
    y: number;
    width: number;
    height: number;
  }): Promise<void> => invokeDesktopCommand('iab_show_pane', bounds),
  setBounds: (bounds: {
    x: number;
    y: number;
    width: number;
    height: number;
  }): Promise<void> => invokeDesktopCommand('iab_set_bounds', bounds),
  hidePane: (): Promise<void> => invokeDesktopCommand('iab_hide_pane'),
  onTabsChanged: onIabTabsChanged,
  onVisibilityRequested: onIabVisibilityRequested,
});

function onMcpAppGuest(listener: (payload: McpAppGuestHostEvent) => void): () => void {
  if (typeof listener !== 'function') throw new Error('MCP App listener is invalid');
  const wrapped = (_event: unknown, payload: McpAppGuestHostEvent) => listener(payload);
  ipcRenderer.on(MCP_APP_GUEST_EVENT, wrapped);
  return () => ipcRenderer.removeListener(MCP_APP_GUEST_EVENT, wrapped);
}

contextBridge.exposeInMainWorld(
  '__MEMSTACK_DESKTOP__',
  Object.freeze({
    runtime: 'electron',
    platform: process.platform,
    core: commandBridge,
    captureCurrentDisplay,
    getCapabilities,
    openWebControlPlane,
    focusMainWindow,
    windowControls,
    files: fileBridge,
    updates: updateBridge,
    iab: iabBridge,
    events: Object.freeze({
      onMcpAppGuest,
      onSidecarRecovered,
      onOAuthSessionChanged,
      onCloudSocketEvent,
      onComputerUseActivity,
      onComputerUseInput,
    }),
  }),
);
