// Node smoke test for the WASM build of the portable core.
// Proves the SAME core that runs the native server also runs in JS via wasm-bindgen.
//   run: node harness/node-smoke.cjs
const { MemstackCore } = require('../crates/bindings-wasm/pkg/memstack_bindings_wasm.js');

(async () => {
  const core = new MemstackCore();

  const memJson = await core.ingest(
    'p1',
    'u1',
    'Rust core compiles to wasm and runs in the browser offline',
  );
  const mem = JSON.parse(memJson);
  console.log('[ingest] id=%s tags=%j embeddingDim=%d', mem.id, mem.tags, mem.embedding.length);

  const hits = JSON.parse(await core.search('p1', 'browser', 10));
  console.log('[search "browser"] hits=%d title=%j', hits.length, hits[0] && hits[0].title);

  const miss = JSON.parse(await core.search('p1', 'zzz-nope', 10));
  console.log('[search "zzz-nope"] hits=%d', miss.length);

  const ok = mem.project_id === 'p1' && mem.embedding.length === 8 && hits.length === 1 && miss.length === 0;
  console.log(ok ? 'WASM SMOKE: PASS' : 'WASM SMOKE: FAIL');
  process.exit(ok ? 0 : 1);
})();
