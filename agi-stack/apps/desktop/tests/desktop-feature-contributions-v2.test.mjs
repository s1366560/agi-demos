import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const runtime = require('@agistack/plugin-runtime');
const { createDesktopProductionRendererRuntimeV2 } = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopProductionRendererRuntimeV2.js');
const { projectDesktopRendererAuthorityV2 } = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererAuthorityProjectionV2.js');
const profile = () => JSON.parse(readFileSync(new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url), 'utf8'));

test('production desktop profile contributes individual routes, settings, commands, shortcuts and work panels', async () => {
  const renderer = createDesktopProductionRendererRuntimeV2();
  try {
    const baseline = profile(); await renderer.bootstrap(baseline);
    const before = projectDesktopRendererAuthorityV2(renderer.getSnapshot());
    assert.ok(before.routeIds.includes('tenant-tenant-plugins'));
    assert.ok(before.settingsSectionIds.includes('plugins'));
    assert.ok(before.commandIds.includes('refresh-runtime'));
    assert.ok(before.shortcutIds.includes('command-palette'));
    assert.ok(before.slotDefinitions.some((slot) => slot.slot === 'work_panel' && slot.id === 'terminal'));
    const next = structuredClone(baseline);
    const targets = ['desktop.routes.feature.tenant-tenant-plugins.v1', 'desktop.settings.plugins.v1', 'desktop.commands.refresh-runtime.v1', 'desktop.shortcuts.command-palette.v1', 'desktop.ui-slots.panel.terminal.v1'];
    for (const ref of targets) {
      const entry = next.entries.find((entry) => entry.config?.contributions?.some((item) => item.payload.artifact_refs.includes(ref)));
      assert.ok(entry, ref); entry.enabled = false;
    }
    const { digest, ...payload } = next; next.digest = await runtime.digestV2(payload);
    await renderer.replaceBaseline(next);
    const after = projectDesktopRendererAuthorityV2(renderer.getSnapshot());
    assert.equal(after.routeIds.includes('tenant-tenant-plugins'), false);
    assert.equal(after.navigationRouteIds.includes('tenant-tenant-plugins'), false);
    assert.equal(after.settingsSectionIds.includes('plugins'), false);
    assert.equal(after.commandIds.includes('refresh-runtime'), false);
    assert.equal(after.shortcutIds.includes('command-palette'), false);
    assert.equal(after.slotDefinitions.some((slot) => slot.slot === 'work_panel' && slot.id === 'terminal'), false);
    assert.ok(after.routeIds.includes('tenant-tenant-skills'));
    assert.ok(after.settingsSectionIds.includes('skills'));
    assert.ok(after.commandIds.includes('settings'));
    assert.ok(after.shortcutIds.includes('activity-inbox'));
    assert.ok(after.slotDefinitions.some((slot) => slot.slot === 'work_panel' && slot.id === 'plan'));
  } finally { await renderer.close(); }
});
