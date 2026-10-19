import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { encodeSlotPortMessageV2, type SlotBridgeIdentityV2 } from '@agistack/plugin-slots';
import { PluginSlotHost } from '@/components/plugins/PluginSlotHost';

const slot = {
  pluginId: 'core',
  slot: 'settings_page' as const,
  id: 'settings',
  moduleRef: 'builtin:web-slot-settings',
  permission: 'ui.settings',
  sandbox: true,
};
const context = { kind: 'settings' as const, sections: [{ id: 'graph', label: 'Graph' }] };
class Port {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onmessageerror: (() => void) | null = null;
  postMessage = vi.fn();
  start = vi.fn();
  close = vi.fn();
}
const channels: Array<{ port1: Port; port2: Port }> = [];
function connect() {
  const frame = screen.getByTestId('plugin-slot-settings') as HTMLIFrameElement;
  const post = vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation(() => undefined);
  fireEvent.load(frame);
  const identity = post.mock.calls.at(-1)![0] as SlotBridgeIdentityV2;
  const port = channels.at(-1)!.port1;
  return { post, identity, port, frame };
}
function receive(
  port: Port,
  identity: SlotBridgeIdentityV2,
  payload: Parameters<typeof encodeSlotPortMessageV2>[1]
) {
  act(() =>
    port.onmessage?.(
      new MessageEvent('message', { data: encodeSlotPortMessageV2(identity, payload) })
    )
  );
}

describe('PluginSlotHost', () => {
  beforeEach(() => {
    channels.length = 0;
    vi.stubGlobal(
      'MessageChannel',
      class {
        port1 = new Port();
        port2 = new Port();
        constructor() {
          channels.push(this);
        }
      }
    );
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
  it('transfers a private port to the opaque frame, then sends owner context only on that port', () => {
    const action = vi.fn();
    const { unmount } = render(
      <PluginSlotHost slot={slot} generationId="g1" initPayload={context} onAction={action} />
    );
    const { post, identity, port, frame } = connect();
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
    expect(frame.getAttribute('srcdoc')).toContain("connect-src 'none'");
    expect(post.mock.calls[0]![1]).toBe('*');
    expect(post.mock.calls[0]![0]).not.toHaveProperty('payload');
    receive(port, { ...identity, instanceNonce: 'stale' }, { type: 'slot:ready' });
    expect(port.postMessage).not.toHaveBeenCalled();
    receive(port, identity, { type: 'slot:ready' });
    expect(frame).toHaveAttribute('data-ready', 'true');
    expect(port.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'slot:init', payload: context })
    );
    receive(port, identity, {
      type: 'slot:action',
      action: { type: 'settings.open', sectionId: 'graph' },
    });
    expect(action).toHaveBeenCalledWith({ type: 'settings.open', sectionId: 'graph' });
    const oldHandler = port.onmessage;
    unmount();
    expect(port.close).toHaveBeenCalled();
    act(() =>
      oldHandler?.(
        new MessageEvent('message', {
          data: encodeSlotPortMessageV2(identity, {
            type: 'slot:action',
            action: { type: 'settings.open', sectionId: 'graph' },
          }),
        })
      )
    );
    expect(action).toHaveBeenCalledTimes(1);
  });
  it('exposes timeout fallback and retries with a fresh nonce', () => {
    vi.useFakeTimers();
    render(<PluginSlotHost slot={slot} />);
    const { port, identity } = connect();
    act(() => vi.advanceTimersByTime(4001));
    expect(screen.getByTestId('plugin-slot-fallback-settings')).toBeTruthy();
    expect(port.close).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button'));
    expect(connect().identity.instanceNonce).not.toBe(identity.instanceNonce);
  });
  it('does not fetch missing resources and leaves a visible fallback', () => {
    render(<PluginSlotHost slot={{ ...slot, moduleRef: 'builtin:missing' }} />);
    expect(screen.queryByTestId('plugin-slot-settings')).toBeNull();
    expect(screen.getByTestId('plugin-slot-fallback-settings')).toBeTruthy();
  });
});
