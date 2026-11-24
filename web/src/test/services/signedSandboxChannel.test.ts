import { afterEach, expect, it, vi } from 'vitest';

import { SandboxChannel } from '@business/environments/ui/signed/channel';

afterEach(() => vi.unstubAllGlobals());

it('merges adjacent terminal input while preserving resize boundaries and input order', async () => {
  const received: object[] = [];
  const invoke = vi.fn(async (_command: string, payload: Record<string, string>) => {
    if (payload.action === 'open') return { channel: 'admitted' };
    if (payload.action === 'read') return new Promise(() => {});
    if (payload.action === 'write') received.push(JSON.parse(payload.data));
    return {};
  });
  vi.stubGlobal('WebSocket', { CONNECTING: 0, OPEN: 1, CLOSED: 3 });
  vi.stubGlobal('memstack', { invoke });
  const socket = new SandboxChannel('project-terminal');
  await new Promise<void>((resolve) => {
    socket.onopen = () => resolve();
  });
  const input = (text: string) => socket.send(JSON.stringify({ type: 'input', data: text }));
  input('a');
  input('b');
  socket.send(JSON.stringify({ type: 'resize', cols: 100, rows: 30 }));
  input('c');
  input('\r');
  await vi.waitFor(() =>
    expect(received).toEqual([
      { type: 'input', data: 'ab' },
      { type: 'resize', cols: 100, rows: 30 },
      { type: 'input', data: 'c\r' },
    ])
  );
  socket.close();
});
