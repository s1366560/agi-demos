import React, { createRef } from 'react';
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { WebOperationContextV2 } from '../../../plugins/webOperationAdmissionV2';
import type { AppRendererProps } from '@mcp-ui/client';
const fixture = vi.hoisted(() => ({
  operation: null as WebOperationContextV2 | null,
  canFallback: true,
  teardown: vi.fn().mockResolvedValue(undefined),
  props: null as (AppRendererProps & { onInitialized?: () => void }) | null,
  api: {
    list: vi.fn(),
    proxyToolCall: vi.fn(),
    proxyToolCallDirect: vi.fn(),
    readResource: vi.fn(),
    listResources: vi.fn(),
  },
}));
vi.mock('../../../services/mcpAppService', () => ({ mcpAppAPI: fixture.api }));
vi.mock('../../../hooks/useMCPClient', () => ({
  useMCPClient: () => ({
    client: null,
    status: 'error',
    operation: fixture.operation,
    canFallback: fixture.canFallback,
    retired: false,
    assertFallback: () => {
      fixture.operation?.check();
      if (!fixture.canFallback) throw new Error('unavailable');
      return fixture.operation;
    },
  }),
}));
vi.mock('../../../stores/project', () => ({
  useProjectStore: (select: any) => select({ currentProject: { id: 'project' } }),
}));
vi.mock('../../../stores/agent/conversationsStore', () => ({
  useConversationsStore: (select: any) =>
    select({ currentConversation: { project_id: 'project' } }),
}));
vi.mock('../../../stores/theme', () => ({
  useThemeStore: (select: any) => select({ computedTheme: 'light' }),
}));
vi.mock('../../../components/mcp-app/ControlledMCPAppRendererV2', () => ({
  default: React.forwardRef((_props: AppRendererProps, _ref) => {
    React.useImperativeHandle(_ref, () => ({ teardownResource: fixture.teardown }));
    fixture.props = _props;
    return <iframe title="mcp" src="about:blank" />;
  }),
}));
import {
  StandardMCPAppRenderer,
  type StandardMCPAppRendererHandle,
} from '../../../components/mcp-app/StandardMCPAppRenderer';
let controller: AbortController;
beforeEach(() => {
  vi.clearAllMocks();
  fixture.canFallback = true;
  fixture.props = null;
  controller = new AbortController();
  const operation = {
    owner: {},
    signal: controller.signal,
    check: () => {
      if (controller.signal.aborted) throw new DOMException('Retired', 'AbortError');
    },
    runChild: async (work: any) => work(operation),
  } as WebOperationContextV2;
  fixture.operation = operation;
  fixture.api.list.mockResolvedValue([]);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const props = {
  toolName: 'owning-tool',
  projectId: 'project',
  serverName: 'server',
  appId: '_synthetic_app',
  html: '<main/>',
};
async function mount() {
  const ref = createRef<StandardMCPAppRendererHandle>();
  const view = render(<StandardMCPAppRenderer {...props} ref={ref} />);
  await waitFor(() => expect(view.container.querySelector('iframe')).not.toBeNull());
  return { ...view, ref, frame: view.container.querySelector('iframe')! };
}
function message(source: Window, data: unknown) {
  window.dispatchEvent(new MessageEvent('message', { source, origin: 'null', data }));
}
it('a dispatched synthetic app mutation failure never retries another route', async () => {
  fixture.api.list.mockResolvedValue([
    { id: 'app', project_id: 'project', server_name: 'server', tool_name: 'owning-tool' },
  ]);
  fixture.api.proxyToolCall.mockRejectedValue(new Error('response lost'));
  await mount();
  await expect(
    fixture.props!.onCallTool!({ name: 'mutation', arguments: { value: 1 } })
  ).rejects.toThrow('response lost');
  expect(fixture.api.proxyToolCall).toHaveBeenCalledOnce();
  expect(fixture.api.proxyToolCallDirect).not.toHaveBeenCalled();
  const options = fixture.api.proxyToolCall.mock.calls[0]![2];
  expect(options.operation).toBe(fixture.operation);
  expect(options.signal).toBe(controller.signal);
});
it('structural route selection excludes another project/server and preserves is_error', async () => {
  fixture.api.list.mockResolvedValue([
    { id: 'other', project_id: 'other', server_name: 'server', tool_name: 'owning-tool' },
  ]);
  fixture.api.proxyToolCallDirect.mockResolvedValue({
    content: [{ type: 'text', text: 'rejected' }],
    is_error: true,
  });
  await mount();
  const result = await fixture.props!.onCallTool!({ name: 'mutation' });
  expect(result.isError).toBe(true);
  expect(fixture.api.proxyToolCall).not.toHaveBeenCalled();
  expect(fixture.api.proxyToolCallDirect).toHaveBeenCalledOnce();
});
it('retirement during lookup prevents any mutation and old SDK callbacks', async () => {
  let resolve!: (value: unknown[]) => void;
  fixture.api.list.mockReturnValue(
    new Promise((r) => {
      resolve = r;
    })
  );
  await mount();
  const old = fixture.props!;
  const call = old.onCallTool!({ name: 'mutation' });
  const rejection = expect(call).rejects.toMatchObject({ name: 'AbortError' });
  controller.abort();
  resolve([]);
  await rejection;
  expect(fixture.api.proxyToolCallDirect).not.toHaveBeenCalled();
  expect(() => old.onMessage!({ role: 'user', content: [] })).toThrow();
});
it('only the current iframe can declare capabilities and settle app RPC', async () => {
  const view = await mount();
  const foreign = document.createElement('iframe');
  document.body.append(foreign);
  act(() =>
    message(foreign.contentWindow!, {
      jsonrpc: '2.0',
      method: 'ui/initialize',
      params: { appCapabilities: { tools: {} } },
    })
  );
  await expect(view.ref.current!.callAppTool('tool')).rejects.toThrow('capability');
  act(() =>
    message(view.frame.contentWindow!, {
      jsonrpc: '2.0',
      method: 'ui/initialize',
      params: { appCapabilities: { tools: {} } },
    })
  );
  const post = vi.spyOn(view.frame.contentWindow!, 'postMessage');
  let done = false;
  const rpc = view.ref.current!.callAppTool('tool').then((value) => {
    done = true;
    return value;
  });
  const id = (post.mock.calls[0]![0] as { id: number }).id;
  act(() => message(foreign.contentWindow!, { jsonrpc: '2.0', id, result: 'forged' }));
  await Promise.resolve();
  expect(done).toBe(false);
  act(() => message(view.frame.contentWindow!, { jsonrpc: '2.0', id, result: 'real' }));
  await expect(rpc).resolves.toBe('real');
  foreign.remove();
});
it('pending RPC is rejected and cleared immediately on owner retirement', async () => {
  const view = await mount();
  act(() =>
    message(view.frame.contentWindow!, {
      jsonrpc: '2.0',
      method: 'ui/initialize',
      params: { appCapabilities: { tools: {} } },
    })
  );
  const rpc = view.ref.current!.callAppTool('tool');
  const rejected = expect(rpc).rejects.toMatchObject({ name: 'AbortError' });
  controller.abort();
  await rejected;
});
it('no client without explicit fallback does not expose an HTTP tool callback', async () => {
  fixture.canFallback = false;
  await mount();
  expect(fixture.props!.onCallTool).toBeUndefined();
});

it('a callback retained from HTTP fallback cannot dispatch after that state ends', async () => {
  await mount();
  const old = fixture.props!.onCallTool!;
  fixture.canFallback = false;
  await expect(old({ name: 'mutation' })).rejects.toThrow('unavailable');
  expect(fixture.api.list).not.toHaveBeenCalled();
  expect(fixture.api.proxyToolCallDirect).not.toHaveBeenCalled();
});

it('a lookup failure may choose direct once but a mutation is never retried', async () => {
  fixture.api.list.mockRejectedValue(new Error('lookup unavailable'));
  fixture.api.proxyToolCallDirect.mockResolvedValue({ content: [], is_error: true });
  await mount();
  await expect(fixture.props!.onCallTool!({ name: 'mutation' })).resolves.toMatchObject({
    isError: true,
  });
  expect(fixture.api.proxyToolCallDirect).toHaveBeenCalledOnce();
});
it('tool arguments are captured before asynchronous route lookup', async () => {
  let resolve!: (value: unknown[]) => void;
  fixture.api.list.mockReturnValue(
    new Promise((r) => {
      resolve = r;
    })
  );
  fixture.api.proxyToolCallDirect.mockResolvedValue({ content: [], is_error: false });
  await mount();
  const args = { nested: { value: 'original' } };
  const call = fixture.props!.onCallTool!({ name: 'mutation', arguments: args });
  args.nested.value = 'changed';
  resolve([]);
  await call;
  expect(fixture.api.proxyToolCallDirect.mock.calls[0]![0].arguments).toEqual({
    nested: { value: 'original' },
  });
});

it('progressive chunks wait for initialized, not size or elapsed time, and stop after retirement', async () => {
  const view = await mount();
  const post = vi.spyOn(view.frame.contentWindow!, 'postMessage');
  view.rerender(<StandardMCPAppRenderer {...props} toolResult={{ content: [] }} ref={view.ref} />);
  act(() => fixture.props!.onSizeChanged?.({ width: 100, height: 100 }));
  expect(post).not.toHaveBeenCalled();
  const initialized = fixture.props!.onInitialized!;
  act(() => initialized());
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({ method: 'ui/notifications/tool-result-chunk' }),
      '*'
    )
  );
  const count = post.mock.calls.length;
  controller.abort();
  act(() => initialized());
  view.rerender(
    <StandardMCPAppRenderer
      {...props}
      toolResult={{ content: [{ type: 'text', text: 'late' }] }}
      ref={view.ref}
    />
  );
  expect(post).toHaveBeenCalledTimes(count);
});

it('observes asynchronous teardown rejection from a handle declared void by the SDK', async () => {
  const view = await mount();
  fixture.teardown.mockRejectedValueOnce(new Error('retired teardown'));
  act(() => view.ref.current!.teardown());
  await act(async () => {});
  expect(fixture.teardown).toHaveBeenCalledOnce();
});
