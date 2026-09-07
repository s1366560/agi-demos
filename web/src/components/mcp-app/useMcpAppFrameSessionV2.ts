import { useCallback, useLayoutEffect, useRef } from 'react';
import type { RefObject } from 'react';

import type { MCPAppCapabilities, MCPAppDisplayMode } from '@/types/mcpApp';

import type { WebOperationContextV2 } from '@/plugins/webOperationAdmissionV2';

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;
const retired = () => new DOMException('MCP app session retired', 'AbortError');
function targetOrigin(frame: HTMLIFrameElement) {
  try {
    const url = new URL(frame.src);
    return ['http:', 'https:'].includes(url.protocol) ? url.origin : '*';
  } catch {
    return '*';
  }
}
export function useMcpAppFrameSessionV2(
  operation: WebOperationContextV2 | null,
  container: RefObject<HTMLDivElement | null>,
  setCapabilities: (value: MCPAppCapabilities | null) => void,
  setDisplayMode: (value: MCPAppDisplayMode) => void
) {
  const serial = useRef(0);
  const pending = useRef(
    new Map<
      number,
      {
        source: Window;
        resolve: (value: unknown) => void;
        reject: (error: Error) => void;
        timer: ReturnType<typeof setTimeout>;
      }
    >()
  );
  const clear = useCallback(() => {
    for (const item of pending.current.values()) {
      clearTimeout(item.timer);
      item.reject(retired());
    }
    pending.current.clear();
  }, []);
  useLayoutEffect(() => {
    if (!operation) return;
    const receive = (event: MessageEvent<unknown>) => {
      try {
        operation.check();
      } catch {
        return;
      }
      const frame = container.current?.querySelector('iframe');
      if (!frame?.contentWindow || event.source !== frame.contentWindow) return;
      const expected = targetOrigin(frame);
      if (expected !== '*' && event.origin !== expected) return;
      if (!record(event.data) || event.data.jsonrpc !== '2.0') return;
      const data = event.data;
      if (
        typeof data.id === 'number' &&
        !('method' in data) &&
        ('result' in data || 'error' in data)
      ) {
        const item = pending.current.get(data.id);
        if (!item || item.source !== event.source) return;
        pending.current.delete(data.id);
        clearTimeout(item.timer);
        if ('error' in data)
          item.reject(
            new Error(
              record(data.error) && typeof data.error.message === 'string'
                ? data.error.message
                : 'RPC error'
            )
          );
        else item.resolve(data.result);
        return;
      }
      const params = record(data.params) ? data.params : undefined;
      if (
        data.method === 'ui/request-display-mode' &&
        (params?.mode === 'inline' || params?.mode === 'fullscreen' || params?.mode === 'pip')
      ) {
        setDisplayMode(params.mode);
        operation.check();
        frame.contentWindow.postMessage(
          { jsonrpc: '2.0', id: data.id, result: { mode: params.mode } },
          expected
        );
        return;
      }
      if (
        (data.method === 'ui/initialize' || data.method === 'ui/notifications/initialized') &&
        record(params?.appCapabilities)
      )
        setCapabilities(params.appCapabilities as MCPAppCapabilities);
    };
    const observer = new MutationObserver(() => {
      const current = container.current?.querySelector('iframe')?.contentWindow;
      for (const [id, item] of pending.current) {
        if (item.source !== current) {
          clearTimeout(item.timer);
          pending.current.delete(id);
          item.reject(retired());
        }
      }
    });
    if (container.current) observer.observe(container.current, { childList: true, subtree: true });
    const stop = () => {
      clear();
      observer.disconnect();
      window.removeEventListener('message', receive);
    };
    operation.signal.addEventListener('abort', stop, { once: true });
    window.addEventListener('message', receive);
    return () => {
      stop();
      operation.signal.removeEventListener('abort', stop);
    };
  }, [operation, container, clear, setCapabilities, setDisplayMode]);
  const sendRpc = useCallback(
    async (method: string, params?: Record<string, unknown>): Promise<unknown> => {
      if (!operation) throw retired();
      operation.check();
      const capturedParams = params === undefined ? undefined : structuredClone(params);
      return operation.runChild(async (child) => {
        child.check();
        const frame = container.current?.querySelector('iframe');
        const source = frame?.contentWindow;
        if (!source || !frame) throw new Error('No iframe found for app communication');
        const id = ++serial.current;
        const result = await new Promise<unknown>((resolve, reject) => {
          const timer = setTimeout(() => {
            pending.current.delete(id);
            reject(new Error('MCP app RPC timed out'));
          }, 30000);
          pending.current.set(id, { source, resolve, reject, timer });
          try {
            source.postMessage(
              {
                jsonrpc: '2.0',
                id,
                method,
                ...(capturedParams ? { params: capturedParams } : {}),
              },
              targetOrigin(frame)
            );
          } catch (error) {
            clearTimeout(timer);
            pending.current.delete(id);
            reject(error instanceof Error ? error : new Error('MCP app RPC failed'));
          }
        });
        child.check();
        return result;
      });
    },
    [operation, container]
  );
  const notify = useCallback(
    (method: string, params?: Record<string, unknown>) => {
      if (!operation) return;
      try {
        operation.check();
      } catch {
        return;
      }
      const frame = container.current?.querySelector('iframe');
      if (!frame?.contentWindow) return;
      frame.contentWindow.postMessage(
        { jsonrpc: '2.0', method, ...(params ? { params: structuredClone(params) } : {}) },
        targetOrigin(frame)
      );
    },
    [operation, container]
  );
  return { sendRpc, notify, clear };
}
