import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const {
  shouldPreserveConversationSelectionDuringSidecarRecovery,
} = require(
  "/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceTreeModel.js",
);
const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");

test("only the exact sidecar recovery refresh preserves conversation selection", () => {
  assert.equal(
    shouldPreserveConversationSelectionDuringSidecarRecovery(8, 8),
    true,
  );
  assert.equal(
    shouldPreserveConversationSelectionDuringSidecarRecovery(8, 9),
    false,
  );
  assert.equal(
    shouldPreserveConversationSelectionDuringSidecarRecovery(null, 8),
    false,
  );
});

test("invalid refresh generations fail closed", () => {
  for (const value of [0, -1, 1.5, Number.NaN]) {
    assert.equal(
      shouldPreserveConversationSelectionDuringSidecarRecovery(value, value),
      false,
    );
  }
});

test("Desktop binds selection preservation to one sidecar recovery generation", () => {
  assert.match(
    appSource,
    /sidecarRecoveryRefreshGenerationRef = useRef<number \| null>\(null\)/u,
  );
  assert.match(
    appSource,
    /shouldPreserveConversationSelectionDuringSidecarRecovery\([\s\S]*sidecarRecoveryRefreshGenerationRef\.current,[\s\S]*runtimeRefreshRequestRef\.current/u,
  );
  assert.match(
    appSource,
    /onSidecarRecovered\(\(\) => \{[\s\S]*recoveryRefreshGeneration[\s\S]*refreshRuntime\(configRef\.current\)\.finally/u,
  );
});
