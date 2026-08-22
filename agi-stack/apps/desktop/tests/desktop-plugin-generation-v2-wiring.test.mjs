import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function source(relativePath) {
  return readFileSync(new URL(`../${relativePath}`, import.meta.url), "utf8");
}

test("desktop renderer owns a protocol-v2 generation host through the public fetch seam", () => {
  const hook = source("src/plugins/useDesktopPluginGenerationV2.ts");
  const app = source("src/App.tsx");
  const main = source("src/main.tsx");

  assert.match(hook, /RendererPluginRuntimeV2\(\s*["']desktop-renderer["']/u);
  assert.match(hook, /createDesktopRendererDefinitionsV2/u);
  assert.match(hook, /validateDesktopRendererContributionsV2/u);
  assert.match(hook, /RendererGenerationLeaseStoreV2/u);
  assert.match(hook, /useLayoutEffect/u);
  assert.match(hook, /desktopRendererLeaseStoreV2\.commit\(snapshot\)/u);
  assert.match(hook, /return snapshot\.generation/u);
  assert.match(hook, /desktopApiFetch\(/u);
  assert.doesNotMatch(hook, /DesktopApiClient/u);
  assert.match(hook, /runtime\.bootstrap\(bootstrapProfileV2\)/u);
  const bootstrapIndex = hook.search(
    /runtime\.bootstrap\(bootstrapProfileV2\)/u,
  );
  const remoteFetchIndex = hook.search(
    /fetchDesktopPluginDistributionV2\(\s*config,\s*controller\.signal/u,
  );
  assert.ok(
    bootstrapIndex >= 0 && remoteFetchIndex > bootstrapIndex,
    "local bootstrap must activate before the first remote request",
  );
  assert.match(
    app,
    /useDesktopPluginGenerationV2\(config, identityAuthenticated\)/u,
  );
  assert.match(app, /resolveDesktopRendererAuthorityStateV2/u);
  assert.match(app, /projectDesktopRouteRegistryV2/u);
  assert.match(app, /projectDesktopNavigationRegistryV2/u);
  assert.match(app, /DesktopRendererAuthorityContextV2\.Provider/u);
  assert.doesNotMatch(app, /CANONICAL_DESKTOP_ROUTE_IDS\.map/u);
  assert.match(main, /activateDesktopPluginGenerationRootV2\(\)/u);
  assert.match(main, /root\.unmount\(\)/u);
  assert.match(main, /deactivateDesktopPluginGenerationRootV2\(\)/u);
});

test("desktop UI slot consumers use the pinned V2 authority without V1 fallback", () => {
  const hook = source("src/features/settings/usePlatformPluginUiSlots.ts");
  const conversationSlots = source("src/features/chat/PlatformPluginConversationSlots.tsx");

  assert.match(hook, /useDesktopRendererAuthorityV2/u);
  assert.doesNotMatch(hook, /DesktopApiClient|getPlatformPluginSnapshot/u);
  assert.doesNotMatch(hook, /builtinUiFallbackSnapshot|BUILTIN_UI_SLOT_DEFINITIONS/u);
  assert.doesNotMatch(conversationSlots, /usePlatformPluginUiSlots\(\{ active, config \}\)/u);
});

test("every desktop build path resolves the shared protocol-v2 runtime package", () => {
  const tsconfig = source("tsconfig.json");
  const vite = source("vite.config.ts");
  const electronVite = source("electron.vite.config.ts");

  for (const content of [tsconfig, vite, electronVite]) {
    assert.match(content, /@agistack\/plugin-runtime/u);
  }
});
