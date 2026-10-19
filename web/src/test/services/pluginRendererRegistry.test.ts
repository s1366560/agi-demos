import { describe, expect, it } from 'vitest';
import { createPluginRendererRegistryV2 } from '@/services/pluginRendererRegistry';

const slot = Object.freeze({
  id: 'result',
  pluginId: 'core',
  contract: 'tool-result:default',
  slot: 'tool_result_renderer' as const,
  moduleRef: 'builtin:web-slot-tool-result',
  permission: 'ui.tools',
  sandbox: true,
});

describe('generation-owned renderer registry', () => {
  it('resolves only the exact definitions in its own generation', () => {
    let active = true;
    const registry = createPluginRendererRegistryV2([slot], () => active);
    expect(registry.resolve(slot)).toBeTypeOf('function');
    expect(registry.resolve({ ...slot })).toBeUndefined();
    expect(createPluginRendererRegistryV2([], () => true).resolve(slot)).toBeUndefined();
    active = false;
    expect(registry.resolve(slot)).toBeUndefined();
  });
  it('does not resolve arbitrary compiled-module claims', () => {
    const other = { ...slot, moduleRef: 'builtin:external-result' };
    expect(createPluginRendererRegistryV2([other], () => true).resolve(other)).toBeUndefined();
  });
});
