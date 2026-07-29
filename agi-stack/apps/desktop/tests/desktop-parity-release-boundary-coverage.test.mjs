import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const repositoryRoot = new URL("../../../../", import.meta.url);
const contractRoot = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);

test("signed update and release boundary binds every required production authority", () => {
  const fragment = JSON.parse(
    readFileSync(
      new URL(
        "parity-capability-definitions.25-native-boundaries.v2.json",
        contractRoot,
      ),
      "utf8",
    ),
  );
  const metadata = JSON.parse(
    readFileSync(
      new URL("parity-capability-definitions.metadata.v2.json", contractRoot),
      "utf8",
    ),
  );
  const releaseBoundary = fragment.capabilities.find(
    (capability) => capability.id === "signed-update-and-release-boundary",
  );
  const requiredProductionAuthorities = [
    ".github/workflows/desktop-release.yml",
    "agi-stack/Cargo.lock",
    "agi-stack/Cargo.toml",
    "agi-stack/apps/desktop/sidecar/Cargo.toml",
    "agi-stack/apps/desktop/electron/main/updater.ts",
    "agi-stack/apps/desktop/electron/main/updatePolicy.ts",
    "agi-stack/apps/desktop/electron/main/automaticUpdateLoop.ts",
    "agi-stack/apps/desktop/scripts/verify-release-artifacts.mjs",
    "agi-stack/apps/desktop/scripts/release-artifact-contract.mjs",
    "agi-stack/apps/desktop/scripts/release-package-verification.mjs",
    "agi-stack/apps/desktop/scripts/stage-sidecar.mjs",
    "agi-stack/apps/desktop/scripts/sign-local-macos.mjs",
    "agi-stack/apps/desktop/package.json",
    "agi-stack/apps/desktop/pnpm-lock.yaml",
    "agi-stack/apps/desktop/electron-builder.yml",
    "agi-stack/apps/desktop/electron-builder.local.yml",
    "agi-stack/apps/desktop/electron/resources/entitlements.mac.plist",
    "agi-stack/apps/desktop/electron/resources/entitlements.mac.inherit.plist",
    "agi-stack/apps/desktop/electron/resources/entitlements.mac.local.plist",
  ];

  assert.ok(releaseBoundary);
  assert.equal(releaseBoundary.kind, "native_only");
  assert.equal(releaseBoundary.native_authority, "electron");
  assert.equal(releaseBoundary.native_status, "partial");
  assert.equal(
    releaseBoundary.native_reason_code,
    "production_install_update_rollback_evidence_missing",
  );
  assert.deepEqual(
    requiredProductionAuthorities.filter(
      (entry) => !releaseBoundary.native_entries.includes(entry),
    ),
    [],
    "signed update and release boundary is missing a required production authority",
  );
  assert.equal(
    new Set(releaseBoundary.native_entries).size,
    releaseBoundary.native_entries.length,
    "release production authorities must not be duplicated",
  );

  for (const entry of releaseBoundary.native_entries) {
    assert.equal(
      existsSync(new URL(entry, repositoryRoot)),
      true,
      `release production authority does not exist: ${entry}`,
    );
    assert.equal(
      /(^|\/)(?:tests?|docs?|qa)(?:\/|$)/u.test(entry),
      false,
      `test, documentation, or QA evidence is not production authority: ${entry}`,
    );
  }

  assert.deepEqual(metadata.production_entry_integrity, {
    hash_algorithm: "sha256",
    verification_scope: "source_content_integrity_only",
    execution_evidence: false,
  });
});
