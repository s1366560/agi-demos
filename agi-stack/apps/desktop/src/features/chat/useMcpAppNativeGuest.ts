import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import type { McpAppAutomationMount } from './mcpAppAutomation';
import { computeMcpAppGuestBounds, intersectGuestRects } from './mcpAppGuestLayout';
import { mcpAppGuestDocumentKey } from './mcpAppGuestProtocol';
import type {
  McpAppGuestConfig,
  McpAppGuestHostEvent,
  McpAppGuestIdentity,
  McpAppGuestMethod,
  McpAppGuestRect,
} from './mcpAppGuestProtocol';

export type McpAppGuestHandlers = Record<
  McpAppGuestMethod,
  (params: unknown, extra: { signal: AbortSignal }) => unknown | Promise<unknown>
>;
type Binding = McpAppGuestIdentity & { key: string; controller: AbortController };
type Options = {
  enabled: boolean;
  key?: string;
  tabId?: string | null;
  keys: readonly string[];
  config: McpAppGuestConfig | null;
  container: RefObject<HTMLElement | null>;
  handlers: RefObject<McpAppGuestHandlers | null>;
  authority: unknown;
  onError(message: string): void;
};

export function hasMcpAppNativeGuest(): boolean {
  return typeof window !== 'undefined' && window.__MEMSTACK_DESKTOP__?.runtime === 'electron';
}

function visibleRect(element: Element): McpAppGuestRect | null {
  const style = getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  return style.display === 'none' ||
    style.visibility === 'hidden' ||
    !element.getClientRects().length ||
    rect.width <= 0 ||
    rect.height <= 0
    ? null
    : rect;
}

/** DOM roles/attributes are explicit host UI affordances, not content classification. */
export function readMcpAppGuestBounds(container: HTMLElement): McpAppGuestRect | null {
  if (container.closest('[inert], [aria-hidden="true"]')) return null;
  for (const dialog of document.querySelectorAll('[aria-modal="true"], dialog[open]')) {
    if (visibleRect(dialog)) return null;
  }
  let slot = visibleRect(container);
  if (!slot) return null;
  const style = getComputedStyle(container);
  const left = parseFloat(style.paddingLeft) || 0;
  const top = parseFloat(style.paddingTop) || 0;
  slot = {
    x: slot.x + left,
    y: slot.y + top,
    width: slot.width - left - (parseFloat(style.paddingRight) || 0),
    height: slot.height - top - (parseFloat(style.paddingBottom) || 0),
  };
  for (let parent = container.parentElement; parent; parent = parent.parentElement) {
    const parentStyle = getComputedStyle(parent);
    if (parentStyle.visibility === 'hidden' || parentStyle.display === 'none') return null;
    if (parentStyle.overflowX !== 'visible' || parentStyle.overflowY !== 'visible') {
      slot = intersectGuestRects(slot, parent.getBoundingClientRect());
      if (!slot) return null;
    }
  }
  const reserved: McpAppGuestRect[] = [];
  const blockers = document.querySelectorAll(
    '[data-native-view-occluder], [data-radix-popper-content-wrapper], [role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"], [role="tooltip"]',
  );
  for (const element of blockers) {
    if (element.contains(container) || container.contains(element)) continue;
    const rect = visibleRect(element);
    if (rect) reserved.push(rect);
  }
  return computeMcpAppGuestBounds(
    slot,
    { x: 0, y: 0, width: innerWidth, height: innerHeight },
    reserved,
  );
}

export function useMcpAppNativeGuest(options: Options): McpAppAutomationMount | null {
  const { enabled, key, tabId, container, handlers, authority } = options;
  const latest = useRef(options);
  latest.current = options;
  const [binding, setBinding] = useState<Binding | null>(null);
  const keysKey = JSON.stringify(options.keys);
  const configKey = JSON.stringify(options.config);
  const documentKey = mcpAppGuestDocumentKey(options.config);

  useEffect(() => {
    if (!enabled || !key || !latest.current.config) return;
    const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
    if (!invoke || !window.__MEMSTACK_DESKTOP__?.events?.onMcpAppGuest) {
      latest.current.onError('mcp_app_native_bridge_unavailable');
      return;
    }
    const frameName = `mcpapp-${crypto.randomUUID()}`;
    const controller = new AbortController();
    let disposed = false;
    void invoke<McpAppGuestIdentity>('mcp_app_guest_open', {
      key,
      frameName,
      ...(tabId ? { tabId } : {}),
      config: latest.current.config,
    })
      .then((identity) => {
        if (disposed) return;
        setBinding({ ...identity, key, controller });
      })
      .catch((error) => {
        if (!disposed)
          latest.current.onError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      disposed = true;
      controller.abort();
      // A release tombstone also rejects an open that is still queued.
      void invoke('mcp_app_guest_release', { frameName }).catch(() => {});
    };
  }, [enabled, key, tabId, authority, documentKey]);

  useEffect(() => {
    if (!enabled) return;
    void window.__MEMSTACK_DESKTOP__?.core
      ?.invoke?.('mcp_app_guest_prune', {
        keys: JSON.parse(keysKey),
      })
      .catch(() => {});
  }, [enabled, keysKey]);

  useEffect(() => {
    if (!binding || binding.controller.signal.aborted || binding.key !== key) return;
    const invoke = window.__MEMSTACK_DESKTOP__!.core!.invoke!;
    void invoke('mcp_app_guest_update', {
      ...identityOf(binding),
      config: JSON.parse(configKey),
    }).catch(() => {});
  }, [binding, key, configKey]);

  useEffect(() => {
    if (!binding || binding.controller.signal.aborted || binding.key !== key) return;
    const invoke = window.__MEMSTACK_DESKTOP__!.core!.invoke!;
    const identity = identityOf(binding);
    const pending = new Map<string, AbortController>();
    let disposed = false;
    let registered = false;
    let busy = false;
    const current = () => !disposed && !binding.controller.signal.aborted;
    const unsubscribe = window.__MEMSTACK_DESKTOP__!.events!.onMcpAppGuest!(
      (event: McpAppGuestHostEvent) => {
        if (
          !current() ||
          event.guestId !== identity.guestId ||
          event.frameName !== identity.frameName ||
          event.tabId !== identity.tabId
        )
          return;
        if (event.kind === 'retired') {
          latest.current.onError(event.reason);
          return;
        }
        if (event.kind === 'cancel') {
          pending.get(event.requestId)?.abort();
          pending.delete(event.requestId);
          return;
        }
        const handler = handlers.current?.[event.method];
        if (!handler || pending.has(event.requestId)) return;
        const controller = new AbortController();
        pending.set(event.requestId, controller);
        const respond = (result: Record<string, unknown>) => {
          if (!current() || controller.signal.aborted) return;
          return invoke('mcp_app_guest_respond', {
            ...identity,
            requestId: event.requestId,
            ...result,
          }).catch(() => {});
        };
        void Promise.resolve()
          .then(() => {
            if (!current() || controller.signal.aborted)
              throw new DOMException('MCP App request cancelled', 'AbortError');
            return handler(event.params, { signal: controller.signal });
          })
          .then(
            (result) => respond({ ok: true, result }),
            (error) =>
              respond({
                ok: false,
                error: error instanceof Error ? error.message : String(error),
              }),
          )
          .finally(() => pending.delete(event.requestId));
      },
    );
    const register = async () => {
      if (!current() || !identity.tabId || registered || busy) return;
      busy = true;
      try {
        const result = await invoke<{ pending: boolean }>('mcp_app_frame_register', identity);
        registered = result?.pending === false;
      } catch {
        // The SDK creates the inner document after its sandbox handshake.
      } finally {
        busy = false;
      }
    };
    void invoke('mcp_app_guest_start', identity)
      .then(register)
      .catch((error) => {
        if (current())
          latest.current.onError(error instanceof Error ? error.message : String(error));
      });
    const timer = window.setInterval(() => {
      void register();
    }, 250);
    return () => {
      disposed = true;
      unsubscribe();
      window.clearInterval(timer);
      for (const controller of pending.values()) controller.abort();
      pending.clear();
    };
  }, [binding, key, handlers]);

  useEffect(() => {
    if (!binding || binding.controller.signal.aborted || binding.key !== key || !container.current)
      return;
    const invoke = window.__MEMSTACK_DESKTOP__!.core!.invoke!;
    const identity = identityOf(binding);
    let animation = 0;
    let sequence = 0;
    let previous = '';
    let disposed = false;
    const update = () => {
      if (disposed || binding.controller.signal.aborted) return;
      const bounds = container.current ? readMcpAppGuestBounds(container.current) : null;
      const serialized = JSON.stringify(bounds);
      if (serialized !== previous) {
        previous = serialized;
        void invoke('mcp_app_guest_layout', { ...identity, sequence: ++sequence, bounds }).catch(
          () => {},
        );
      }
    };
    const tick = () => {
      update();
      if (!disposed) animation = requestAnimationFrame(tick);
    };
    // Inert/modal changes must detach the child view before the next host paint.
    const observer = new MutationObserver(update);
    observer.observe(document.body, { subtree: true, childList: true, attributes: true });
    tick();
    return () => {
      disposed = true;
      cancelAnimationFrame(animation);
      observer.disconnect();
      void invoke('mcp_app_guest_layout', {
        ...identity,
        sequence: ++sequence,
        bounds: null,
      }).catch(() => {});
    };
  }, [binding, key, container]);

  return useMemo(() => {
    if (
      !enabled ||
      !binding ||
      binding.key !== key ||
      binding.controller.signal.aborted ||
      !binding.tabId
    )
      return null;
    return {
      tabId: binding.tabId,
      mountNonce: binding.frameName,
      signal: binding.controller.signal,
    };
  }, [enabled, binding, key]);
}

function identityOf(binding: Binding): McpAppGuestIdentity {
  return {
    guestId: binding.guestId,
    frameName: binding.frameName,
    ...(binding.tabId ? { tabId: binding.tabId } : {}),
  };
}
