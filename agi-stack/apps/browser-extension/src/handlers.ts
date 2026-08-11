import type { ChromeApi } from './chrome-api';
import { createCursorManager } from './cursor/cursor-manager';
import { createMonitorInjector } from './monitor';
import {
  ErrorCodes,
  RpcError,
  errorResponse,
  isJsonRpcRequest,
  optionalCdpParams,
  requireAssignTabParams,
  requireCdpMethod,
  requireEnsureTabGroupParams,
  requireLeases,
  requireMoveMouseParams,
  requireTabId,
  successResponse,
  type JsonRpcResponse,
} from './protocol';
import { createTabGroupRegistry } from './tab-groups';

export const CDP_PROTOCOL_VERSION = '1.3';
export const CDP_COMMAND_TIMEOUT_MS = 10_000;
export const BRIDGE_PROTOCOL_VERSION = 1;
export const BRIDGE_PROTOCOL_MIN = BRIDGE_PROTOCOL_VERSION;
export const BRIDGE_PROTOCOL_MAX = BRIDGE_PROTOCOL_VERSION + 1;

const EXCLUDED_TAB_URL_PREFIXES = ['chrome://', 'chrome-extension://', 'edge://', 'about:'];

export interface Bridge {
  /** Tabs with a live debugger session, per the extension's own bookkeeping. */
  attachedTabs: Set<number>;
  /** Route one inbound JSON-RPC message; null means "not a request, ignore". */
  dispatch(message: unknown): Promise<JsonRpcResponse | null>;
  attachTab(tabId: number): Promise<void>;
  detachTab(tabId: number): Promise<void>;
  /** Kill-switch: detach every attached debugger. Never throws. */
  detachAll(): Promise<void>;
  clearAttachState(): void;
  /** Cursor kill-switch for native-port disconnect: hide + forget all cursors. */
  clearCursorStates(): void;
}

type Handler = (params: unknown) => unknown | Promise<unknown>;

export function createBridge(chrome: ChromeApi): Bridge {
  const attachedTabs = new Set<number>();
  const tabGroupRegistry = createTabGroupRegistry(chrome);
  const cursorManager = createCursorManager(chrome);
  const monitorInjector = createMonitorInjector(chrome);

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    cursorManager.handleMessage(message, sender, sendResponse);
  });

  async function attachTab(tabId: number): Promise<void> {
    if (attachedTabs.has(tabId)) return; // idempotent
    await chrome.debugger.attach({ tabId }, CDP_PROTOCOL_VERSION);
    attachedTabs.add(tabId);
  }

  async function detachTab(tabId: number): Promise<void> {
    if (!attachedTabs.has(tabId)) return;
    attachedTabs.delete(tabId);
    await chrome.debugger.detach({ tabId });
  }

  async function detachAll(): Promise<void> {
    const tabIds = [...attachedTabs];
    attachedTabs.clear();
    await Promise.all(
      tabIds.map((tabId) =>
        chrome.debugger.detach({ tabId }).catch(() => {
          /* tab may already be gone */
        }),
      ),
    );
  }

  function clearAttachState(): void {
    attachedTabs.clear();
  }

  function clearCursorStates(): void {
    cursorManager.clearAll();
  }

  async function executeCdp(params: unknown): Promise<{ result: unknown }> {
    const tabId = requireTabId(params);
    const method = requireCdpMethod(params);
    const commandParams = optionalCdpParams(params);
    await attachTab(tabId); // implicit attach on first use

    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const result = await Promise.race([
        chrome.debugger.sendCommand({ tabId }, method, commandParams),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(() => {
            reject(
              new RpcError(
                ErrorCodes.cdpTimeout,
                `cdp command timeout after ${CDP_COMMAND_TIMEOUT_MS}ms: ${method}`,
              ),
            );
          }, CDP_COMMAND_TIMEOUT_MS);
        }),
      ]);
      return { result };
    } catch (error) {
      if (error instanceof RpcError && error.code === ErrorCodes.cdpTimeout) {
        await detachTab(tabId).catch(() => {
          /* best effort */
        });
      }
      throw error;
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }

  async function getTabs(): Promise<{ tabs: unknown[] }> {
    const tabs = await chrome.tabs.query({});
    const out = [];
    for (const tab of tabs) {
      if (typeof tab.id !== 'number') continue;
      const url = typeof tab.url === 'string' ? tab.url : '';
      if (EXCLUDED_TAB_URL_PREFIXES.some((prefix) => url.startsWith(prefix))) continue;
      out.push({
        tabId: tab.id,
        windowId: typeof tab.windowId === 'number' ? tab.windowId : -1,
        title: typeof tab.title === 'string' ? tab.title : '',
        url,
        active: tab.active === true,
      });
    }
    return { tabs: out };
  }

  async function createTab(params: unknown): Promise<{ tabId: number }> {
    let url: string | undefined;
    if (params !== undefined) {
      if (typeof params !== 'object' || params === null || Array.isArray(params)) {
        throw new RpcError(ErrorCodes.invalidParams, 'params must be an object');
      }
      const candidate = (params as Record<string, unknown>).url;
      if (candidate !== undefined && typeof candidate !== 'string') {
        throw new RpcError(ErrorCodes.invalidParams, 'url must be a string');
      }
      url = candidate;
    }
    const tab = await chrome.tabs.create({ url: url ?? 'about:blank', active: false });
    if (typeof tab.id !== 'number') {
      throw new RpcError(ErrorCodes.internalError, 'chrome.tabs.create returned no tab id');
    }
    monitorInjector.ensureMonitorInjected(tab.id);
    return { tabId: tab.id };
  }

  /** Shared close path: debugger off first, then remove the tab. */
  async function closeTabById(tabId: number): Promise<void> {
    if (attachedTabs.has(tabId)) {
      await detachTab(tabId).catch(() => {
        /* best effort: still close the tab */
      });
    }
    await chrome.tabs.remove(tabId);
    cursorManager.clearTab(tabId);
  }

  async function ensureTabGroup(params: unknown): Promise<{ groupId: number }> {
    const { key, title, color } = requireEnsureTabGroupParams(params);
    const groupId = await tabGroupRegistry.ensureTabGroup(key, title, color);
    return { groupId };
  }

  async function assignTab(params: unknown): Promise<Record<string, never>> {
    const { tabId, groupId } = requireAssignTabParams(params);
    try {
      await chrome.tabs.group({ tabIds: tabId, groupId });
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new RpcError(
        ErrorCodes.invalidParams,
        `cannot assign tab ${tabId} to group ${groupId}: ${detail}`,
      );
    }
    monitorInjector.ensureMonitorInjected(tabId);
    return {};
  }

  async function ungroupTab(params: unknown): Promise<Record<string, never>> {
    await chrome.tabs.ungroup(requireTabId(params));
    return {};
  }

  async function closeTab(params: unknown): Promise<Record<string, never>> {
    await closeTabById(requireTabId(params));
    return {};
  }

  async function focusTab(params: unknown): Promise<Record<string, never>> {
    await chrome.tabs.update(requireTabId(params), { active: true });
    return {};
  }

  async function moveMouse(params: unknown): Promise<Record<string, never>> {
    await cursorManager.moveMouse(requireMoveMouseParams(params));
    return {};
  }

  /**
   * Turn cleanup (design §2.6): unmarked agent tabs close, deliverables are
   * ungrouped but kept, handoffs stay in the group, user tabs are untouched.
   * Per-tab failures are tolerated; only successes are counted.
   */
  async function turnEnded(params: unknown): Promise<{ closed: number; ungrouped: number }> {
    const leases = requireLeases(params);
    cursorManager.hideTabs(leases.map((lease) => lease.tabId));
    let closed = 0;
    let ungrouped = 0;
    for (const lease of leases) {
      if (lease.origin === 'user' || lease.mark === 'handoff') continue;
      if (lease.mark === 'deliverable') {
        try {
          await chrome.tabs.ungroup(lease.tabId);
          ungrouped++;
        } catch {
          /* tolerate: tab may already be gone */
        }
        continue;
      }
      try {
        await closeTabById(lease.tabId);
        closed++;
      } catch {
        /* tolerate: tab may already be gone */
      }
    }
    return { closed, ungrouped };
  }

  const handlers: Record<string, Handler> = {
    hello: () => ({
      protocolVersion: BRIDGE_PROTOCOL_VERSION,
      protocolMin: BRIDGE_PROTOCOL_MIN,
      protocolMax: BRIDGE_PROTOCOL_MAX,
      backend: 'chrome-extension',
      extensionId: chrome.runtime.id,
      extensionVersion: chrome.runtime.getManifest().version,
      capabilities: ['cdp', 'tabs', 'events'],
    }),
    ping: () => ({}),
    attach: async (params) => {
      await attachTab(requireTabId(params));
      return {};
    },
    detach: async (params) => {
      await detachTab(requireTabId(params));
      return {};
    },
    executeCdp,
    getTabs,
    createTab,
    ensureTabGroup,
    assignTab,
    ungroupTab,
    closeTab,
    focusTab,
    moveMouse,
    turnEnded,
  };

  async function dispatch(message: unknown): Promise<JsonRpcResponse | null> {
    if (!isJsonRpcRequest(message)) return null; // garbage on the wire: ignore
    const handler = handlers[message.method];
    if (!handler) {
      return errorResponse(
        message.id,
        ErrorCodes.methodNotFound,
        `unknown method: ${message.method}`,
      );
    }
    try {
      const result = await handler(message.params);
      return successResponse(message.id, result ?? {});
    } catch (error) {
      if (error instanceof RpcError) {
        return errorResponse(message.id, error.code, error.message);
      }
      const message_ = error instanceof Error ? error.message : String(error);
      return errorResponse(message.id, ErrorCodes.internalError, message_);
    }
  }

  return {
    attachedTabs,
    dispatch,
    attachTab,
    detachTab,
    detachAll,
    clearAttachState,
    clearCursorStates,
  };
}
