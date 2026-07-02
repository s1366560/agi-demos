//! On-device vector-search benchmark: **brute-force SQLite** vs **HNSW ANN**.
//!
//! Fills the `端上向量检索 (N=10k) P50` scorecard row (`04-spike-evidence §2`,
//! `05-roadmap §3`). Builds N normalized vectors, indexes them in both adapters,
//! runs Q queries against each, and reports P50/P95/P99 latency plus the ANN's
//! recall@k against the exact brute-force result.
//!
//! Run (release matters — the brute-force JSON scan is the realistic baseline):
//! ```text
//! cargo run -p agistack-adapters-device --example vector_bench --release
//! ```

use std::time::Instant;

use agistack_adapters_device::{HnswVectorIndex, SqliteVectorIndex};
use agistack_core::ports::{ScoredId, VectorIndexPort};
use futures::executor::block_on;

const N: usize = 10_000;
const DIM: usize = 256;
const QUERIES: usize = 200;
const K: usize = 10;

/// Tiny deterministic PRNG (xorshift64*) — no rand dependency, fully reproducible.
struct Rng(u64);
impl Rng {
    fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    fn unit_f32(&mut self) -> f32 {
        // Map to [-1, 1).
        (self.next_u64() as f64 / u64::MAX as f64) as f32 * 2.0 - 1.0
    }
}

fn random_unit_vector(rng: &mut Rng) -> Vec<f32> {
    let mut v: Vec<f32> = (0..DIM).map(|_| rng.unit_f32()).collect();
    let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm > 0.0 {
        for x in &mut v {
            *x /= norm;
        }
    }
    v
}

fn percentile(sorted_us: &[u128], p: f64) -> u128 {
    if sorted_us.is_empty() {
        return 0;
    }
    let idx = ((sorted_us.len() as f64 - 1.0) * p).round() as usize;
    sorted_us[idx]
}

fn ids(hits: &[ScoredId]) -> Vec<String> {
    hits.iter().map(|h| h.id.clone()).collect()
}

fn main() {
    println!("# On-device vector search: brute-force vs HNSW");
    println!("N={N} vectors, dim={DIM}, {QUERIES} queries, k={K}\n");

    let mut rng = Rng(0x9E37_79B9_7F4A_7C15);
    let corpus: Vec<Vec<f32>> = (0..N).map(|_| random_unit_vector(&mut rng)).collect();
    let queries: Vec<Vec<f32>> = (0..QUERIES).map(|_| random_unit_vector(&mut rng)).collect();

    // --- Build both indexes ---
    let brute = SqliteVectorIndex::in_memory().expect("sqlite index");
    let ann = HnswVectorIndex::new();

    let t = Instant::now();
    for (i, v) in corpus.iter().enumerate() {
        block_on(brute.upsert("p1", &format!("m{i}"), v)).unwrap();
    }
    let brute_build_ms = t.elapsed().as_secs_f64() * 1e3;

    let t = Instant::now();
    for (i, v) in corpus.iter().enumerate() {
        block_on(ann.upsert("p1", &format!("m{i}"), v)).unwrap();
    }
    // Force the lazy HNSW build with one warm-up query (excluded from timings).
    let _ = block_on(ann.query("p1", &queries[0], K)).unwrap();
    let ann_build_ms = t.elapsed().as_secs_f64() * 1e3;

    // --- Query both, collecting per-query latency + recall ---
    let mut brute_us = Vec::with_capacity(QUERIES);
    let mut ann_us = Vec::with_capacity(QUERIES);
    let mut recall_hits = 0usize;
    let mut recall_total = 0usize;

    for q in &queries {
        let t = Instant::now();
        let b = block_on(brute.query("p1", q, K)).unwrap();
        brute_us.push(t.elapsed().as_micros());

        let t = Instant::now();
        let a = block_on(ann.query("p1", q, K)).unwrap();
        ann_us.push(t.elapsed().as_micros());

        // recall@k: fraction of the exact top-k the ANN also returned.
        let exact = ids(&b);
        for id in ids(&a) {
            if exact.contains(&id) {
                recall_hits += 1;
            }
        }
        recall_total += exact.len();
    }

    brute_us.sort_unstable();
    ann_us.sort_unstable();

    let recall = if recall_total == 0 {
        0.0
    } else {
        recall_hits as f64 / recall_total as f64
    };

    println!("Build time:   brute-force {brute_build_ms:8.1} ms   HNSW {ann_build_ms:8.1} ms");
    println!();
    println!("| Index       |   P50 |   P95 |   P99 |  <=20ms |");
    println!("|-------------|-------|-------|-------|---------|");
    for (name, lat) in [("brute-force", &brute_us), ("HNSW", &ann_us)] {
        let p50 = percentile(lat, 0.50) as f64 / 1e3;
        let p95 = percentile(lat, 0.95) as f64 / 1e3;
        let p99 = percentile(lat, 0.99) as f64 / 1e3;
        let ok = if p50 <= 20.0 { "  yes  " } else { "  no   " };
        println!("| {name:<11} | {p50:5.2} | {p95:5.2} | {p99:5.2} | {ok} |");
    }
    println!("\n(latencies in ms)");
    println!("HNSW recall@{K} vs exact: {:.1}%", recall * 100.0);

    let ann_p50 = percentile(&ann_us, 0.50) as f64 / 1e3;
    let brute_p50 = percentile(&brute_us, 0.50) as f64 / 1e3;
    if brute_p50 > 0.0 {
        println!(
            "HNSW speedup at P50:     {:.1}x",
            brute_p50 / ann_p50.max(1e-6)
        );
    }
}
