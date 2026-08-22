import type { ReactNode } from 'react';

import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { PluginToolResultRenderer } from '@/components/plugins/PluginToolResultRenderer';
import {
  registerBuiltinRenderer,
  resetBuiltinRenderersForTests,
} from '@/services/pluginRendererRegistry';
import {
  WebUiSlotAuthorityContextV2,
  type WebUiSlotAuthorityStateV2,
} from '@/routes/v2/webUiSlotAuthorityStateV2';

const toolResultSlot = Object.freeze({
  pluginId: 'acme',
  slot: 'tool_result_renderer' as const,
  id: 'memory_card',
  contract: 'tool-result:memory_search',
  moduleRef: 'builtin:memory-card',
  permission: 'ui.tools',
  sandbox: true,
});

function renderWithSlots(ui: ReactNode, slots = [toolResultSlot]) {
  const state: WebUiSlotAuthorityStateV2 = {
    slotDefinitions: slots,
    status: 'ready',
    uiSlotArtifactIds: ['test.ui-slots.v1'],
  };
  return render(
    <WebUiSlotAuthorityContextV2.Provider value={state}>{ui}</WebUiSlotAuthorityContextV2.Provider>
  );
}

describe('PluginToolResultRenderer', () => {
  beforeEach(() => {
    resetBuiltinRenderersForTests();
  });

  it('renders the fallback when no slot matches the tool', () => {
    renderWithSlots(
      <PluginToolResultRenderer
        toolName="memory_search"
        result={{ ok: 1 }}
        fallback={<div>default-card</div>}
      />,
      []
    );
    expect(screen.getByText('default-card')).toBeTruthy();
  });

  it('renders the keyed renderer matching tool-result:<tool>', () => {
    registerBuiltinRenderer('tool-result:memory_search', () => <div>memory-plugin-card</div>);

    renderWithSlots(
      <PluginToolResultRenderer
        toolName="memory_search"
        result={{ ok: 1 }}
        fallback={<div>default-card</div>}
      />
    );
    expect(screen.getByText('memory-plugin-card')).toBeTruthy();
    expect(screen.queryByText('default-card')).toBeNull();
  });

  it('falls back to the sandbox host for non-keyed matching slots', () => {
    renderWithSlots(
      <PluginToolResultRenderer
        toolName="memory_search"
        result={{ ok: 1 }}
        fallback={<div>default-card</div>}
      />
    );
    const frame = screen.getByTestId('plugin-slot-memory_card');
    expect(frame.tagName).toBe('IFRAME');
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
  });
});
