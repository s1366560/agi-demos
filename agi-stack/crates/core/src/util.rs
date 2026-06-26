//! Tiny dependency-free helpers (FNV-1a hash + id generation).
//!
//! Avoids pulling `uuid`/`rand`, which need extra feature wiring for wasm and
//! would add weight against the size budgets in `05-roadmap.md` §3.

/// FNV-1a, 64-bit. Deterministic and allocation-free — good enough for stable
/// content-derived ids and the toy embedding in `adapters-mem`.
pub fn fnv1a(input: &str) -> u64 {
    let mut hash: u64 = 0xcbf29ce4_84222325;
    for byte in input.bytes() {
        hash ^= byte as u64;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash
}

/// Content-addressed memory id. Stable for a given seed so re-ingesting the same
/// episode in the same round is idempotent.
pub fn new_memory_id(seed: &str) -> String {
    format!("mem_{:016x}", fnv1a(seed))
}
