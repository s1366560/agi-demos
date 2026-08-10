import { vi } from 'vitest';
import type { ChromeApi, ChromeEvent, NativePort, TabLike } from '../src/chrome-api';

export interface MockEvent<T extends unknown[]> extends ChromeEvent<T> {
  fire(...args: T): void;
  listenerCount(): number;
}

export function createMockEvent<T extends unknown[]>(): MockEvent<T> {
  const listeners: Array<(...args: T) => void> = [];
  return {
    addListener: (callback) => {
      listeners.push(callback);
    },
    fire: (...args) => {
      for (const listener of [...listeners]) listener(...args);
    },
    listenerCount: () => listeners.length,
  };
}

export interface MockPort extends NativePort {
  postMessage: ReturnType<typeof vi.fn>;
  onMessage: MockEvent<[unknown]>;
  onDisconnect: MockEvent<[]>;
}

export interface ChromeMock extends ChromeApi {
  runtime: ChromeApi['runtime'] & {
    connectNative: ReturnType<typeof vi.fn>;
    sendMessage: ReturnType<typeof vi.fn>;
    lastError: { message?: string } | null;
    onStartup: MockEvent<[]>;
    onInstalled: MockEvent<[]>;
    onMessage: MockEvent<[unknown, { tab?: { id?: number } }, (response?: unknown) => void]>;
  };
  debugger: ChromeApi['debugger'] & {
    attach: ReturnType<typeof vi.fn>;
    detach: ReturnType<typeof vi.fn>;
    sendCommand: ReturnType<typeof vi.fn>;
    onEvent: MockEvent<[{ tabId?: number }, string, unknown]>;
    onDetach: MockEvent<[{ tabId?: number }, string]>;
  };
  tabs: {
    query: ReturnType<typeof vi.fn>;
    create: ReturnType<typeof vi.fn>;
    get: ReturnType<typeof vi.fn>;
    update: ReturnType<typeof vi.fn>;
    remove: ReturnType<typeof vi.fn>;
    group: ReturnType<typeof vi.fn>;
    ungroup: ReturnType<typeof vi.fn>;
    sendMessage: ReturnType<typeof vi.fn>;
  };
  windows: {
    get: ReturnType<typeof vi.fn>;
  };
  tabGroups: {
    get: ReturnType<typeof vi.fn>;
    update: ReturnType<typeof vi.fn>;
  };
  scripting: {
    executeScript: ReturnType<typeof vi.fn>;
  };
  alarms: {
    create: ReturnType<typeof vi.fn>;
    clear: ReturnType<typeof vi.fn>;
    onAlarm: MockEvent<[{ name: string }]>;
  };
  storage: {
    local: {
      set: ReturnType<typeof vi.fn>;
      get: ReturnType<typeof vi.fn>;
    };
    onChanged: MockEvent<[Record<string, { newValue?: unknown }>, string]>;
  };
}

export function createChromeMock(): { chrome: ChromeMock; port: MockPort } {
  const port: MockPort = {
    postMessage: vi.fn(),
    onMessage: createMockEvent<[unknown]>(),
    onDisconnect: createMockEvent<[]>(),
  };

  const chrome: ChromeMock = {
    runtime: {
      id: 'enbljdpbhdllbbkcjhccmbgpkfmcdkkl',
      lastError: null,
      connectNative: vi.fn(() => port),
      sendMessage: vi.fn(async () => undefined),
      onStartup: createMockEvent<[]>(),
      onInstalled: createMockEvent<[]>(),
      onMessage: createMockEvent<[unknown, { tab?: { id?: number } }, (response?: unknown) => void]>(),
    },
    debugger: {
      attach: vi.fn(async () => undefined),
      detach: vi.fn(async () => undefined),
      sendCommand: vi.fn(async () => ({})),
      onEvent: createMockEvent<[{ tabId?: number }, string, unknown]>(),
      onDetach: createMockEvent<[{ tabId?: number }, string]>(),
    },
    tabs: {
      query: vi.fn(async (): Promise<TabLike[]> => []),
      create: vi.fn(async (): Promise<TabLike> => ({ id: 99, windowId: 1 })),
      get: vi.fn(async (): Promise<TabLike> => ({ id: 99, windowId: 1, active: true })),
      update: vi.fn(async () => ({})),
      remove: vi.fn(async () => undefined),
      group: vi.fn(async () => 555),
      ungroup: vi.fn(async () => undefined),
      sendMessage: vi.fn(async () => undefined),
    },
    windows: {
      get: vi.fn(async () => ({ id: 1, type: 'normal', state: 'normal' })),
    },
    tabGroups: {
      get: vi.fn(async () => ({ id: 555 })),
      update: vi.fn(async () => ({})),
    },
    scripting: {
      executeScript: vi.fn(async () => []),
    },
    alarms: {
      create: vi.fn(),
      clear: vi.fn(),
      onAlarm: createMockEvent<[{ name: string }]>(),
    },
    storage: {
      local: {
        set: vi.fn(),
        get: vi.fn(async () => ({})),
      },
      onChanged: createMockEvent<[Record<string, { newValue?: unknown }>, string]>(),
    },
  };

  return { chrome, port };
}

/** Let queued microtasks and zero-delay timers run. */
export async function flush(rounds = 10): Promise<void> {
  for (let i = 0; i < rounds; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}
