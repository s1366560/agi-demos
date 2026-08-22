import type { ReactNode } from 'react';

import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { PluginSlotOutlet } from '@/components/plugins/PluginSlotOutlet';
import {
  registerBuiltinRenderer,
  resetBuiltinRenderersForTests,
} from '@/services/pluginRendererRegistry';
import {
  WebUiSlotAuthorityContextV2,
  type WebUiSlotAuthorityStateV2,
} from '@/routes/v2/webUiSlotAuthorityStateV2';

const settingsSlot = Object.freeze({
  pluginId: 'acme',
  slot: 'settings_page' as const,
  id: 'settings-card',
  contract: 'ui-slot:settings-card',
  moduleRef: 'builtin:settings-card',
  permission: 'ui.settings',
  sandbox: true,
});

function renderWithSlots(slots = [settingsSlot]) {
  const state: WebUiSlotAuthorityStateV2 = {
    slotDefinitions: slots,
    status: 'ready',
    uiSlotArtifactIds: ['test.ui-slots.v1'],
  };
  return (ui: ReactNode) =>
    render(
      <WebUiSlotAuthorityContextV2.Provider value={state}>
        {ui}
      </WebUiSlotAuthorityContextV2.Provider>
    );
}

describe('PluginSlotOutlet', () => {
  beforeEach(() => {
    resetBuiltinRenderersForTests();
  });

  it('renders nothing when no V2 slot of the kind exists', () => {
    const { container } = renderWithSlots()(<PluginSlotOutlet kind="nav_item" />);
    expect(container.innerHTML).toBe('');
  });

  it('renders the sandbox host for V2 slots without a keyed renderer', () => {
    renderWithSlots()(<PluginSlotOutlet kind="settings_page" />);
    const frame = screen.getByTestId('plugin-slot-settings-card');
    expect(frame.tagName).toBe('IFRAME');
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
  });

  it('renders the keyed builtin renderer when registered', () => {
    registerBuiltinRenderer('ui-slot:settings-card', () => <div>keyed-settings</div>);
    renderWithSlots()(<PluginSlotOutlet kind="settings_page" />);
    expect(screen.getByText('keyed-settings')).toBeTruthy();
  });

  it('filters by contractId when provided', () => {
    renderWithSlots()(<PluginSlotOutlet kind="settings_page" contractId="ui-slot:other" />);
    expect(screen.queryByTestId('plugin-slot-settings-card')).toBeNull();
  });
});
