declare global {
  var __memstackNativeSetImmediate: typeof setImmediate;
  var __memstackPendingReactMacrotasks: Set<ReturnType<typeof setImmediate>>;
  var __memstackReactMacrotasksOpen: boolean;
  var __memstackClearReactMacrotask: (handle: ReturnType<typeof setImmediate>) => void;
}

// Loaded before setup.ts. React's scheduler captures setImmediate when
// @testing-library/react is imported, so this patch has to exist first.
const nativeSetImmediate = globalThis.setImmediate.bind(globalThis);
const nativeClearImmediate = globalThis.clearImmediate.bind(globalThis);
const pendingReactMacrotasks = new Set<ReturnType<typeof setImmediate>>();

globalThis.__memstackNativeSetImmediate = nativeSetImmediate;
globalThis.__memstackPendingReactMacrotasks = pendingReactMacrotasks;
globalThis.__memstackReactMacrotasksOpen = true;

globalThis.setImmediate = ((callback: (...args: unknown[]) => void, ...args: unknown[]) => {
  if (!globalThis.__memstackReactMacrotasksOpen) {
    return nativeSetImmediate(() => undefined);
  }
  let handle!: ReturnType<typeof setImmediate>;
  handle = nativeSetImmediate((...inner: unknown[]) => {
    pendingReactMacrotasks.delete(handle);
    if (!globalThis.__memstackReactMacrotasksOpen) return;
    callback(...inner);
  }, ...args);
  pendingReactMacrotasks.add(handle);
  return handle;
}) as typeof setImmediate;

globalThis.__memstackClearReactMacrotask = (handle: ReturnType<typeof setImmediate>) => {
  nativeClearImmediate(handle);
};

export {};
