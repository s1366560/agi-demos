import { execFileSync, spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  createPairedRendererBuildReceipt,
  serializePairedRendererBuildReceipt,
  snapshotRendererTree,
} from "./production-renderer-build-attestation.mjs";

const SCRIPT_PATH = fileURLToPath(import.meta.url);
const DESKTOP_ROOT = realpathSync(resolve(dirname(SCRIPT_PATH), ".."));
const REPOSITORY_ROOT = realpathSync(resolve(DESKTOP_ROOT, "../../.."));
const WEB_ROOT = resolve(REPOSITORY_ROOT, "web");
const WEB_OUTPUT_ROOT = resolve(WEB_ROOT, "dist");
const DESKTOP_OUTPUT_ROOT = resolve(DESKTOP_ROOT, "out/renderer");
const PAIRED_RESULT_ROOT = resolve(DESKTOP_ROOT, "browser-qa/paired-results");
const REVISION_PATTERN = /^[0-9a-f]{40}$/u;
const PACKAGE_MANAGER_PATTERN =
  /^pnpm@([^+]+)\+sha512\.[0-9a-f]{128}$/u;
const RUNNER_PHASES = new Set([
  "preflight",
  "prepare_outputs",
  "build_web",
  "build_desktop_renderer",
  "write_renderer_receipt",
  "launch_playwright",
]);

function sha256File(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function git(args, { encoding = "utf8", allowFailure = false } = {}) {
  try {
    return execFileSync("git", args, {
      cwd: REPOSITORY_ROOT,
      encoding,
      stdio: encoding === "utf8" ? ["ignore", "pipe", "pipe"] : undefined,
    });
  } catch (error) {
    if (allowFailure) return null;
    throw error;
  }
}

function packageManagerVersion(packageRoot) {
  const packageJson = JSON.parse(
    readFileSync(resolve(packageRoot, "package.json"), "utf8"),
  );
  const declaration = packageJson.packageManager;
  const match =
    typeof declaration === "string"
      ? PACKAGE_MANAGER_PATTERN.exec(declaration)
      : null;
  if (match === null) {
    throw new Error(
      `${packageRoot} must use an integrity-qualified pnpm packageManager declaration`,
    );
  }
  return match[1];
}

function installedPackageVersion(packageRoot, packageName) {
  return JSON.parse(
    readFileSync(
      resolve(packageRoot, "node_modules", packageName, "package.json"),
      "utf8",
    ),
  ).version;
}

function assertNoIndexFlags() {
  const flagged = git(["ls-files", "-v"])
    .split(/\r?\n/u)
    .filter(Boolean)
    .filter((line) => line.startsWith("S ") || /^[a-z] /u.test(line));
  if (flagged.length > 0) {
    throw new Error(
      `paired production refuses ${flagged.length} assume-unchanged or skip-worktree entries`,
    );
  }
}

function assertNoUntrackedViteEnvironmentFiles() {
  for (const root of [WEB_ROOT, DESKTOP_ROOT]) {
    for (const name of readdirSync(root)) {
      if (name !== ".env" && !name.startsWith(".env.")) continue;
      const absolutePath = resolve(root, name);
      const relativePath = absolutePath.slice(REPOSITORY_ROOT.length + 1);
      const tracked = git(["ls-files", "--error-unmatch", "--", relativePath], {
        allowFailure: true,
      });
      if (tracked === null) {
        throw new Error(
          `paired production refuses untracked or ignored Vite environment file ${relativePath}`,
        );
      }
    }
  }
}

export function inspectPairedBuildPreconditions(expectedRevision) {
  if (
    typeof expectedRevision !== "string" ||
    !REVISION_PATTERN.test(expectedRevision)
  ) {
    throw new Error(
      "AGISTACK_PAIRED_SOURCE_REVISION must be a 40-character Git revision",
    );
  }
  const headRevision = git(["rev-parse", "HEAD"]).trim();
  if (headRevision !== expectedRevision) {
    throw new Error(
      `paired production expected ${expectedRevision} but HEAD is ${headRevision}`,
    );
  }
  const worktreeStatus = git([
    "status",
    "--porcelain=v1",
    "--untracked-files=all",
  ]).trim();
  if (worktreeStatus.length > 0) {
    throw new Error(
      "paired production requires a clean tracked and untracked worktree",
    );
  }
  assertNoIndexFlags();
  assertNoUntrackedViteEnvironmentFiles();
  return {
    headRevision,
    headTree: git(["rev-parse", "HEAD^{tree}"]).trim(),
  };
}

export function runPinnedPnpmBuild(packageRoot, scriptName) {
  const declaredVersion = packageManagerVersion(packageRoot);
  const activeVersion = execFileSync("corepack", ["pnpm", "--version"], {
    cwd: packageRoot,
    encoding: "utf8",
  }).trim();
  if (activeVersion !== declaredVersion) {
    throw new Error(
      `active pnpm ${activeVersion} does not match ${declaredVersion} in ${packageRoot}`,
    );
  }
  const startedAt = new Date().toISOString();
  const command = ["corepack", "pnpm", "run", scriptName];
  const result = spawnSync(command[0], command.slice(1), {
    cwd: packageRoot,
    env: process.env,
    stdio: "inherit",
  });
  const completedAt = new Date().toISOString();
  const exitCode = result.status ?? 1;
  const build = {
    command,
    canonical_cwd: realpathSync(packageRoot),
    started_at: startedAt,
    completed_at: completedAt,
    exit_code: exitCode,
  };
  if (result.error) throw result.error;
  if (exitCode !== 0) {
    throw new Error(`${command.join(" ")} failed with exit code ${exitCode}`);
  }
  if (completedAt === startedAt) {
    throw new Error(
      `${scriptName} did not produce a measurable build interval`,
    );
  }
  return { build, pnpmVersion: activeVersion };
}

function runPlaywright(receiptPath, invocationNonce, sourceRevision) {
  const command = [
    "corepack",
    "pnpm",
    "exec",
    "playwright",
    "test",
    "--config",
    "browser-qa/paired-production.playwright.config.mjs",
  ];
  const result = spawnSync(command[0], command.slice(1), {
    cwd: DESKTOP_ROOT,
    env: {
      ...process.env,
      AGISTACK_PAIRED_SOURCE_REVISION: sourceRevision,
      AGISTACK_PAIRED_BUILD_RECEIPT: receiptPath,
      AGISTACK_PAIRED_INVOCATION_NONCE: invocationNonce,
    },
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`paired Playwright failed with exit code ${result.status}`);
  }
}

export function runPairedProductionGuarded({
  sourceRevision,
  resultRoot,
  startedAt = new Date().toISOString(),
  completedAt = () => new Date().toISOString(),
  execute,
}) {
  if (typeof resultRoot !== "string" || resultRoot.length === 0) {
    throw new Error("resultRoot is required");
  }
  if (typeof execute !== "function") {
    throw new Error("execute must be a function");
  }
  rmSync(resultRoot, { recursive: true, force: true });
  mkdirSync(resultRoot, { recursive: true, mode: 0o700 });
  chmodSync(resultRoot, 0o700);

  let phase = "preflight";
  const setPhase = (nextPhase) => {
    if (!RUNNER_PHASES.has(nextPhase)) {
      throw new Error(`unsupported paired runner phase ${nextPhase}`);
    }
    phase = nextPhase;
  };
  try {
    return execute(setPhase);
  } catch (error) {
    const completedTimestamp = completedAt();
    const message = error instanceof Error ? error.message : String(error);
    const channel =
      error instanceof TypeError
        ? "TypeError"
        : error instanceof Error
          ? "Error"
          : "NonError";
    const normalizedRevision =
      typeof sourceRevision === "string" &&
      REVISION_PATTERN.test(sourceRevision)
        ? sourceRevision
        : null;
    const attempt = {
      schema_version: "1.0.0",
      record_kind: "paired-production-runner-attempt",
      attempt_id: `paired-production-runner-${sha256(
        `${startedAt}:${normalizedRevision ?? "unbound"}`,
      ).slice(0, 12)}`,
      status: "failed",
      phase,
      failure_domain: "runner_setup",
      source_revision: normalizedRevision,
      started_at: startedAt,
      completed_at: completedTimestamp,
      evidence_packet_created: false,
      diagnostics: [
        {
          channel,
          message_sha256: sha256(message),
        },
      ],
    };
    const temporaryAttemptPath = resolve(
      resultRoot,
      `.runner-attempt-${process.pid}.tmp`,
    );
    const attemptPath = resolve(resultRoot, "runner-attempt.json");
    writeFileSync(
      temporaryAttemptPath,
      Buffer.from(`${JSON.stringify(attempt, null, 2)}\n`),
      { mode: 0o600 },
    );
    renameSync(temporaryAttemptPath, attemptPath);
    throw error;
  }
}

export function runPairedProduction() {
  const sourceRevision = process.env.AGISTACK_PAIRED_SOURCE_REVISION;
  return runPairedProductionGuarded({
    sourceRevision,
    resultRoot: PAIRED_RESULT_ROOT,
    execute(setPhase) {
      setPhase("preflight");
      const { headRevision, headTree } =
        inspectPairedBuildPreconditions(sourceRevision);
      const orchestrationStartedAt = new Date().toISOString();
      const invocationNonce = randomBytes(32).toString("hex");
      const temporaryRoot = mkdtempSync(
        join(tmpdir(), "memstack-paired-production-"),
      );
      chmodSync(temporaryRoot, 0o700);

      try {
        setPhase("prepare_outputs");
        for (const taskOwnedPath of [WEB_OUTPUT_ROOT, DESKTOP_OUTPUT_ROOT]) {
          rmSync(taskOwnedPath, { recursive: true, force: true });
        }
        setPhase("build_web");
        const webResult = runPinnedPnpmBuild(WEB_ROOT, "build");
        setPhase("build_desktop_renderer");
        const desktopResult = runPinnedPnpmBuild(
          DESKTOP_ROOT,
          "build:electron",
        );
        const orchestrationCompletedAt = new Date().toISOString();
        const receipt = createPairedRendererBuildReceipt({
          sourceRevision: headRevision,
          headTree,
          invocationNonce,
          repositoryRoot: REPOSITORY_ROOT,
          orchestrationStartedAt,
          orchestrationCompletedAt,
          lockfiles: {
            web: {
              path: "web/pnpm-lock.yaml",
              sha256: sha256File(resolve(WEB_ROOT, "pnpm-lock.yaml")),
            },
            desktop: {
              path: "agi-stack/apps/desktop/pnpm-lock.yaml",
              sha256: sha256File(resolve(DESKTOP_ROOT, "pnpm-lock.yaml")),
            },
          },
          builds: {
            web: webResult.build,
            desktop_renderer: desktopResult.build,
          },
          toolchain: {
            node: process.version,
            web_pnpm: webResult.pnpmVersion,
            desktop_pnpm: desktopResult.pnpmVersion,
            vite_web: installedPackageVersion(WEB_ROOT, "vite"),
            electron_vite: installedPackageVersion(
              DESKTOP_ROOT,
              "electron-vite",
            ),
            electron: installedPackageVersion(DESKTOP_ROOT, "electron"),
          },
          outputSnapshots: {
            web: snapshotRendererTree(WEB_OUTPUT_ROOT),
            desktop_renderer: snapshotRendererTree(DESKTOP_OUTPUT_ROOT),
          },
        });
        setPhase("write_renderer_receipt");
        const receiptPath = resolve(
          temporaryRoot,
          "renderer-build-receipt.json",
        );
        writeFileSync(
          receiptPath,
          serializePairedRendererBuildReceipt(receipt),
          { mode: 0o600 },
        );
        setPhase("launch_playwright");
        runPlaywright(receiptPath, invocationNonce, sourceRevision);
      } finally {
        rmSync(temporaryRoot, { recursive: true, force: true });
      }
    },
  });
}

if (process.argv[1] && realpathSync(process.argv[1]) === SCRIPT_PATH) {
  runPairedProduction();
}
