import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { PluginSlotOutlet } from '@/components/plugins/PluginSlotOutlet';
import {
  registerBuiltinRenderer,
  resetBuiltinRenderersForTests,
} from '@/services/pluginRendererRegistry';
import { resetPluginSlotsForTests } from '@/services/pluginSlotService';
import type { PlatformPluginSnapshotResponse } from '@/types/pluginSlots';

vi.mock('@/services/client/httpClient', () => ({
  httpClient: { get: vi.fn() },
}));

import { httpClient } from '@/services/client/httpClient';
import { refreshPluginSlots } from '@/services/pluginSlotService';

function snapshot(capabilities: Array<Record<string, unknown>>): PlatformPluginSnapshotResponse {
  return {
    version: 1,
    nonce: 'n',
    profile_id: 'p',
    digest: 'd',
    payload: {
      schema_version: 1,
      profile_id: 'p',
      digest: 'd',
      plugins: [{ id: 'acme', provides: capabilities as never }],
    },
  };
}

const settingsSlot = {
  kind: 'ui_slot',
  id: 'settings-card',
  contract: 'ui-slot:settings-card',
  config_schema: {
    slot: 'settings_page',
    module_ref: 'builtin:settings-card',
    permission: 'ui.settings',
  },
};

describe('PluginSlotOutlet', () => {
  beforeEach(() => {
    resetPluginSlotsForTests();
    resetBuiltinRenderersForTests();
    vi.mocked(httpClient.get).mockResolvedValue(snapshot([settingsSlot]));
  });

  it('renders nothing when no slot of the kind exists', async () => {
    const { container } = render(<PluginSlotOutlet kind="nav_item" />);
    await screen.findByTestId('plugin-slot-settings-card', undefined, {
      timeout: 50,
    }).catch(() => undefined);
    expect(container.innerHTML).toBe('');
  });

  it('renders the sandbox host for slots without a keyed renderer', async () => {
    render(<PluginSlotOutlet kind="settings_page" />);
    const frame = await screen.findByTestId('plugin-slot-settings-card');
    expect(frame.tagName).toBe('IFRAME');
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
  });

  it('renders the keyed builtin renderer when registered', async () => {
    registerBuiltinRenderer('ui-slot:settings-card', () => <div>keyed-settings</div>);
    render(<PluginSlotOutlet kind="settings_page" />);
    expect(await screen.findByText('keyed-settings')).toBeTruthy();
  });

  it('filters by contractId when provided', async () => {
    render(<PluginSlotOutlet kind="settings_page" contractId="ui-slot:other" />);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByTestId('plugin-slot-settings-card')).toBeNull();
  });
});
