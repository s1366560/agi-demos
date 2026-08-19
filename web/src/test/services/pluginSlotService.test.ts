import { beforeEach, describe, expect, it } from 'vitest';

import {
  extractSlotDefinitions,
  getPluginSlots,
  PluginSlotError,
  resetPluginSlotsForTests,
  subscribePluginSlots,
} from '@/services/pluginSlotService';
import type { PlatformPluginSnapshotResponse } from '@/types/pluginSlots';

function snapshotWith(provides: Array<Record<string, unknown>>): PlatformPluginSnapshotResponse {
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
          provides: provides as never,
        },
      ],
    },
  };
}

const validCapability = {
  kind: 'ui_slot',
  id: 'settings-card',
  contract: 'ui-slot:settings-card',
  config_schema: {
    slot: 'settings_page',
    module_ref: 'builtin:settings-card',
    permission: 'ui.settings',
    sandbox: true,
  },
};

describe('pluginSlotService.extractSlotDefinitions', () => {
  beforeEach(() => resetPluginSlotsForTests());

  it('extracts valid ui_slot and ui_renderer capabilities', () => {
    const snapshot = snapshotWith([
      validCapability,
      {
        kind: 'ui_renderer',
        id: 'tool-card',
        contract: 'ui-renderer:tool-card',
        config_schema: {
          slot: 'tool_result_renderer',
          module_ref: 'builtin:tool-card',
          permission: 'ui.tools',
        },
      },
      { kind: 'tool', id: 'not-a-slot', contract: 'tool:x' },
    ]);

    const slots = extractSlotDefinitions(snapshot);

    expect(slots).toHaveLength(2);
    expect(slots[0]).toMatchObject({
      pluginId: 'acme',
      slot: 'settings_page',
      id: 'settings-card',
      moduleRef: 'builtin:settings-card',
      permission: 'ui.settings',
      sandbox: true,
    });
    expect(slots[1].slot).toBe('tool_result_renderer');
  });

  it('rejects non-builtin module references', () => {
    const snapshot = snapshotWith([
      {
        ...validCapability,
        config_schema: {
          ...validCapability.config_schema,
          module_ref: 'https://evil.example/x.js',
        },
      },
    ]);
    expect(() => extractSlotDefinitions(snapshot)).toThrow(PluginSlotError);
  });

  it('rejects non-sandboxed slots and non-ui permissions', () => {
    const noSandbox = snapshotWith([
      {
        ...validCapability,
        config_schema: { ...validCapability.config_schema, sandbox: false },
      },
    ]);
    expect(() => extractSlotDefinitions(noSandbox)).toThrow(/sandbox/);

    const badPermission = snapshotWith([
      {
        ...validCapability,
        config_schema: { ...validCapability.config_schema, permission: 'admin.full' },
      },
    ]);
    expect(() => extractSlotDefinitions(badPermission)).toThrow(/ui\./);
  });

  it('rejects unknown slot kinds', () => {
    const snapshot = snapshotWith([
      {
        ...validCapability,
        config_schema: { ...validCapability.config_schema, slot: 'root_access' },
      },
    ]);
    expect(() => extractSlotDefinitions(snapshot)).toThrow(/unknown slot kind/);
  });

  it('keeps the cache and notifies subscribers', () => {
    const seen: number[] = [];
    const unsubscribe = subscribePluginSlots((slots) => seen.push(slots.length));
    expect(getPluginSlots()).toEqual([]);
    unsubscribe();
    expect(seen).toEqual([]);
  });
});
