/**
 * Minimal structural view of the chrome.* APIs this extension uses.
 * Both the real `chrome` global and the hand-rolled test mock satisfy this.
 */

export interface ChromeEvent<T extends unknown[]> {
  addListener(callback: (...args: T) => void): void;
}

export interface NativePort {
  postMessage(message: unknown): void;
  onMessage: ChromeEvent<[unknown]>;
  onDisconnect: ChromeEvent<[]>;
}

export interface DebuggerTarget {
  tabId: number;
}

export interface Debuggee {
  tabId?: number;
}

export interface TabLike {
  id?: number;
  windowId?: number;
  title?: string;
  url?: string;
  active?: boolean;
}

export interface WindowLike {
  id?: number;
  type?: string;
  state?: string;
}

export interface TabGroupLike {
  id?: number;
  title?: string;
  color?: string;
}

export interface MessageSenderLike {
  tab?: { id?: number };
}

export interface ScriptInjection {
  target: { tabId: number; allFrames?: boolean };
  files: string[];
  world?: string;
}

export interface AlarmLike {
  name: string;
}

export interface ChromeApi {
  runtime: {
    id: string;
    lastError?: { message?: string } | null;
    connectNative(name: string): NativePort;
    sendMessage(message: unknown): Promise<unknown>;
    onStartup: ChromeEvent<[]>;
    onInstalled: ChromeEvent<[]>;
    onMessage: ChromeEvent<[unknown, MessageSenderLike, (response?: unknown) => void]>;
  };
  debugger: {
    attach(target: DebuggerTarget, protocolVersion: string): Promise<void>;
    detach(target: DebuggerTarget): Promise<void>;
    sendCommand(target: DebuggerTarget, method: string, params?: object): Promise<unknown>;
    onEvent: ChromeEvent<[Debuggee, string, unknown]>;
    onDetach: ChromeEvent<[Debuggee, string]>;
  };
  tabs: {
    query(queryInfo: Record<string, never>): Promise<TabLike[]>;
    create(createProperties: { url: string; active: boolean }): Promise<TabLike>;
    get(tabId: number): Promise<TabLike>;
    update(tabId: number, updateProperties: { active?: boolean }): Promise<unknown>;
    remove(tabId: number): Promise<void>;
    group(options: { tabIds: number | number[]; groupId?: number }): Promise<number>;
    ungroup(tabIds: number | number[]): Promise<void>;
    sendMessage(tabId: number, message: unknown): Promise<unknown>;
  };
  windows: {
    get(windowId: number): Promise<WindowLike>;
  };
  tabGroups: {
    get(groupId: number): Promise<TabGroupLike>;
    update(groupId: number, updateProperties: { title?: string; color?: string }): Promise<unknown>;
  };
  scripting: {
    executeScript(injection: ScriptInjection): Promise<unknown[]>;
  };
  alarms: {
    create(
      name: string,
      alarmInfo: { delayInMinutes?: number; periodInMinutes?: number },
    ): Promise<void> | void;
    clear(name: string): Promise<boolean> | void;
    onAlarm: ChromeEvent<[AlarmLike]>;
  };
  storage: {
    local: {
      set(items: Record<string, unknown>): Promise<void> | void;
      get(keys: string): Promise<Record<string, unknown>>;
    };
    /** SW-lifetime session store (side panel session cache). */
    session?: {
      set(items: Record<string, unknown>): Promise<void> | void;
      get(keys: string): Promise<Record<string, unknown>>;
      remove(keys: string): Promise<void> | void;
    };
    onChanged: ChromeEvent<[Record<string, { newValue?: unknown }>, string]>;
  };
  /** Present in Chrome 114+; the SW enables openPanelOnActionClick. */
  sidePanel?: {
    setPanelBehavior(options: { openPanelOnActionClick: boolean }): Promise<void>;
  };
}
