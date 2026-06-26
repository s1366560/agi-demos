//! Tiny dependency-free helpers (FNV-1a hash + id generation).
//! Avoids pulling `uuid`/`rand`, which need extra feature wiring for wasm.

pub fn fnv1a(input: &str) -> u64 {
    let mut hash: u64 = 0xcbf29ce4_84222325;
    for byte in input.bytes() {
        hash ^= byte as u64;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash
}

pub fn new_memory_id(seed: &str) -> String {
    format!("mem_{:016x}", fnv1a(seed))
}
