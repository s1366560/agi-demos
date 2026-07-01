// Node smoke test for the WASM web binding: proves the *same* portable core runs
// in a JS runtime (core-as-guest) with a real round-trip — ingest, then keyword
// and semantic search — using the wasm-pack `nodejs` package. Run:
//   wasm-pack build crates/bindings-wasm --release --target nodejs --out-dir pkg
//   node crates/bindings-wasm/smoke.cjs
const assert = require("node:assert");
const { AgistackCore } = require("./pkg/agistack_bindings_wasm.js");

async function main() {
  const core = new AgistackCore();
  const project = "p1";

  // Ingest two episodes; each returns the created Memory as JSON.
  const m1 = JSON.parse(
    await core.ingest(project, "u1", "Local-first apps store data on device using sqlite")
  );
  assert.ok(m1.id, "ingest returns a memory with an id");
  assert.ok(Array.isArray(m1.embedding) && m1.embedding.length === 32, "32-dim embedding");
  await core.ingest(project, "u1", "A recipe for garlic bread with butter and herbs");

  // Keyword search hits the sqlite memory, misses the unrelated term.
  const hits = JSON.parse(await core.search(project, "sqlite", 10));
  assert.strictEqual(hits.length, 1, "keyword search finds exactly one match");
  const miss = JSON.parse(await core.search(project, "postgres", 10));
  assert.strictEqual(miss.length, 0, "keyword search misses unrelated term");

  // Semantic search over the in-memory vector index returns ranked results.
  const sem = JSON.parse(await core.semanticSearch(project, "on-device storage", 2));
  assert.ok(sem.length >= 1, "semantic search returns at least one hit");

  console.log("SMOKE_OK", JSON.stringify({ keyword: hits.length, semantic: sem.length }));
}

main().catch((e) => {
  console.error("SMOKE_FAIL", e);
  process.exit(1);
});
