import type { ChromeApi } from './chrome-api';
import { ErrorCodes, RpcError } from './protocol';

type RecordValue = Record<string, unknown>;
type Api = Record<string, Record<string, (...args: unknown[]) => Promise<unknown>>>;
const readable = new Set([
  'tabs.get', 'tabs.query', 'windows.get', 'windows.getAll',
  'tabGroups.get', 'tabGroups.query', 'bookmarks.get', 'bookmarks.getChildren',
  'bookmarks.getTree', 'bookmarks.getSubTree', 'bookmarks.search',
]);
const writable = new Set([
  'tabs.update', 'tabs.move', 'tabs.group', 'tabs.ungroup', 'tabs.remove',
  'windows.create', 'windows.update', 'tabGroups.update', 'tabGroups.move',
  'bookmarks.create', 'bookmarks.update', 'bookmarks.move', 'bookmarks.remove', 'bookmarks.removeTree',
]);
const updateFields: Record<string, readonly string[]> = {
  'tabs.update': ['active', 'pinned', 'muted', 'autoDiscardable'],
  'tabs.move': ['index', 'windowId'],
  'tabs.group': ['tabIds', 'groupId', 'createProperties'],
  'windows.create': ['tabId', 'type', 'incognito', 'focused', 'left', 'top', 'width', 'height', 'state'],
  'windows.update': ['focused', 'drawAttention', 'left', 'top', 'width', 'height', 'state'],
  'tabGroups.update': ['collapsed', 'color', 'title'],
  'tabGroups.move': ['index', 'windowId'],
  'bookmarks.create': ['parentId', 'index', 'title', 'url'],
  'bookmarks.update': ['title', 'url'],
  'bookmarks.move': ['parentId', 'index'],
};
const auditKey = 'memstack.browserManagement.audit.v1';

function record(value: unknown): RecordValue {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new RpcError(ErrorCodes.invalidParams, 'expected an object');
  return value as RecordValue;
}
function fields(value: unknown, allowed: readonly string[]): RecordValue {
  const object = record(value);
  if (Object.keys(object).some(key => !allowed.includes(key))) throw new RpcError(ErrorCodes.invalidParams, 'unsupported management field');
  return object;
}
function ids(value: unknown): number[] {
  const values = Array.isArray(value) ? value : [value];
  if (!values.length || values.some(id => !Number.isSafeInteger(id) || Number(id) <= 0)) throw new RpcError(ErrorCodes.invalidParams, 'expected positive integer ids');
  return values as number[];
}

/** Restricted organization APIs. Page scripting/navigation never use this path. */
export function createManagementHandler(chrome: ChromeApi) {
  const api = chrome as unknown as Api;
  let tail = Promise.resolve();
  async function invoke(namespace: string, method: string, args: unknown[]): Promise<unknown> {
    const object = api[namespace];
    const fn = object?.[method];
    if (typeof fn !== 'function') throw new RpcError(ErrorCodes.methodNotFound, `management method unavailable: ${namespace}.${method}`);
    return fn.apply(object, args);
  }
  async function sharedGroupGuard(namespace: string, method: string, args: unknown[]): Promise<void> {
    if (namespace !== 'tabs' && namespace !== 'tabGroups' && namespace !== 'windows') return;
    const tabs = await invoke('tabs', 'query', [{}]) as RecordValue[];
    const groups = await invoke('tabGroups', 'query', [{}]) as RecordValue[];
    let affected: RecordValue[] = [];
    if (namespace === 'tabs') {
      const tabIds = ids(method === 'group' ? record(args[0]).tabIds : args[0]);
      affected = tabIds.map(id => {
        const tab = tabs.find(tab => tab.id === id);
        if (!tab) throw new RpcError(ErrorCodes.invalidParams, 'tab is unavailable');
        return tab;
      });
      if (method === 'group') {
        const options = record(args[0]);
        if (new Set(affected.map(tab => tab.windowId)).size !== 1) throw new RpcError(ErrorCodes.invalidParams, 'group tabs within their current window');
        if (options.createProperties !== undefined && fields(options.createProperties, ['windowId']).windowId !== affected[0]?.windowId) throw new RpcError(ErrorCodes.invalidParams, 'group destination must match tab window');
        if (options.groupId !== undefined) {
          const group = groups.find(group => group.id === options.groupId);
          if (!group || group.windowId !== affected[0]?.windowId || group.shared === true) throw new RpcError(ErrorCodes.invalidParams, 'group unavailable or shared');
        }
      }
    } else if (namespace === 'tabGroups') {
      const group = groups.find(group => group.id === args[0]);
      if (!group || group.shared === true) throw new RpcError(ErrorCodes.invalidParams, 'group unavailable or shared');
      affected = tabs.filter(tab => tab.groupId === group.id);
    } else if (method === 'create' && record(args[0] ?? {}).tabId !== undefined) {
      const tab = tabs.find(tab => tab.id === record(args[0]).tabId);
      if (!tab || tab.pinned === true) throw new RpcError(ErrorCodes.invalidParams, 'window creation requires an unpinned existing tab');
      affected = [tab];
    }
    if (affected.some(tab => groups.some(group => group.id === tab.groupId && group.shared === true))) throw new RpcError(ErrorCodes.invalidParams, 'shared groups cannot be modified');
    if (method === 'move' || (namespace === 'windows' && method === 'create')) {
      const windows = new Set(affected.map(tab => tab.windowId));
      const destination = args[1] && record(args[1]).windowId;
      if (destination !== undefined) windows.add(destination);
      if (groups.some(group => group.shared === true && windows.has(group.windowId))) throw new RpcError(ErrorCodes.invalidParams, 'cannot move tabs in a window containing shared groups');
    }
  }
  async function execute(input: unknown): Promise<unknown> {
    const request = fields(input, ['namespace', 'method', 'args']);
    const namespace = String(request.namespace ?? '');
    const method = String(request.method ?? '');
    const args = request.args === undefined ? [] : request.args;
    if (!Array.isArray(args) || args.length > 3) throw new RpcError(ErrorCodes.invalidParams, 'invalid management arguments');
    const key = `${namespace}.${method}`;
    if (namespace === 'management' && method === 'getAuditTrail') return { changes: (await chrome.storage.local.get(auditKey))[auditKey] ?? [] };
    if (!readable.has(key) && !writable.has(key)) throw new RpcError(ErrorCodes.methodNotFound, 'management method is not permitted');
    if (readable.has(key)) return invoke(namespace, method, args);
    const allowed = updateFields[key];
    if (allowed) {
      const options = fields(args[key === 'tabs.group' || key === 'windows.create' || key === 'bookmarks.create' ? 0 : 1] ?? {}, allowed);
      if (namespace === 'windows') {
        if (options.type !== undefined && options.type !== 'normal') throw new RpcError(ErrorCodes.invalidParams, 'only normal windows are supported');
        if (options.incognito === true) throw new RpcError(ErrorCodes.invalidParams, 'incognito windows are unavailable');
        if (['left', 'top', 'width', 'height'].some(field => options[field] !== undefined) && options.state !== 'normal') throw new RpcError(ErrorCodes.invalidParams, 'window bounds require state normal');
      }
      if (namespace === 'bookmarks' && options.url !== undefined) {
        let url: URL;
        try { url = new URL(String(options.url)); } catch { throw new RpcError(ErrorCodes.invalidParams, 'invalid bookmark URL'); }
        if (!['http:', 'https:'].includes(url.protocol)) throw new RpcError(ErrorCodes.invalidParams, 'bookmark URL must use HTTP or HTTPS');
      }
    }
    await sharedGroupGuard(namespace, method, args);
    const before: RecordValue = {};
    if (namespace === 'bookmarks') before.bookmarks = await invoke('bookmarks', 'getTree', []);
    else {
      before.tabLayout = { tabs: await invoke('tabs', 'query', [{}]), groups: await invoke('tabGroups', 'query', [{}]) };
      if (namespace === 'windows') before.windows = await invoke('windows', 'getAll', [{}]);
    }
    const result = await invoke(namespace, method, args);
    const previous = (await chrome.storage.local.get(auditKey))[auditKey];
    const changes = [{ namespace, method, args, before, result, createdAt: Date.now() }, ...(Array.isArray(previous) ? previous : [])].slice(0, 100);
    await chrome.storage.local.set({ [auditKey]: changes });
    return result;
  }
  return (input: unknown): Promise<unknown> => {
    const task = tail.then(() => execute(input));
    tail = task.then(() => undefined, () => undefined);
    return task;
  };
}
