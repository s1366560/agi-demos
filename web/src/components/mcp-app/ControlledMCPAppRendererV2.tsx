import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef } from 'react';

import { AppBridge, PostMessageTransport } from '@mcp-ui/client';

import {
  WebOperationCleanupErrorV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';

import type { AppRendererHandle, AppRendererProps } from '@mcp-ui/client';
import type { RequestOptions } from '@modelcontextprotocol/sdk/shared/protocol.js';

type Props = AppRendererProps & {
  operation: WebOperationContextV2;
  onInitialized?: (() => void) | undefined;
};
const cancelled = () => new DOMException('MCP frame retired', 'AbortError');

/** Public official bridge APIs with an explicitly owned frame, listener and RPC lifetime. */
const ControlledMCPAppRendererV2 = forwardRef<AppRendererHandle, Props>((props, ref) => {
  const container = useRef<HTMLDivElement>(null);
  const latest = useRef(props);
  const view = useRef<{
    bridge: AppBridge;
    check(): void;
    track<T>(promise: Promise<T>): Promise<T>;
    initialized: boolean;
  } | null>(null);
  useLayoutEffect(() => {
    latest.current = props;
  });
  useImperativeHandle(
    ref,
    () => ({
      sendToolListChanged() {
        const current = view.current;
        current?.check();
        return current?.bridge.sendToolListChanged();
      },
      sendResourceListChanged() {
        const current = view.current;
        current?.check();
        return current?.bridge.sendResourceListChanged();
      },
      sendPromptListChanged() {
        const current = view.current;
        current?.check();
        return current?.bridge.sendPromptListChanged();
      },
      teardownResource() {
        const current = view.current;
        current?.check();
        return current?.bridge.teardownResource({});
      },
    }),
    []
  );

  useLayoutEffect(() => {
    const target = container.current;
    if (!target) return;
    const captured = latest.current;
    const stop = new AbortController();
    let stopReady!: () => void;
    const stopped = new Promise<void>((resolve) => {
      stopReady = resolve;
    });
    let retireResources: () => void = () => undefined;
    const retire = () => {
      if (!stop.signal.aborted) stop.abort(cancelled());
      retireResources();
      stopReady();
    };
    const task = captured.operation.runChild(async (child) => {
      const pending = new Set<Promise<unknown>>();
      const failures: unknown[] = [];
      let bridge: AppBridge | undefined;
      let transport: PostMessageTransport | undefined;
      let frame: HTMLIFrameElement | undefined;
      let closeTask: Promise<void> | undefined;
      let removeReady: () => void = () => undefined;
      let removeOriginGuard: () => void = () => undefined;
      const check = () => {
        child.check();
        stop.signal.throwIfAborted();
      };
      const track = <T,>(promise: Promise<T>): Promise<T> => {
        pending.add(promise);
        void promise.catch(() => undefined);
        void promise
          .finally(() => {
            pending.delete(promise);
          })
          .catch(() => undefined);
        return promise;
      };
      retireResources = () => {
        removeReady();
        removeOriginGuard();
        if (view.current?.bridge === bridge) view.current = null;
        if (!closeTask) {
          // Abort request signals before Protocol._onclose so SDK request timeout maps drain.
          closeTask = (async () => {
            try {
              await bridge?.close();
            } catch (error) {
              failures.push(error);
            }
            try {
              await transport?.close();
            } catch (error) {
              failures.push(error);
            }
          })();
        }
        frame?.remove();
      };
      child.signal.addEventListener('abort', retire, { once: true });
      let primary: unknown;
      let failed = false;
      try {
        check();
        const capabilities = captured.client?.getServerCapabilities();
        bridge = new AppBridge(
          captured.client ?? null,
          { name: 'MemStack MCP host', version: '1.0.0' },
          {
            openLinks: {},
            ...(capabilities?.tools
              ? {
                  serverTools:
                    capabilities.tools.listChanged === undefined
                      ? {}
                      : { listChanged: capabilities.tools.listChanged },
                }
              : {}),
            ...(capabilities?.resources
              ? {
                  serverResources:
                    capabilities.resources.listChanged === undefined
                      ? {}
                      : { listChanged: capabilities.resources.listChanged },
                }
              : {}),
          },
          { hostContext: captured.hostContext ?? {} }
        );
        const ownedBridge = bridge;
        const setHandler = ownedBridge.setRequestHandler.bind(ownedBridge);
        ownedBridge.setRequestHandler = ((...args: Parameters<typeof setHandler>) => {
          const callback = args[1];
          setHandler(args[0], ((...input: Parameters<typeof callback>) =>
            track(
              Promise.resolve().then(() => {
                check();
                return callback(...input);
              })
            )) as typeof callback);
        }) as typeof ownedBridge.setRequestHandler;
        const request = ownedBridge.request.bind(ownedBridge);
        ownedBridge.request = ((...args: Parameters<typeof request>) => {
          check();
          const options = args[2] as RequestOptions | undefined;
          return track(
            request(args[0], args[1], {
              ...options,
              signal: options?.signal
                ? AbortSignal.any([options.signal, stop.signal])
                : stop.signal,
            })
          );
        }) as typeof ownedBridge.request;
        const handler =
          <P, E extends { signal: AbortSignal }, R>(
            callback: (params: P, extra: E) => Promise<R>
          ) =>
          (params: P, extra: E): Promise<R> =>
            track(
              Promise.resolve().then(async () => {
                check();
                const result = await callback(params, {
                  ...extra,
                  signal: AbortSignal.any([extra.signal, stop.signal]),
                });
                check();
                return result;
              })
            );
        if (captured.onMessage) ownedBridge.onmessage = handler(captured.onMessage);
        if (captured.onOpenLink) ownedBridge.onopenlink = handler(captured.onOpenLink);
        if (captured.onCallTool) ownedBridge.oncalltool = handler(captured.onCallTool);
        if (captured.onReadResource) ownedBridge.onreadresource = handler(captured.onReadResource);
        if (captured.onListResources)
          ownedBridge.onlistresources = handler(captured.onListResources);
        if (captured.onListResourceTemplates)
          ownedBridge.onlistresourcetemplates = handler(captured.onListResourceTemplates);
        if (captured.onListPrompts) ownedBridge.onlistprompts = handler(captured.onListPrompts);
        ownedBridge.onloggingmessage = (params) => {
          check();
          latest.current.onLoggingMessage?.(params);
        };
        ownedBridge.onsizechange = (params) => {
          check();
          latest.current.onSizeChanged?.(params);
          check();
          if (frame && params.width !== undefined) frame.style.width = `${params.width}px`;
          if (frame && params.height !== undefined) frame.style.height = `${params.height}px`;
        };
        ownedBridge.oninitialized = () => {
          check();
          const current = view.current;
          if (current?.bridge === ownedBridge) current.initialized = true;
          const next = latest.current;
          if (next.hostContext) ownedBridge.setHostContext(next.hostContext);
          next.onInitialized?.();
          check();
          if (next.toolInput) void track(ownedBridge.sendToolInput({ arguments: next.toolInput }));
          if (next.toolResult) void track(ownedBridge.sendToolResult(next.toolResult));
          if (next.toolInputPartial)
            void track(ownedBridge.sendToolInputPartial(next.toolInputPartial));
          if (next.toolCancelled) void track(ownedBridge.sendToolCancelled({}));
        };
        let html = captured.html;
        if (html === undefined) {
          let uri = captured.toolResourceUri;
          if (!uri && captured.client) {
            let cursor: string | undefined;
            do {
              const page = await track(
                captured.client.listTools(cursor ? { cursor } : {}, { signal: stop.signal })
              );
              check();
              const tool = page.tools.find((item) => item.name === captured.toolName);
              const meta = tool?._meta;
              const nested = meta?.ui;
              const value =
                nested && typeof nested === 'object' && 'resourceUri' in nested
                  ? nested.resourceUri
                  : meta?.['ui/resourceUri'];
              if (typeof value === 'string' && value.startsWith('ui://')) uri = value;
              cursor = page.nextCursor;
            } while (!uri && cursor);
          }
          if (!uri) throw new Error('MCP UI resource URI is required');
          const result = captured.client
            ? await track(captured.client.readResource({ uri }, { signal: stop.signal }))
            : captured.onReadResource
              ? await track(
                  captured.onReadResource({ uri }, { signal: stop.signal } as Parameters<
                    NonNullable<Props['onReadResource']>
                  >[1])
                )
              : undefined;
          check();
          if (result?.contents.length !== 1)
            throw new Error('MCP UI resource must contain one HTML entry');
          const content = result.contents[0]!;
          if (content.mimeType !== 'text/html;profile=mcp-app')
            throw new Error('MCP UI resource MIME type is invalid');
          if ('text' in content && typeof content.text === 'string') html = content.text;
          else if ('blob' in content && typeof content.blob === 'string') html = atob(content.blob);
          else throw new Error('MCP UI resource content is invalid');
        }
        check();
        frame = document.createElement('iframe');
        frame.title = captured.toolName;
        frame.setAttribute(
          'sandbox',
          captured.sandbox.permissions ?? 'allow-scripts allow-same-origin allow-forms'
        );
        Object.assign(frame.style, {
          width: '100%',
          height: '600px',
          border: 'none',
          backgroundColor: 'transparent',
        });
        const url = new URL(captured.sandbox.url);
        if (captured.sandbox.csp) url.searchParams.set('csp', JSON.stringify(captured.sandbox.csp));
        const ready = track(
          new Promise<void>((resolve, reject) => {
            const timeout = setTimeout(() => {
              removeReady();
              reject(new Error('MCP sandbox readiness timed out'));
            }, 10000);
            const message = (event: MessageEvent) => {
              if (
                event.source !== frame?.contentWindow ||
                event.origin !== url.origin ||
                event.data?.method !== 'ui/notifications/sandbox-proxy-ready'
              )
                return;
              removeReady();
              resolve();
            };
            const error = () => {
              removeReady();
              reject(new Error('MCP sandbox failed to load'));
            };
            const abort = () => {
              removeReady();
              reject(cancelled());
            };
            removeReady = () => {
              clearTimeout(timeout);
              window.removeEventListener('message', message);
              frame?.removeEventListener('error', error);
              stop.signal.removeEventListener('abort', abort);
            };
            window.addEventListener('message', message);
            frame!.addEventListener('error', error);
            stop.signal.addEventListener('abort', abort, { once: true });
          })
        );
        frame.src = url.href;
        target.appendChild(frame);
        await ready;
        check();
        const frameWindow = frame.contentWindow;
        if (!frameWindow) throw new Error('MCP sandbox window is unavailable');
        const rejectOtherOrigin = (event: MessageEvent) => {
          if (event.source === frameWindow && event.origin !== url.origin)
            event.stopImmediatePropagation();
        };
        window.addEventListener('message', rejectOtherOrigin, true);
        removeOriginGuard = () => {
          window.removeEventListener('message', rejectOtherOrigin, true);
        };
        const destination = new Proxy(frameWindow, {
          get(targetWindow, key) {
            if (key === 'postMessage')
              return (message: unknown) => {
                check();
                targetWindow.postMessage(message, url.origin);
              };
            return Reflect.get(targetWindow, key, targetWindow);
          },
        });
        transport = new PostMessageTransport(destination, frameWindow);
        const close = transport.close.bind(transport);
        let physicalClose: Promise<void> | undefined;
        transport.close = () => (physicalClose ??= close());
        const send = transport.send.bind(transport);
        transport.send = async (...args) => {
          check();
          await send(...args);
        };
        await track(ownedBridge.connect(transport));
        check();
        view.current = { bridge: ownedBridge, check, track, initialized: false };
        if (latest.current.hostContext) ownedBridge.setHostContext(latest.current.hostContext);
        await track(
          ownedBridge.sendSandboxResourceReady({
            html,
            ...(captured.sandbox.csp ? { csp: captured.sandbox.csp } : {}),
          })
        );
        await stopped;
      } catch (error) {
        primary = error;
        failed = true;
        if (!stop.signal.aborted && error instanceof Error) {
          try {
            captured.onError?.(error);
          } catch {
            /* Errors cannot prevent cleanup. */
          }
        }
      }
      retire();
      await closeTask;
      while (pending.size) await Promise.allSettled([...pending]);
      child.signal.removeEventListener('abort', retire);
      if (failures.length)
        throw new WebOperationCleanupErrorV2(failures, 'MCP frame cleanup failed');
      if (failed) throw primary;
    });
    void task.catch((error: unknown) => {
      if (!stop.signal.aborted && error instanceof Error) captured.onError?.(error);
    });
    return retire;
  }, [
    props.operation,
    props.client,
    props.toolName,
    props.toolResourceUri,
    props.html,
    props.sandbox.url,
    props.sandbox.csp,
  ]);
  useEffect(() => {
    const current = view.current;
    if (!current) return;
    try {
      current.check();
      if (props.hostContext) current.bridge.setHostContext(props.hostContext);
      if (current.initialized && props.toolInput)
        void current.track(current.bridge.sendToolInput({ arguments: props.toolInput }));
      if (current.initialized && props.toolResult)
        void current.track(current.bridge.sendToolResult(props.toolResult));
      if (props.toolInputPartial)
        void current.track(current.bridge.sendToolInputPartial(props.toolInputPartial));
      if (props.toolCancelled) void current.track(current.bridge.sendToolCancelled({}));
    } catch {
      /* Retired views cannot publish. */
    }
  }, [
    props.hostContext,
    props.toolInput,
    props.toolResult,
    props.toolInputPartial,
    props.toolCancelled,
  ]);
  return <div ref={container} style={{ width: '100%', height: '100%' }} />;
});
ControlledMCPAppRendererV2.displayName = 'ControlledMCPAppRendererV2';
export default ControlledMCPAppRendererV2;
