/// <reference types="vite/client" />

type TauriInvoke = <T = string>(command: string, args?: Record<string, unknown>) => Promise<T>;

interface Window {
  __TAURI__?: {
    core?: {
      invoke?: TauriInvoke;
    };
  };
  __TAURI_INTERNALS__?: unknown;
}
