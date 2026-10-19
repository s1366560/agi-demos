import type { ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PluginSlotOutlet } from '@/components/plugins/PluginSlotOutlet';
import {
  WebUiSlotAuthorityContextV2,
  type WebUiSlotAuthorityStateV2,
} from '@/routes/v2/webUiSlotAuthorityStateV2';

const settingsSlot = Object.freeze({
  pluginId: 'core',
  slot: 'settings_page' as const,
  id: 'settings',
  contract: 'ui-builtin:settings',
  moduleRef: 'builtin:web-slot-settings',
  permission: 'ui.settings',
  sandbox: true,
});
const context = { kind: 'settings' as const, sections: [{ id: 'memory', label: 'Memory' }] };
function wrapper(ui: ReactNode, state: Partial<WebUiSlotAuthorityStateV2> = {}) {
  return (
    <WebUiSlotAuthorityContextV2.Provider
      value={{
        slotDefinitions: [settingsSlot],
        status: 'ready',
        uiSlotArtifactIds: ['test'],
        generationId: 'g1',
        ...state,
      }}
    >
      {ui}
    </WebUiSlotAuthorityContextV2.Provider>
  );
}

describe('PluginSlotOutlet', () => {
  it('renders nothing when the kind or contract is absent', () => {
    const { container, rerender } = render(wrapper(<PluginSlotOutlet kind="nav_item" />));
    expect(container.innerHTML).toBe('');
    rerender(wrapper(<PluginSlotOutlet kind="settings_page" contractId="other" />));
    expect(container.innerHTML).toBe('');
  });
  it('uses a packaged opaque sandbox and remounts it for a new generation', () => {
    const { rerender } = render(
      wrapper(<PluginSlotOutlet kind="settings_page" context={context} />)
    );
    const frame = screen.getByTestId('plugin-slot-settings');
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
    expect(frame).toHaveAttribute('srcdoc');
    rerender(
      wrapper(<PluginSlotOutlet kind="settings_page" context={context} />, { generationId: 'g2' })
    );
    expect(screen.getByTestId('plugin-slot-settings')).not.toBe(frame);
  });
  it('revokes native actions immediately when their generation retires', () => {
    let active = true;
    const action = vi.fn();
    const renderers = {
      resolve:
        () =>
        (props: { onAction?: (value: { type: 'settings.open'; sectionId: string }) => void }) => (
          <button onClick={() => props.onAction?.({ type: 'settings.open', sectionId: 'memory' })}>
            Open settings
          </button>
        ),
    };
    render(
      wrapper(<PluginSlotOutlet kind="settings_page" context={context} onAction={action} />, {
        renderers,
        isActive: () => active,
      })
    );
    fireEvent.click(screen.getByText('Open settings'));
    expect(action).toHaveBeenCalledTimes(1);
    active = false;
    fireEvent.click(screen.getByText('Open settings'));
    expect(action).toHaveBeenCalledTimes(1);
  });
});
