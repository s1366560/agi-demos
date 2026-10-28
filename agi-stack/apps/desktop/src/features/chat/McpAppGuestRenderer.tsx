import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AppRenderer, type AppRendererProps, type SandboxConfig } from '@mcp-ui/client';
import type {
  McpAppGuestActivation,
  McpAppGuestBridge,
  McpAppGuestConfig,
  McpAppGuestMethod,
} from './mcpAppGuestProtocol';
import './McpAppGuestRenderer.css';

declare global {
  interface Window {
    __MEMSTACK_MCP_APP_GUEST__?: McpAppGuestBridge;
  }
}

function cancelled(): DOMException {
  return new DOMException('MCP App request cancelled', 'AbortError');
}

function GuestRenderer({ bridge }: { bridge: McpAppGuestBridge }) {
  const [config, setConfig] = useState<McpAppGuestConfig | null>(null);
  const current = useRef<McpAppGuestActivation | null>(null);
  const initialized = useRef(false);
  const renameFrame = () => {
    const frame = document.querySelector('iframe');
    if (frame && current.current) frame.name = current.current.frameName;
  };
  useEffect(() => {
    let disposed = false;
    const activate = (value: McpAppGuestActivation) => {
      if (disposed) return;
      current.current = value;
      if (initialized.current) void bridge.ready(value).catch(() => {});
      // A fresh mount nonce must not resend HTML or recreate the SDK/App document.
      setConfig((previous) =>
        JSON.stringify(previous) === JSON.stringify(value.config) ? previous : value.config,
      );
      renameFrame();
    };
    const unsubscribe = bridge.subscribe((event) => {
      if (event.kind === 'activate') activate(event.value);
      else if (current.current?.frameName === event.frameName) current.current = null;
    });
    const onMessage = (event: MessageEvent) => {
      const frame = document.querySelector('iframe');
      if (
        event.source !== frame?.contentWindow ||
        event.data?.jsonrpc !== '2.0' ||
        event.data?.method !== 'ui/notifications/initialized' ||
        !current.current
      )
        return;
      initialized.current = true;
      void bridge.ready(current.current).catch(() => {});
    };
    window.addEventListener('message', onMessage);
    const observer = new MutationObserver(renameFrame);
    observer.observe(document.body, { childList: true, subtree: true });
    void bridge
      .initialize()
      .then(activate)
      .catch(() => {});
    return () => {
      disposed = true;
      current.current = null;
      observer.disconnect();
      unsubscribe();
      window.removeEventListener('message', onMessage);
    };
  }, [bridge]);

  const handlers = useMemo(() => {
    const request = async (
      method: McpAppGuestMethod,
      params: unknown,
      extra?: { signal?: AbortSignal },
    ) => {
      const identity = current.current;
      if (!identity || extra?.signal?.aborted) throw cancelled();
      const { guestId, frameName, tabId } = identity;
      const input = {
        guestId,
        frameName,
        ...(tabId ? { tabId } : {}),
        requestId: crypto.randomUUID(),
      };
      const abort = () => {
        void bridge.cancel(input).catch(() => {});
      };
      extra?.signal?.addEventListener('abort', abort, { once: true });
      try {
        const result = await bridge.request({ ...input, kind: 'request', method, params });
        if (current.current?.frameName !== frameName || extra?.signal?.aborted) throw cancelled();
        return result;
      } finally {
        extra?.signal?.removeEventListener('abort', abort);
      }
    };
    return {
      onCallTool: (params, extra) => request('callTool', params, extra),
      onReadResource: (params, extra) => request('readResource', params, extra),
      onListResources: (params, extra) => request('listResources', params, extra),
      onListResourceTemplates: (params, extra) => request('listResourceTemplates', params, extra),
      onListPrompts: (params, extra) => request('listPrompts', params, extra),
      onFallbackRequest: (params, extra) => request('fallbackRequest', params, extra),
      onMessage: (params, extra) => request('message', params, extra),
      onOpenLink: (params, extra) => request('openLink', params, extra),
      onSizeChanged: (params) => {
        void request('sizeChanged', params).catch(() => {});
      },
      onError: (error) => {
        void request('error', { message: error.message }).catch(() => {});
      },
    } as Pick<
      AppRendererProps,
      | 'onCallTool'
      | 'onReadResource'
      | 'onListResources'
      | 'onListResourceTemplates'
      | 'onListPrompts'
      | 'onFallbackRequest'
      | 'onMessage'
      | 'onOpenLink'
      | 'onSizeChanged'
      | 'onError'
    >;
  }, [bridge]);
  const sandboxKey = JSON.stringify(config?.sandbox);
  const sandbox = useMemo<SandboxConfig | null>(() => {
    if (!config) return null;
    return {
      ...config.sandbox,
      url: new URL(config.sandbox.url),
      csp: config.sandbox.csp as SandboxConfig['csp'],
    };
  }, [sandboxKey]);
  if (!config || !sandbox) return null;
  return (
    <AppRenderer
      {...config}
      sandbox={sandbox}
      toolResult={config.toolResult as AppRendererProps['toolResult']}
      {...handlers}
    />
  );
}

const bridge = window.__MEMSTACK_MCP_APP_GUEST__;
const container = document.getElementById('root');
if (bridge && container) createRoot(container).render(<GuestRenderer bridge={bridge} />);
