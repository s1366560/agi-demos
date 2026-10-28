import { useEffect, useState, type RefObject } from 'react';

export type McpAppAutomationMount = Readonly<{
  tabId: string;
  mountNonce: string;
  signal: AbortSignal;
}>;

export async function invokeMcpApp(
  mount: McpAppAutomationMount | null | undefined,
  operation: string,
  args: unknown = {},
  signal?: AbortSignal,
): Promise<unknown> {
  if (!mount) throw new Error('mcp_app_mount_unavailable');
  const signals = [...new Set(signal ? [mount.signal, signal] : [mount.signal])];
  const aborted = () => signals.some(item => item.aborted);
  const abortError = () => new DOMException('MCP App request cancelled', 'AbortError');
  if (aborted()) throw abortError();
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  if (!invoke) throw new Error('mcp_app_native_bridge_unavailable');
  const input = {
    tabId: mount.tabId,
    mountNonce: mount.mountNonce,
    operation,
    arguments: args,
  };
  if (operation !== 'tools/call') {
    const result = await invoke('mcp_app_operation', input);
    if (aborted()) throw abortError();
    return result;
  }
  let operationId: string | undefined;
  let cancellation: Promise<unknown> | undefined;
  const cancel = (): Promise<unknown> | undefined => {
    if (operationId) cancellation ??= invoke('mcp_app_operation_cancel', {
      tabId: mount.tabId, mountNonce: mount.mountNonce, operationId,
    }).catch(() => {});
    return cancellation;
  };
  const abort = () => { void cancel(); };
  for (const item of signals) item.addEventListener('abort', abort, { once: true });
  try {
    // Main chooses the operation identity before any tool call is dispatched.
    const prepared = await invoke<{ operationId: string }>('mcp_app_operation_prepare', input);
    if (typeof prepared?.operationId !== 'string') throw new Error('mcp_app_operation_unavailable');
    operationId = prepared.operationId;
    if (aborted()) throw abortError();
    const result = await invoke('mcp_app_operation', { ...input, operationId });
    if (aborted()) throw abortError();
    return result;
  } catch (error) {
    // An execute IPC failure can leave a prepared operation in main even when
    // no signal fired. Retire only this id; an already completed call is a no-op.
    await cancel();
    if (aborted()) throw abortError();
    throw error;
  } finally {
    for (const item of signals) item.removeEventListener('abort', abort);
  }
}

/** The host chooses an opaque name; an App cannot select another native frame. */
export function useMcpAppAutomation(
  tabId: string | null | undefined,
  container: RefObject<HTMLElement | null>,
): McpAppAutomationMount | null {
  const [mount, setMount] = useState<McpAppAutomationMount | null>(null);
  useEffect(() => {
    if (!tabId || typeof window === 'undefined') return;
    const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
    if (!tabId || !invoke || !container.current) return;
    const frameName = `mcpapp-${crypto.randomUUID()}`;
    const controller = new AbortController();
    setMount(Object.freeze({ tabId, mountNonce: frameName, signal: controller.signal }));
    let disposed = false;
    let registered = false;
    let busy = false;
    const unregister = () => invoke('mcp_app_frame_unregister', { tabId, frameName });
    const register = async () => {
      if (disposed || registered || busy) return;
      const frame = container.current?.querySelector('iframe');
      if (!frame) return;
      frame.name = frameName;
      busy = true;
      try {
        const result = await invoke<{ tabId: string; pending: boolean }>(
          'mcp_app_frame_register',
          { tabId, frameName },
        );
        registered = result?.tabId === tabId && result.pending === false;
        if (disposed) await unregister();
      } catch {
        // The sandbox creates its inner App frame after its ready handshake.
      } finally {
        busy = false;
      }
    };
    const observer = new MutationObserver(() => {
      void register();
    });
    observer.observe(container.current, { childList: true, subtree: true });
    const retry = window.setInterval(() => {
      void register();
    }, 250);
    void register();
    return () => {
      disposed = true;
      controller.abort();
      observer.disconnect();
      window.clearInterval(retry);
      void unregister().catch(() => {});
    };
  }, [container, tabId]);
  return mount?.tabId === tabId ? mount : null;
}
