import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { devNull, tmpdir } from "node:os";
import { resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const fixture = fileURLToPath(
  new URL(
    "./desktop-parity-production-entry-integrity.test.mjs",
    import.meta.url,
  ),
);

for (const variant of ["repository-and-index", "configuration-overrides"]) {
  test(`Desktop production entry binding isolates inherited Git ${variant}`, () => {
    const sandbox = mkdtempSync(resolve(tmpdir(), "memstack-git-isolation-"));
    // This independent safety boundary must never inherit the caller's repository.
    const env = Object.fromEntries(
      Object.entries(process.env).filter(
        ([key]) => !key.toUpperCase().startsWith("GIT_"),
      ),
    );
    delete env.NODE_TEST_CONTEXT;
    Object.assign(env, {
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_CONFIG_GLOBAL: devNull,
      GIT_CONFIG_SYSTEM: devNull,
      TMPDIR: sandbox,
      TMP: sandbox,
      TEMP: sandbox,
    });
    const outer = resolve(sandbox, "outer");
    const git = (...args) => execFileSync("git", args, { cwd: outer, env });
    try {
      mkdirSync(outer);
      git("init", "-q");
      git("config", "user.name", "Dummy Owner");
      git("config", "user.email", "dummy@example.invalid");
      writeFileSync(resolve(outer, "sentinel.txt"), "baseline\n");
      git("add", ".");
      git("commit", "-qm", "test: dummy baseline");
      writeFileSync(resolve(outer, "sentinel.txt"), "staged dummy change\n");
      git("add", "sentinel.txt");
      const snapshot = () => ({
        config: readFileSync(resolve(outer, ".git/config")),
        head: git("rev-parse", "HEAD"),
        index: readFileSync(resolve(outer, ".git/index")),
        staged: git("diff", "--cached", "--binary", "--no-ext-diff"),
        stagedBlob: git("show", ":sentinel.txt"),
      });
      const before = snapshot();
      const poison =
        variant === "repository-and-index"
          ? {
              GIT_DIR: resolve(outer, ".git"),
              GIT_COMMON_DIR: resolve(outer, ".git"),
              GIT_WORK_TREE: outer,
              GIT_INDEX_FILE: resolve(outer, ".git/index"),
              GIT_OBJECT_DIRECTORY: resolve(outer, ".git/objects"),
            }
          : {
              GIT_CONFIG: resolve(outer, ".git/config"),
              GIT_CONFIG_GLOBAL: resolve(outer, ".git/config"),
              GIT_CONFIG_SYSTEM: resolve(outer, ".git/config"),
              GIT_CONFIG_COUNT: "1",
              GIT_CONFIG_KEY_0: "core.worktree",
              GIT_CONFIG_VALUE_0: outer,
              GIT_CONFIG_PARAMETERS: `'core.worktree'='${outer}'`,
            };
      const result = spawnSync(
        process.execPath,
        [
          "--test",
          "--test-name-pattern=production entries bind audited revision|declarations bind their audited|production entry binding rejects audited, HEAD",
          fixture,
        ],
        {
          cwd: sandbox,
          env: { ...env, ...poison },
          encoding: "utf8",
          timeout: 60_000,
        },
      );
      assert.deepEqual(
        snapshot(),
        before,
        "external repository bytes must remain unchanged",
      );
      assert.equal(result.error, undefined);
      assert.equal(result.status, 0, result.stdout + result.stderr);
      assert.match(result.stdout, /# pass 3\b/u);
    } finally {
      rmSync(sandbox, { recursive: true, force: true });
    }
  });
}
