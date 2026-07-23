import { contextBridge, ipcRenderer } from 'electron';

const DESKTOP_COMMAND_CHANNEL = 'agistack:desktop-command';
const SIDECAR_RECOVERED_CHANNEL = 'agistack:sidecar-recovered';
const allowedCommands = new Set([
  'frontend_ready',
  'trusted_session_save',
  'trusted_session_load',
  'trusted_session_clear',
  'local_trusted_session_save',
  'local_trusted_session_load',
  'local_trusted_session_clear',
  'open_device_authorization_url',
  'local_runtime_status',
  'local_runtime_configure',
]);

async function invokeDesktopCommand<T = unknown>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  if (!allowedCommands.has(command)) {
    throw new Error('desktop command is not supported');
  }
  return ipcRenderer.invoke(DESKTOP_COMMAND_CHANNEL, command, args) as Promise<T>;
}

const commandBridge = Object.freeze({
  invoke: invokeDesktopCommand,
});

function onSidecarRecovered(listener: () => void): () => void {
  if (typeof listener !== 'function') {
    throw new Error('sidecar recovery listener is invalid');
  }
  const wrappedListener = (): void => listener();
  ipcRenderer.on(SIDECAR_RECOVERED_CHANNEL, wrappedListener);
  return () => ipcRenderer.removeListener(SIDECAR_RECOVERED_CHANNEL, wrappedListener);
}

contextBridge.exposeInMainWorld(
  '__MEMSTACK_DESKTOP__',
  Object.freeze({
    runtime: 'electron',
    core: commandBridge,
    events: Object.freeze({
      onSidecarRecovered,
    }),
  }),
);
