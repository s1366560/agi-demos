import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function source(relativePath) {
  return readFileSync(new URL(`../${relativePath}`, import.meta.url), "utf8");
}

test("desktop renderer owns a protocol-v2 generation host through the public fetch seam", () => {
  const hook = source("src/plugins/useDesktopPluginGenerationV2.ts");
  const app = source("src/App.tsx");

  assert.match(hook, /RendererPluginRuntimeV2\(\s*["']desktop-renderer["']/u);
  assert.match(hook, /desktopRendererHostDefinitionV2/u);
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
});

test("every desktop build path resolves the shared protocol-v2 runtime package", () => {
  const tsconfig = source("tsconfig.json");
  const vite = source("vite.config.ts");
  const electronVite = source("electron.vite.config.ts");

  for (const content of [tsconfig, vite, electronVite]) {
    assert.match(content, /@agistack\/plugin-runtime/u);
  }
});
