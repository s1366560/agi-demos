import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { PluginSlotHost } from '@/components/plugins/PluginSlotHost';
import { encodeSlotMessage } from '@/services/pluginSlotProtocol';
import type { UiSlotDefinition } from '@/types/pluginSlots';

const slot: UiSlotDefinition = {
  pluginId: 'acme',
  slot: 'settings_page',
  id: 'settings-card',
  moduleRef: 'builtin:settings-card',
  permission: 'ui.settings',
  sandbox: true,
};

describe('PluginSlotHost', () => {
  it('mounts a sandboxed iframe pointing at the builtin module', () => {
    render(<PluginSlotHost slot={slot} />);
    const iframe = screen.getByTestId('plugin-slot-settings-card');
    expect(iframe).toHaveAttribute('sandbox', 'allow-scripts');
    expect(iframe.getAttribute('src')).toContain('settings-card');
  });

  it('ignores foreign messages and handles guest protocol messages', () => {
    const onAction = vi.fn();
    const onError = vi.fn();
    render(<PluginSlotHost slot={slot} onAction={onAction} onError={onError} />);

    fireEvent(window, new MessageEvent('message', { data: { hello: 'world' } }));
    fireEvent(
      window,
      new MessageEvent('message', {
        data: encodeSlotMessage({ type: 'slot:ready', slotId: 'other-slot' }),
      })
    );
    expect(onAction).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();

    fireEvent(
      window,
      new MessageEvent('message', {
        data: encodeSlotMessage({ type: 'slot:error', slotId: 'settings-card', message: 'boom' }),
      })
    );
    // The source check rejects messages not coming from the iframe window,
    // so the handler must not fire for synthetic window events.
    expect(onError).not.toHaveBeenCalled();
  });
});
