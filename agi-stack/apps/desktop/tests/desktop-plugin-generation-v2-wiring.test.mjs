import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function source(relativePath) {
  return readFileSync(new URL(`../${relativePath}`, import.meta.url), "utf8");
}

test("desktop renderer owns a protocol-v2 generation host through the public fetch seam", () => {
  const hook = source("src/plugins/useDesktopPluginGenerationV2.ts");
  const host = source("src/plugins/DesktopRendererGenerationHostV2.tsx");
  const lifecycle = source("../../packages/plugin-runtime/src/rendererLifecycle.ts");
  const app = source("src/App.tsx");
  const artifactCatalog = source("src/plugins/desktopRendererArtifactCatalogV2.ts");
  const authority = source("src/plugins/desktopRendererAuthorityStateV2.ts");
  const main = source("src/main.tsx");

  assert.match(hook, /RendererPluginRuntimeV2\(\s*["']desktop-renderer["']/u);
  assert.match(hook, /createDesktopRendererDefinitionsV2/u);
  assert.match(hook, /validateDesktopRendererContributionsV2/u);
  assert.match(hook, /RendererGenerationLeaseStoreV2/u);
  assert.match(hook, /RendererGenerationStatusStoreV2/u);
  assert.match(hook, /projectRendererPluginGenerationStateV2/u);
  assert.match(hook, /useLayoutEffect/u);
  assert.match(hook, /desktopRendererLeaseStoreV2\.commit\(snapshot\)/u);
  assert.match(hook, /return state/u);
  assert.match(hook, /if \(!enabled\) \{\s*scheduleClose\(\);\s*return;\s*\}/u);
  assert.doesNotMatch(hook, /if \(!enabled\) return \(\) => scheduleClose\(\)/u);
  assert.match(hook, /desktopApiFetch\(/u);
  assert.doesNotMatch(hook, /DesktopApiClient/u);
  assert.match(hook, /startRendererGenerationPollingV2/u);
  assert.match(hook, /runtime\.bootstrap\(bootstrapProfileV2\)/u);
  assert.match(hook, /source:\s*\(signal\) => fetchDesktopPluginDistributionV2\(config, signal\)/u);
  const bootstrapIndex = lifecycle.search(/await options\.bootstrap\(\)/u);
  const remoteFetchIndex = lifecycle.search(/await options\.source\(signal\)/u);
  assert.ok(
    bootstrapIndex >= 0 && remoteFetchIndex > bootstrapIndex,
    "local bootstrap must activate before the first remote request",
  );
  assert.match(host, /useDesktopPluginGenerationV2\(\s*config,\s*enabled\s*,?\s*\)/u);
  assert.match(host, /resolveDesktopRendererAuthorityStateV2/u);
  assert.match(host, /projectDesktopRouteRegistryV2/u);
  assert.match(host, /projectDesktopNavigationRegistryV2/u);
  assert.match(host, /DesktopRendererGenerationContextV2/u);
  assert.match(host, /DesktopRendererAuthorityContextV2/u);
  assert.match(host, /children/u);
  assert.match(app, /useDesktopRendererGenerationHostV2\(/u);
  assert.match(app, /DesktopRendererGenerationProviderV2/u);
  assert.match(app, /desktopRendererGenerationV2\.meta\.digest/u);
  assert.match(app, /desktopRendererGenerationV2\.meta\.status/u);
  assert.match(app, /desktopRendererGenerationV2\.meta\.target/u);
  assert.doesNotMatch(app, /useDesktopPluginGenerationV2/u);
  assert.doesNotMatch(app, /resolveDesktopRendererAuthorityStateV2/u);
  assert.doesNotMatch(app, /projectDesktopRouteRegistryV2/u);
  assert.doesNotMatch(app, /projectDesktopNavigationRegistryV2/u);
  assert.doesNotMatch(app, /DesktopRendererAuthorityContextV2/u);
  assert.doesNotMatch(app, /createAppRouteRegistry/u);
  assert.doesNotMatch(app, /CANONICAL_DESKTOP_ROUTE_IDS\.map/u);
  assert.match(artifactCatalog, /createRegistry:\s*\(/u);
  assert.match(authority, /artifact\.createRegistry\(refs\)/u);
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
