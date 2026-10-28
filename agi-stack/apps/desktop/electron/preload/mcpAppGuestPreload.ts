import { contextBridge, ipcRenderer } from 'electron';
import {
  MCP_APP_GUEST_CHANNEL,
  MCP_APP_GUEST_EVENT,
  type McpAppGuestBridge,
  type McpAppGuestEvent,
} from '../../src/features/chat/mcpAppGuestProtocol';

// Subframes, including the untrusted SDK sandbox, receive no Electron bridge.
if (process.isMainFrame) {
  const bridge: McpAppGuestBridge = Object.freeze({
    initialize: () => ipcRenderer.invoke(MCP_APP_GUEST_CHANNEL, 'initialize'),
    ready: (input) => ipcRenderer.invoke(MCP_APP_GUEST_CHANNEL, 'ready', input),
    request: (input) => ipcRenderer.invoke(MCP_APP_GUEST_CHANNEL, 'request', input),
    cancel: (input) => ipcRenderer.invoke(MCP_APP_GUEST_CHANNEL, 'cancel', input),
    subscribe(listener) {
      const wrapped = (_event: unknown, payload: McpAppGuestEvent) => listener(payload);
      ipcRenderer.on(MCP_APP_GUEST_EVENT, wrapped);
      return () => ipcRenderer.removeListener(MCP_APP_GUEST_EVENT, wrapped);
    },
  });
  contextBridge.exposeInMainWorld('__MEMSTACK_MCP_APP_GUEST__', bridge);
}
