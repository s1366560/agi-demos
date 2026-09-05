import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { agentService } from '@/services/agentService';
import { installResourceOperationFixtureV2 } from './webResourceOperationFixtureV2';
import type { AgentStreamHandler } from '@/types/agent';
vi.mock('@/utils/tokenResolver', () => ({ getAuthToken: () => 'test-token' }));
class Socket {
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSED = 3;
  static sockets: Socket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: Record<string, unknown>[] = [];
  constructor() {
    Socket.sockets.push(this);
    queueMicrotask(() => {
      this.readyState = 1;
      this.onopen?.();
    });
  }
  send(raw: string) {
    this.sent.push(JSON.parse(raw));
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  message(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}
let fixture: ReturnType<typeof installResourceOperationFixtureV2>;
beforeEach(async () => {
  await agentService.disconnect().catch(() => undefined);
  Socket.sockets = [];
  vi.stubGlobal('WebSocket', Socket);
  fixture = installResourceOperationFixtureV2();
});
afterEach(async () => {
  await agentService.disconnect().catch(() => undefined);
  await fixture.close();
  vi.unstubAllGlobals();
});
it('retires pending send and control acknowledgements and clears subscriptions synchronously', async () => {
  const context = await agentService.connectSession();
  const pending = agentService.chat(
    { conversation_id: 'c', project_id: 'p', message: 'hello' },
    {} as AgentStreamHandler,
    context
  );
  const control = agentService.killSubAgent('c', 'r', { expectedRunRevision: 1, cascade: false });
  const sendResult = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  const controlResult = expect(control).rejects.toMatchObject({ name: 'AbortError' });
  fixture.admission.invalidate();
  expect(agentService.getOperationContext()).toBeUndefined();
  expect((agentService as any).handlers.size).toBe(0);
  expect((agentService as any).pendingSendAcks.size).toBe(0);
  await Promise.all([sendResult, controlResult]);
});
it('old conversation cleanup cannot remove a new owner subscription for the same id', async () => {
  const first = await agentService.connectSession();
  const cleanup = agentService.subscribe('c', {} as AgentStreamHandler, undefined, first);
  fixture.admission.invalidate();
  const second = await agentService.connectSession();
  const handler = {} as AgentStreamHandler;
  agentService.subscribe('c', handler, undefined, second);
  const subscribed = (agentService as any).handlers.get('c');
  cleanup();
  expect((agentService as any).handlers.get('c')).toBe(subscribed);
  expect(() => agentService.subscribe('c', {} as AgentStreamHandler, undefined, first)).toThrow();
});
it('old lifecycle cleanup cannot remove a new callback with identical project and tenant', async () => {
  const context = await agentService.connectSession();
  const cleanup = agentService.subscribeLifecycleState('p', 't', vi.fn(), context);
  const callback = vi.fn();
  agentService.subscribeLifecycleState('p', 't', callback, context);
  cleanup();
  expect((agentService as any).lifecycleStateSubscriber.callback).toBe(callback);
});
it('acknowledged send still rejects if owner retires before its continuation; no replay', async () => {
  const context = await agentService.connectSession();
  const result = agentService.chat(
    { conversation_id: 'c', project_id: 'p', message: 'hello' },
    {} as AgentStreamHandler,
    context
  );
  const assertion = expect(result).rejects.toMatchObject({ name: 'AbortError' });
  Socket.sockets[0]!.message({ type: 'ack', action: 'send_message', conversation_id: 'c' });
  fixture.admission.invalidate();
  await assertion;
  await agentService.connectSession();
  expect(Socket.sockets[1]!.sent.filter((x) => x.type === 'send_message')).toHaveLength(0);
});
it('disabled admission creates no socket and no subscription', async () => {
  fixture.admission.setEnabled(false);
  await expect(agentService.connectSession()).rejects.toThrow();
  expect(Socket.sockets).toHaveLength(0);
  expect(() => agentService.subscribe('c', {} as AgentStreamHandler)).toThrow();
});

it('an escaped handler from a retired owner cannot dispatch into a replacement owner', async () => {
  const context = await agentService.connectSession();
  const callback = vi.fn();
  agentService.subscribe('c', Object.freeze({ onMessage: callback }), undefined, context);
  const bound = (agentService as any).handlers.get('c');
  expect(Object.keys(bound)).toEqual(['onMessage']);
  expect('onMessage' in bound).toBe(true);
  const escaped = { ...bound };
  fixture.admission.invalidate();
  await agentService.connectSession();
  expect(() => escaped.onMessage({ type: 'message', data: {} })).toThrow();
  expect(callback).not.toHaveBeenCalled();
});
