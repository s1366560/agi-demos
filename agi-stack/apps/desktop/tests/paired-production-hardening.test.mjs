import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  mkdtempSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { deflateSync } from "node:zlib";
import { test } from "node:test";

import {
  createPairedRendererBuildReceipt,
  computeRendererTreeDigest,
  validatePairedRendererBuildReceipt,
} from "../browser-qa/production-renderer-build-attestation.mjs";
import { runPairedProductionGuarded } from "../browser-qa/run-paired-production.mjs";
import { decodePlaywrightPng } from "../contracts/desktop-web-parity/paired-evidence-packet-validator.mjs";

const repositoryRoot = new URL("../../../../", import.meta.url);
const desktopRoot = new URL("../", import.meta.url);
const matrix = JSON.parse(
  readFileSync(
    new URL("browser-qa/paired-production.matrix.v1.json", desktopRoot),
    "utf8",
  ),
);
const webLoginSource = readFileSync(
  new URL("web/src/pages/Login.tsx", repositoryRoot),
  "utf8",
);
const desktopLoginSource = readFileSync(
  new URL("src/features/auth/LoginScreen.tsx", desktopRoot),
  "utf8",
);
const pairedSpecSource = readFileSync(
  new URL("browser-qa/paired-production.spec.mjs", desktopRoot),
  "utf8",
);
const pairedRunnerSource = readFileSync(
  new URL("browser-qa/run-paired-production.mjs", desktopRoot),
  "utf8",
);
const desktopPackage = JSON.parse(
  readFileSync(new URL("package.json", desktopRoot), "utf8"),
);
const makefileSource = readFileSync(
  new URL("agi-stack/Makefile", repositoryRoot),
  "utf8",
);

const PNG_SIGNATURE = Buffer.from([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
]);

function crc32(bytes) {
  let value = 0xffffffff;
  for (const byte of bytes) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      value = (value >>> 1) ^ (value & 1 ? 0xedb88320 : 0);
    }
  }
  return (value ^ 0xffffffff) >>> 0;
}

function pngChunk(type, body) {
  const typeBytes = Buffer.from(type, "ascii");
  const result = Buffer.alloc(12 + body.length);
  result.writeUInt32BE(body.length, 0);
  typeBytes.copy(result, 4);
  body.copy(result, 8);
  result.writeUInt32BE(
    crc32(Buffer.concat([typeBytes, body])),
    result.length - 4,
  );
  return result;
}

function encodeRgbaPng(width, height, pixels, bitDepth = 8) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = bitDepth;
  ihdr[9] = 6;
  const scanlines = [];
  for (let row = 0; row < height; row += 1) {
    scanlines.push(
      Buffer.from([0]),
      pixels.subarray(row * width * 4, (row + 1) * width * 4),
    );
  }
  return Buffer.concat([
    PNG_SIGNATURE,
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", deflateSync(Buffer.concat(scanlines))),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

test("signed-out production roots expose fail-closed parity state and focus probes", () => {
  for (const source of [webLoginSource, desktopLoginSource]) {
    assert.match(source, /data-parity-surface=["']signed-out-entry["']/u);
    assert.match(
      source,
      /data-parity-authentication-state=["']signed_out["']/u,
    );
    assert.match(source, /data-parity-account-state=["']none["']/u);
    assert.match(
      source,
      /data-parity-permission-state=["']public_entry_only["']/u,
    );
    assert.match(source, /data-parity-data-state=["']empty["']/u);
    assert.match(source, /data-parity-target-id=["']email_entry["']/u);
  }

  const scenario = matrix.scenarios.find(
    (candidate) => candidate.id === "signed-out-entry",
  );
  assert.ok(scenario);
  for (const probe of [scenario.web_probe, scenario.desktop_probe]) {
    assert.equal(typeof probe.root_selector, "string");
    assert.deepEqual(probe.state_attributes, {
      authentication_state: "data-parity-authentication-state",
      account_state: "data-parity-account-state",
      permission_state: "data-parity-permission-state",
      data_state: "data-parity-data-state",
    });
    assert.equal(probe.focus_target_attribute, "data-parity-target-id");
  }
  assert.equal(scenario.matched_state.interaction_state, "focused:email_entry");
});

test("Browser observation derives every matched field without receiving expected state", () => {
  assert.match(pairedSpecSource, /observeFinalMatchedState\(page,\s*probe\)/u);
  assert.doesNotMatch(
    pairedSpecSource,
    /observeFinalMatchedState\(page,\s*runtime,\s*matchedState/u,
  );
  assert.match(pairedSpecSource, /document\.documentElement\.lang/u);
  assert.match(pairedSpecSource, /root\.getAttribute\(attributeName\)/u);
  assert.match(pairedSpecSource, /`focused:\$\{focusTargetId\}`/u);
  assert.doesNotMatch(
    pairedSpecSource,
    /interactionState:\s*matchedState\.interaction_state/u,
  );
});

test("qa:paired-production is the single build-and-browser orchestration entry", () => {
  assert.equal(
    desktopPackage.scripts["qa:paired-production"],
    "node browser-qa/run-paired-production.mjs",
  );
  const recipe = makefileSource.match(
    /^desktop-paired-browser-qa:[^\n]*\n((?:\t[^\n]*(?:\n|$))*)/mu,
  )?.[1];
  assert.ok(recipe);
  assert.match(recipe, /\$\(PNPM\) run qa:paired-production/u);
  assert.doesNotMatch(recipe, /run build(?::electron)?/u);

  assert.match(pairedRunnerSource, /git\(\["rev-parse", "HEAD"\]\)/u);
  assert.match(pairedRunnerSource, /git\(\[\s*"status",\s*"--porcelain=v1"/u);
  assert.match(pairedRunnerSource, /git\(\["ls-files", "-v"\]\)/u);
  assert.match(pairedRunnerSource, /\.env/u);
  assert.match(pairedRunnerSource, /randomBytes\(32\)/u);
  assert.match(pairedRunnerSource, /runPinnedPnpmBuild/u);
  assert.match(pairedRunnerSource, /AGISTACK_PAIRED_BUILD_RECEIPT/u);
  assert.match(pairedRunnerSource, /AGISTACK_PAIRED_INVOCATION_NONCE/u);
});

test("renderer receipt binds distinct build intervals, commands, roots, locks, and nonce", (t) => {
  const fixtureRoot = mkdtempSync(join(tmpdir(), "paired-receipt-"));
  t.after(() => rmSync(fixtureRoot, { recursive: true, force: true }));
  const canonicalFixtureRoot = realpathSync(fixtureRoot);
  const webFiles = [
    { path: "index.html", size_bytes: 1, sha256: "2".repeat(64) },
  ];
  const desktopFiles = [
    { path: "index.html", size_bytes: 1, sha256: "4".repeat(64) },
  ];
  const receipt = createPairedRendererBuildReceipt({
    sourceRevision: "a".repeat(40),
    headTree: "b".repeat(40),
    invocationNonce: "c".repeat(64),
    repositoryRoot: canonicalFixtureRoot,
    orchestrationStartedAt: "2026-07-30T00:00:00.000Z",
    orchestrationCompletedAt: "2026-07-30T00:00:04.000Z",
    lockfiles: {
      web: {
        path: "web/pnpm-lock.yaml",
        sha256: "d".repeat(64),
      },
      desktop: {
        path: "agi-stack/apps/desktop/pnpm-lock.yaml",
        sha256: "e".repeat(64),
      },
    },
    builds: {
      web: {
        command: ["corepack", "pnpm", "run", "build"],
        canonical_cwd: join(canonicalFixtureRoot, "web"),
        started_at: "2026-07-30T00:00:00.100Z",
        completed_at: "2026-07-30T00:00:01.900Z",
        exit_code: 0,
      },
      desktop_renderer: {
        command: ["corepack", "pnpm", "run", "build:electron"],
        canonical_cwd: join(canonicalFixtureRoot, "agi-stack/apps/desktop"),
        started_at: "2026-07-30T00:00:02.000Z",
        completed_at: "2026-07-30T00:00:03.900Z",
        exit_code: 0,
      },
    },
    toolchain: {
      node: "v22.0.0",
      web_pnpm: "10.24.0",
      desktop_pnpm: "11.15.1",
      vite_web: "7.3.0",
      electron_vite: "5.0.0",
      electron: "43.2.0",
    },
    outputSnapshots: {
      web: {
        digest_contract: "memstack.renderer-tree.v1",
        tree_digest: computeRendererTreeDigest(webFiles),
        file_count: 1,
        total_bytes: 1,
        files: webFiles,
      },
      desktop_renderer: {
        digest_contract: "memstack.renderer-tree.v1",
        tree_digest: computeRendererTreeDigest(desktopFiles),
        file_count: 1,
        total_bytes: 1,
        files: desktopFiles,
      },
    },
  });

  assert.equal(receipt.record_kind, "paired-production-renderer-build-receipt");
  assert.equal(receipt.invocation_nonce, "c".repeat(64));
  assert.notEqual(
    receipt.builds.web.started_at,
    receipt.builds.web.completed_at,
  );
  assert.deepEqual(receipt.builds.web.command, [
    "corepack",
    "pnpm",
    "run",
    "build",
  ]);
  assert.deepEqual(
    validatePairedRendererBuildReceipt(receipt, {
      expectedSourceRevision: "a".repeat(40),
      expectedInvocationNonce: "c".repeat(64),
      repositoryRoot: canonicalFixtureRoot,
      now: Date.parse("2026-07-30T00:00:05.000Z"),
    }),
    [],
  );
});

test("restricted PNG decoder verifies IHDR and returns exact RGBA pixels", () => {
  const pixels = Buffer.from([10, 20, 30, 255, 50, 60, 70, 255]);
  const png = encodeRgbaPng(2, 1, pixels);
  const decoded = decodePlaywrightPng(png);

  assert.equal(decoded.width, 2);
  assert.equal(decoded.height, 1);
  assert.deepEqual(decoded.rgba, pixels);
  assert.equal(createHash("sha256").update(png).digest("hex").length, 64);

  const malformed = encodeRgbaPng(2, 1, pixels, 16);
  assert.throws(() => decodePlaywrightPng(malformed), /8-bit/u);
});

test("production spec consumes a fresh receipt and the self-derived packet validator", () => {
  assert.doesNotMatch(
    pairedSpecSource,
    /createPairedRendererBuildAttestation/u,
  );
  assert.match(pairedSpecSource, /AGISTACK_PAIRED_BUILD_RECEIPT/u);
  assert.match(pairedSpecSource, /AGISTACK_PAIRED_INVOCATION_NONCE/u);
  assert.match(pairedSpecSource, /validateEvidencePacket\(\{/u);
  assert.match(pairedSpecSource, /repositoryRoot,/u);
  assert.match(pairedSpecSource, /evidenceRunPath/u);
  assert.doesNotMatch(pairedSpecSource, /repositoryBinding,/u);
  assert.doesNotMatch(pairedSpecSource, /rendererBuildRoots:/u);
});

test("direct paired Playwright configuration fails closed without a receipt", () => {
  const environment = { ...process.env };
  delete environment.AGISTACK_PAIRED_BUILD_RECEIPT;
  delete environment.AGISTACK_PAIRED_INVOCATION_NONCE;
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "--eval",
      "await import('./browser-qa/paired-production.playwright.config.mjs')",
    ],
    {
      cwd: new URL("../", import.meta.url),
      env: environment,
      encoding: "utf8",
    },
  );
  assert.notEqual(result.status, 0);
  assert.match(
    result.stderr,
    /requires a fresh orchestration receipt and invocation nonce/u,
  );
});

test("runner failures retain one hashed attempt without fabricating a packet", (t) => {
  const fixtureRoot = mkdtempSync(join(tmpdir(), "paired-runner-attempt-"));
  t.after(() => rmSync(fixtureRoot, { recursive: true, force: true }));
  const phases = [
    "preflight",
    "build_web",
    "build_desktop_renderer",
    "launch_playwright",
  ];

  for (const phase of phases) {
    const resultRoot = join(fixtureRoot, phase);
    assert.throws(
      () =>
        runPairedProductionGuarded({
          sourceRevision: phase === "preflight" ? undefined : "a".repeat(40),
          resultRoot,
          startedAt: "2026-07-30T09:00:00.000Z",
          completedAt: () => "2026-07-30T09:00:01.000Z",
          execute(setPhase) {
            setPhase(phase);
            throw new TypeError(`sensitive ${phase} failure`);
          },
        }),
      new RegExp(`sensitive ${phase} failure`, "u"),
    );

    assert.deepEqual(readdirSync(resultRoot), ["runner-attempt.json"]);
    const attempt = JSON.parse(
      readFileSync(join(resultRoot, "runner-attempt.json"), "utf8"),
    );
    assert.deepEqual(Object.keys(attempt), [
      "schema_version",
      "record_kind",
      "attempt_id",
      "status",
      "phase",
      "failure_domain",
      "source_revision",
      "started_at",
      "completed_at",
      "evidence_packet_created",
      "diagnostics",
    ]);
    assert.equal(attempt.record_kind, "paired-production-runner-attempt");
    assert.equal(attempt.status, "failed");
    assert.equal(attempt.phase, phase);
    assert.equal(attempt.failure_domain, "runner_setup");
    assert.equal(
      attempt.source_revision,
      phase === "preflight" ? null : "a".repeat(40),
    );
    assert.equal(attempt.evidence_packet_created, false);
    assert.deepEqual(Object.keys(attempt.diagnostics[0]), [
      "channel",
      "message_sha256",
    ]);
    assert.match(attempt.diagnostics[0].message_sha256, /^[0-9a-f]{64}$/u);
    assert.equal(
      JSON.stringify(attempt).includes(`sensitive ${phase} failure`),
      false,
    );
    assert.equal(
      readdirSync(resultRoot).some(
        (name) => name.endsWith(".png") || name === "evidence-run.json",
      ),
      false,
    );
  }
});
