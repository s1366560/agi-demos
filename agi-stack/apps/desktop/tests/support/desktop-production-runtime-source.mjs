import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/** Read both production assembly sites and prove the private singleton uses the factory. */
export function desktopProductionRuntimeSource() {
  const hook = readFileSync(new URL('../../src/plugins/useDesktopPluginGenerationV2.ts', import.meta.url), 'utf8');
  const factory = readFileSync(new URL('../../src/plugins/desktopProductionRendererRuntimeV2.ts', import.meta.url), 'utf8');
  assert.match(hook, /const desktopRendererRuntimeV2 = createDesktopProductionRendererRuntimeV2\(\);/u);
  assert.match(factory, /export function createDesktopProductionRendererRuntimeV2/u);
  assert.match(factory, /validateDesktopRendererContributionsV2/u);
  return `${hook}\n${factory}`;
}
