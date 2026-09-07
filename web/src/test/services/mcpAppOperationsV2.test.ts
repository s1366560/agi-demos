import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  installWebOperationAdmissionV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';
import { mcpAppAPI } from '@/services/mcpAppService';
import { projectSandboxService } from '@/services/projectSandboxService';

const transport = vi.hoisted(() => ({
  calls: [] as Array<{ url: string; signal?: AbortSignal }>,
  pending: Promise<unknown> | undefined,
}));
vi.mock('@/services/client/kernelHttpClient', () => ({
  kernelHttpClient: {
    get: async (url: string, config: { signal?: AbortSignal }) => {
      transport.calls.push({ url, ...config });
      return await transport.pending;
    },
    post: async (url: string, _body: unknown, config: { signal?: AbortSignal }) => {
      transport.calls.push({ url, ...config });
      return await transport.pending;
    },
  },
}));
const gate = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
};
let runtime: RendererPluginRuntimeV2;
let admission: WebOperationAdmissionV2;
let uninstall: () => void;
beforeEach(async () => {
  runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
  await runtime.bootstrap(profile);
  admission = new WebOperationAdmissionV2(runtime);
  admission.setEnabled(true);
  uninstall = installWebOperationAdmissionV2(admission);
  transport.calls = [];
  transport.pending = undefined;
});
afterEach(async () => {
  await admission.close();
  uninstall();
  await runtime.close();
});
const requests: Array<[string, (operation: WebOperationContextV2) => Promise<unknown>]> = [
  ['/mcp/apps?project_id=p', (operation) => mcpAppAPI.list('p', false, { operation })],
  [
    '/mcp/apps/resources/read',
    (operation) => mcpAppAPI.readResource('ui://app', 'p', 'server', { operation }),
  ],
  [
    '/mcp/apps/resources/list',
    (operation) => mcpAppAPI.listResources('p', 'server', { operation }),
  ],
  [
    '/mcp/apps/app/tool-call',
    (operation) =>
      mcpAppAPI.proxyToolCall('app', { tool_name: 'run', arguments: {} }, { operation }),
  ],
  [
    '/mcp/apps/proxy/tool-call',
    (operation) =>
      mcpAppAPI.proxyToolCallDirect(
        { project_id: 'p', server_name: 'server', tool_name: 'run', arguments: {} },
        { operation }
      ),
  ],
  [
    '/projects/p/sandbox/proxy-auth-cookie',
    (operation) => projectSandboxService.ensureProxyAuthCookie('p', { operation }),
  ],
];
describe('MCP HTTP children retain their originating App operation', () => {
  it.each(requests)(
    '%s drains the pending response after owner retirement',
    async (url, request) => {
      const response = gate<unknown>();
      transport.pending = response.promise;
      const parentReady = gate<WebOperationContextV2>();
      const finishParent = gate<void>();
      const parent = admission.run(async (operation) => {
        parentReady.resolve(operation);
        await finishParent.promise;
      });
      const parentResult = parent.catch((error: unknown) => error);
      const operation = await parentReady.promise;
      const child = request(operation);
      const childResult = child.catch((error: unknown) => error);
      await vi.waitFor(() => expect(transport.calls).toHaveLength(1));
      expect(transport.calls[0]?.url).toBe(url);
      expect(runtime.getSnapshot()?.leaseCount).toBe(2);
      admission.invalidate();
      finishParent.resolve();
      expect(transport.calls[0]?.signal?.aborted).toBe(true);
      let drained = false;
      const closing = admission.close().then(() => {
        drained = true;
      });
      await Promise.resolve();
      expect(drained).toBe(false);
      response.resolve({ contents: [], resources: [], content: [] });
      expect(await childResult).toMatchObject({ name: 'AbortError' });
      expect(await parentResult).toMatchObject({ name: 'AbortError' });
      await closing;
      expect(runtime.getSnapshot()?.leaseCount).toBe(0);
    }
  );
  it('refuses a retired parent without starting a new owner request', async () => {
    const ready = gate<WebOperationContextV2>();
    const finish = gate<void>();
    const parent = admission.run(async (operation) => {
      ready.resolve(operation);
      await finish.promise;
    });
    const observed = parent.catch((error: unknown) => error);
    const operation = await ready.promise;
    admission.invalidate();
    await expect(
      mcpAppAPI.proxyToolCall('app', { tool_name: 'run', arguments: {} }, { operation })
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(transport.calls).toHaveLength(0);
    finish.resolve();
    await observed;
  });
});
