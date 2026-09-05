import { act, render } from '@testing-library/react';
import { createRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PostMessageTransport } from '@mcp-ui/client';
import type { AppRendererHandle } from '@mcp-ui/client';
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  type WebOperationContextV2,
} from '../../plugins/webOperationAdmissionV2';
import ControlledMCPAppRendererV2 from '../../components/mcp-app/ControlledMCPAppRendererV2';
async function fixture() {
  const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
  await runtime.bootstrap(profile);
  const admission = new WebOperationAdmissionV2(runtime);
  admission.setEnabled(true);
  let operation!: WebOperationContextV2, ready!: () => void;
  const started = new Promise<void>((resolve) => {
    ready = resolve;
  });
  const parent = admission.run(async (context) => {
    operation = context;
    ready();
    await new Promise<void>((resolve) =>
      context.signal.addEventListener('abort', () => resolve(), { once: true })
    );
    context.check();
  });
  void parent.catch(() => undefined);
  await started;
  return {
    runtime,
    admission,
    operation,
    async close() {
      admission.invalidate();
      await Promise.allSettled([parent]);
      await admission.close();
      await runtime.close();
    },
  };
}
async function flush() {
  await act(async () => {
    for (let i = 0; i < 20; i++) await Promise.resolve();
    if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(0);
  });
}
const sandbox = { url: new URL('https://sandbox.example/proxy') };
function send(
  frame: HTMLIFrameElement,
  method: string,
  params: object = {},
  origin = sandbox.url.origin
) {
  act(() => {
    window.dispatchEvent(
      new MessageEvent('message', {
        source: frame.contentWindow,
        origin,
        data: { jsonrpc: '2.0', method, params },
      })
    );
  });
}
beforeEach(() => {
  // Keep DOM navigation local; the actual official bridge and message listeners still run.
  vi.spyOn(HTMLIFrameElement.prototype, 'src', 'set').mockImplementation(function (
    this: HTMLIFrameElement,
    value: string
  ) {
    this.dataset.requestedSrc = value;
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
describe('controlled official MCP bridge with actual Loader', () => {
  it('closes official listener and pending bridge RPC timers on owner retirement', async () => {
    const f = await fixture();
    vi.useFakeTimers();
    const close = vi.spyOn(PostMessageTransport.prototype, 'close');
    const ref = createRef<AppRendererHandle>();
    const ui = render(
      <ControlledMCPAppRendererV2
        ref={ref}
        operation={f.operation}
        toolName="tool"
        html="<p>fixture</p>"
        sandbox={sandbox}
      />
    );
    await flush();
    const frame = ui.container.querySelector('iframe')!;
    expect(frame).not.toBeNull();
    vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation(() => undefined);
    expect(f.runtime.getSnapshot()!.leaseCount).toBe(2);
    send(frame, 'ui/notifications/sandbox-proxy-ready', {}, 'https://wrong.example');
    await flush();
    expect(close).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(1);
    send(frame, 'ui/notifications/sandbox-proxy-ready');
    await flush();
    const pending = ref.current!.teardownResource() as unknown as Promise<unknown>;
    const rejection = expect(pending).rejects.toThrow();
    expect(vi.getTimerCount()).toBe(1);
    act(() => f.admission.invalidate());
    await flush();
    await rejection;
    expect(close).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
    expect(ui.container.querySelector('iframe')).toBeNull();
    ui.unmount();
    await f.close();
  });
  it('unmount before sandbox readiness removes its timeout and never installs transport', async () => {
    const f = await fixture();
    vi.useFakeTimers();
    const close = vi.spyOn(PostMessageTransport.prototype, 'close');
    const ui = render(
      <ControlledMCPAppRendererV2
        operation={f.operation}
        toolName="tool"
        html="fixture"
        sandbox={sandbox}
      />
    );
    await flush();
    expect(vi.getTimerCount()).toBe(1);
    ui.unmount();
    await flush();
    expect(vi.getTimerCount()).toBe(0);
    expect(close).not.toHaveBeenCalled();
    expect(f.runtime.getSnapshot()!.leaseCount).toBe(1);
    await f.close();
  });
  it('reports resource read failure before retirement and releases its child', async () => {
    const f = await fixture();
    const error = new Error('resource failed'),
      onError = vi.fn();
    const ui = render(
      <ControlledMCPAppRendererV2
        operation={f.operation}
        toolName="tool"
        toolResourceUri="ui://tool"
        sandbox={sandbox}
        onReadResource={async () => {
          throw error;
        }}
        onError={onError}
      />
    );
    await flush();
    expect(onError).toHaveBeenCalledExactlyOnceWith(error);
    expect(ui.container.querySelector('iframe')).toBeNull();
    expect(f.runtime.getSnapshot()!.leaseCount).toBe(1);
    ui.unmount();
    await f.close();
  });
  it('replays exact initialization notifications and latest delayed host context', async () => {
    const f = await fixture();
    const initialized = vi.fn();
    const initial = {
      operation: f.operation,
      toolName: 'tool',
      html: 'fixture',
      sandbox,
      toolInputPartial: { arguments: { draft: 1 } },
      toolCancelled: true,
      onInitialized: initialized,
    };
    const ui = render(<ControlledMCPAppRendererV2 {...initial} hostContext={{ theme: 'light' }} />);
    await flush();
    const frame = ui.container.querySelector('iframe')!;
    const post = vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation(() => undefined);
    ui.rerender(<ControlledMCPAppRendererV2 {...initial} hostContext={{ theme: 'dark' }} />);
    send(frame, 'ui/notifications/sandbox-proxy-ready');
    await flush();
    send(frame, 'ui/notifications/initialized');
    await flush();
    expect(initialized).toHaveBeenCalledOnce();
    expect(post.mock.calls.map(([message]) => message)).toContainEqual(
      expect.objectContaining({
        method: 'ui/notifications/host-context-changed',
        params: { theme: 'dark' },
      })
    );
    expect(post.mock.calls.map(([message]) => message)).toContainEqual(
      expect.objectContaining({
        method: 'ui/notifications/tool-input-partial',
        params: { arguments: { draft: 1 } },
      })
    );
    expect(post.mock.calls.map(([message]) => message)).toContainEqual(
      expect.objectContaining({ method: 'ui/notifications/tool-cancelled' })
    );
    ui.rerender(
      <ControlledMCPAppRendererV2
        {...initial}
        toolInputPartial={{ arguments: { draft: 2 } }}
        hostContext={{ theme: 'dark' }}
      />
    );
    await flush();
    expect(post.mock.calls.map(([message]) => message)).toContainEqual(
      expect.objectContaining({
        method: 'ui/notifications/tool-input-partial',
        params: { arguments: { draft: 2 } },
      })
    );
    ui.unmount();
    await flush();
    await f.close();
  });
});
