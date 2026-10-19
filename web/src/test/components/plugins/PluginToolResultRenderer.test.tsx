import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PluginToolResultRenderer } from '@/components/plugins/PluginToolResultRenderer';
import { createPluginRendererRegistryV2 } from '@/services/pluginRendererRegistry';
import { WebUiSlotAuthorityContextV2 } from '@/routes/v2/webUiSlotAuthorityStateV2';

const slot = Object.freeze({
  pluginId: 'core',
  slot: 'tool_result_renderer' as const,
  id: 'result',
  contract: 'tool-result:default',
  moduleRef: 'builtin:web-slot-tool-result',
  permission: 'ui.tools',
  sandbox: true,
});
const card = (
  <PluginToolResultRenderer
    toolName="memory_search"
    result="Memory result body"
    fallback={<div>default-card</div>}
  />
);

describe('PluginToolResultRenderer', () => {
  it('renders the original fallback without a matching contribution', () => {
    render(card);
    expect(screen.getByText('default-card')).toBeTruthy();
  });
  it('renders the real folded Markdown result through its generation registry', () => {
    render(
      <WebUiSlotAuthorityContextV2.Provider
        value={{
          slotDefinitions: [slot],
          status: 'ready',
          uiSlotArtifactIds: ['test'],
          renderers: createPluginRendererRegistryV2([slot], () => true),
        }}
      >
        {card}
      </WebUiSlotAuthorityContextV2.Provider>
    );
    expect(screen.getByText('Memory result body')).toBeTruthy();
    expect(screen.queryByText('default-card')).toBeNull();
  });
  it('preserves the result if a selected module is unavailable', () => {
    render(
      <WebUiSlotAuthorityContextV2.Provider
        value={{
          slotDefinitions: [{ ...slot, moduleRef: 'builtin:missing' }],
          status: 'ready',
          uiSlotArtifactIds: ['test'],
        }}
      >
        {card}
      </WebUiSlotAuthorityContextV2.Provider>
    );
    expect(screen.getByText('default-card')).toBeTruthy();
  });
});
