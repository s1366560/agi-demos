import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { PluginToolResultRenderer } from '@/components/plugins/PluginToolResultRenderer';
import {
  registerBuiltinRenderer,
  resetBuiltinRenderersForTests,
} from '@/services/pluginRendererRegistry';
import { refreshPluginSlots, resetPluginSlotsForTests } from '@/services/pluginSlotService';
import type { PlatformPluginSnapshotResponse } from '@/types/pluginSlots';

vi.mock('@/services/client/httpClient', () => ({
  httpClient: { get: vi.fn() },
}));

import { httpClient } from '@/services/client/httpClient';

function toolResultSnapshot(): PlatformPluginSnapshotResponse {
  return {
    version: 1,
    nonce: 'n',
    profile_id: 'p',
    digest: 'd',
    payload: {
      schema_version: 1,
      profile_id: 'p',
      digest: 'd',
      plugins: [
        {
          id: 'acme',
          provides: [
            {
              kind: 'ui_renderer',
              id: 'memory_card',
              contract: 'tool-result:memory_search',
              config_schema: {
                slot: 'tool_result_renderer',
                module_ref: 'builtin:memory-card',
                permission: 'ui.tools',
              },
            },
          ] as never,
        },
      ],
    },
  };
}

describe('PluginToolResultRenderer', () => {
  beforeEach(() => {
    resetPluginSlotsForTests();
    resetBuiltinRenderersForTests();
  });

  it('renders the fallback when no slot matches the tool', () => {
    render(
      <PluginToolResultRenderer
        toolName="memory_search"
        result={{ ok: 1 }}
        fallback={<div>default-card</div>}
      />
    );
    expect(screen.getByText('default-card')).toBeTruthy();
  });

  it('renders the keyed renderer matching tool-result:<tool>', async () => {
    vi.mocked(httpClient.get).mockResolvedValue(toolResultSnapshot());
    await refreshPluginSlots();
    registerBuiltinRenderer('tool-result:memory_search', () => <div>memory-plugin-card</div>);

    render(
      <PluginToolResultRenderer
        toolName="memory_search"
        result={{ ok: 1 }}
        fallback={<div>default-card</div>}
      />
    );
    expect(screen.getByText('memory-plugin-card')).toBeTruthy();
    expect(screen.queryByText('default-card')).toBeNull();
  });

  it('falls back to the sandbox host for non-keyed matching slots', async () => {
    vi.mocked(httpClient.get).mockResolvedValue(toolResultSnapshot());
    await refreshPluginSlots();

    render(
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
