import { vi, type Mock } from 'vitest';
import type { ChromeApi, ChromeEvent, NativePort } from '../src/chrome-api';

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
  postMessage: Mock<NativePort['postMessage']>;
  onMessage: MockEvent<[unknown]>;
  onDisconnect: MockEvent<[]>;
}

export interface ChromeMock extends ChromeApi {
  runtime: Omit<
    ChromeApi['runtime'],
    'connectNative' | 'sendMessage' | 'lastError' | 'onStartup' | 'onInstalled' | 'onMessage'
  > & {
    connectNative: Mock<ChromeApi['runtime']['connectNative']>;
    sendMessage: Mock<ChromeApi['runtime']['sendMessage']>;
    lastError: { message?: string } | null;
    onStartup: MockEvent<[]>;
    onInstalled: MockEvent<[]>;
    onMessage: MockEvent<[unknown, { tab?: { id?: number } }, (response?: unknown) => void]>;
  };
  debugger: Omit<ChromeApi['debugger'], 'attach' | 'detach' | 'sendCommand' | 'onEvent' | 'onDetach'> & {
    attach: Mock<ChromeApi['debugger']['attach']>;
    detach: Mock<ChromeApi['debugger']['detach']>;
    sendCommand: Mock<ChromeApi['debugger']['sendCommand']>;
    onEvent: MockEvent<[{ tabId?: number }, string, unknown]>;
    onDetach: MockEvent<[{ tabId?: number }, string]>;
  };
  tabs: {
    query: Mock<ChromeApi['tabs']['query']>;
    create: Mock<ChromeApi['tabs']['create']>;
    get: Mock<ChromeApi['tabs']['get']>;
    update: Mock<ChromeApi['tabs']['update']>;
    remove: Mock<ChromeApi['tabs']['remove']>;
    group: Mock<ChromeApi['tabs']['group']>;
    ungroup: Mock<ChromeApi['tabs']['ungroup']>;
    sendMessage: Mock<ChromeApi['tabs']['sendMessage']>;
  };
  windows: {
    get: Mock<ChromeApi['windows']['get']>;
  };
  tabGroups: {
    get: Mock<ChromeApi['tabGroups']['get']>;
    update: Mock<ChromeApi['tabGroups']['update']>;
  };
  scripting: {
    executeScript: Mock<ChromeApi['scripting']['executeScript']>;
  };
  alarms: {
    create: Mock<ChromeApi['alarms']['create']>;
    clear: Mock<ChromeApi['alarms']['clear']>;
    onAlarm: MockEvent<[{ name: string }]>;
  };
  storage: {
    local: {
      set: Mock<ChromeApi['storage']['local']['set']>;
      get: Mock<ChromeApi['storage']['local']['get']>;
    };
    onChanged: MockEvent<[Record<string, { newValue?: unknown }>, string]>;
  };
}

export function createChromeMock(): { chrome: ChromeMock; port: MockPort } {
  const port: MockPort = {
    postMessage: vi.fn<NativePort['postMessage']>(),
    onMessage: createMockEvent<[unknown]>(),
    onDisconnect: createMockEvent<[]>(),
  };

  const chrome: ChromeMock = {
    runtime: {
      id: 'enbljdpbhdllbbkcjhccmbgpkfmcdkkl',
      lastError: null,
      connectNative: vi.fn<ChromeApi['runtime']['connectNative']>(() => port),
      sendMessage: vi.fn<ChromeApi['runtime']['sendMessage']>(async () => undefined),
      onStartup: createMockEvent<[]>(),
      onInstalled: createMockEvent<[]>(),
      onMessage: createMockEvent<[unknown, { tab?: { id?: number } }, (response?: unknown) => void]>(),
    },
    debugger: {
      attach: vi.fn<ChromeApi['debugger']['attach']>(async () => undefined),
      detach: vi.fn<ChromeApi['debugger']['detach']>(async () => undefined),
      sendCommand: vi.fn<ChromeApi['debugger']['sendCommand']>(async () => ({})),
      onEvent: createMockEvent<[{ tabId?: number }, string, unknown]>(),
      onDetach: createMockEvent<[{ tabId?: number }, string]>(),
    },
    tabs: {
      query: vi.fn<ChromeApi['tabs']['query']>(async () => []),
      create: vi.fn<ChromeApi['tabs']['create']>(async () => ({ id: 99, windowId: 1 })),
      get: vi.fn<ChromeApi['tabs']['get']>(async () => ({ id: 99, windowId: 1, active: true })),
      update: vi.fn<ChromeApi['tabs']['update']>(async () => ({})),
      remove: vi.fn<ChromeApi['tabs']['remove']>(async () => undefined),
      group: vi.fn<ChromeApi['tabs']['group']>(async () => 555),
      ungroup: vi.fn<ChromeApi['tabs']['ungroup']>(async () => undefined),
      sendMessage: vi.fn<ChromeApi['tabs']['sendMessage']>(async () => undefined),
    },
    windows: {
      get: vi.fn<ChromeApi['windows']['get']>(async () => ({ id: 1, type: 'normal', state: 'normal' })),
    },
    tabGroups: {
      get: vi.fn<ChromeApi['tabGroups']['get']>(async () => ({ id: 555 })),
      update: vi.fn<ChromeApi['tabGroups']['update']>(async () => ({})),
    },
    scripting: {
      executeScript: vi.fn<ChromeApi['scripting']['executeScript']>(async () => []),
    },
    alarms: {
      create: vi.fn<ChromeApi['alarms']['create']>(),
      clear: vi.fn<ChromeApi['alarms']['clear']>(),
      onAlarm: createMockEvent<[{ name: string }]>(),
    },
    storage: {
      local: {
        set: vi.fn<ChromeApi['storage']['local']['set']>(),
        get: vi.fn<ChromeApi['storage']['local']['get']>(async () => ({})),
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
