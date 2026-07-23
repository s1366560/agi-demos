/// <reference types="vite/client" />

type DesktopInvoke = <T = string>(command: string, args?: Record<string, unknown>) => Promise<T>;

interface Window {
  __MEMSTACK_DESKTOP__?: {
    runtime: 'electron';
    core?: {
      invoke?: DesktopInvoke;
    };
    events?: {
      onSidecarRecovered?: (listener: () => void) => () => void;
    };
  };
}
