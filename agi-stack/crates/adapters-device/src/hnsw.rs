//! HNSW [`VectorIndexPort`] — the on-device **approximate nearest neighbour**
//! tier (`01-portable-core.md` §3, `05-roadmap §4 #3`).
//!
//! [`SqliteVectorIndex`](crate::vector::SqliteVectorIndex) is durable but does a
//! project-scoped **brute-force** cosine scan (and re-parses every stored vector
//! from JSON per query) — fine for small N, but its cost grows linearly. This
//! adapter keeps vectors in memory and serves queries from a real **HNSW** graph
//! ([`instant_distance`]), so query latency stays roughly logarithmic as N grows.
//! The on-device vector bench (`examples/vector_bench.rs`) quantifies the gap at
//! N = 10k.
//!
//! ## Why pure-Rust HNSW, not the `sqlite-vec` C extension
//! `sqlite-vec` is a loadable **C** extension: shipping and `dlopen`-ing it across
//! iOS (no `dlopen` of arbitrary libs), Android and the desktop is exactly the
//! cross-compilation fragility the portable-core invariant exists to avoid.
//! `instant_distance` is pure Rust, so it cross-compiles to every device target
//! unchanged — the same reason the rest of the device tier stays dependency-light.
//! `sqlite-vec` remains a valid *server*-side option behind this same port.
//!
//! ## Mutability model
//! `instant_distance` builds an **immutable** graph from a fixed point set, while
//! [`VectorIndexPort`] is mutable (`upsert`/`remove`). We therefore hold the live
//! vectors as the source of truth and **lazily rebuild** the HNSW graph on the
//! first query after a mutation (a `dirty` flag). That matches the device access
//! pattern — bulk ingest, then many reads — and keeps writes O(1). A production
//! build would use an incremental-insert HNSW or `sqlite-vec`; the port contract
//! is identical either way.

use std::collections::{BTreeMap, HashMap};
use std::sync::Mutex;

use async_trait::async_trait;
use instant_distance::{Builder, HnswMap, Point, Search};

use agistack_core::ports::{CoreError, CoreResult, ScoredId, VectorIndexPort};

/// A point in the index. Distance is **cosine distance** (`1 - cosine`), so
/// nearer points have smaller distance and `score = 1 - distance` recovers the
/// cosine similarity used by every other adapter (parity with the brute-force
/// [`SqliteVectorIndex`](crate::vector::SqliteVectorIndex)).
#[derive(Clone)]
struct VecPoint(Vec<f32>);

impl Point for VecPoint {
    fn distance(&self, other: &Self) -> f32 {
        let (a, b) = (&self.0, &other.0);
        if a.len() != b.len() {
            return 2.0; // maximal cosine distance for a shape mismatch
        }
        let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
        let na: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
        let nb: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
        if na == 0.0 || nb == 0.0 {
            1.0
        } else {
            1.0 - dot / (na * nb)
        }
    }
}

/// Per-project state: the live vectors (source of truth) plus a lazily-built
/// HNSW graph and a `dirty` flag tracking whether the graph is stale.
#[derive(Default)]
struct ProjectState {
    vectors: BTreeMap<String, Vec<f32>>,
    graph: Option<HnswMap<VecPoint, String>>,
    dirty: bool,
}

impl ProjectState {
    /// Rebuild the HNSW graph from the current live vectors if it is stale.
    fn ensure_built(&mut self) {
        if !self.dirty && self.graph.is_some() {
            return;
        }
        if self.vectors.is_empty() {
            self.graph = None;
            self.dirty = false;
            return;
        }
        let mut points = Vec::with_capacity(self.vectors.len());
        let mut ids = Vec::with_capacity(self.vectors.len());
        for (id, vec) in &self.vectors {
            points.push(VecPoint(vec.clone()));
            ids.push(id.clone());
        }
        self.graph = Some(Builder::default().build(points, ids));
        self.dirty = false;
    }
}

/// In-memory, per-project HNSW vector index. Cheap to share behind an `Arc`.
#[derive(Default)]
pub struct HnswVectorIndex {
    projects: Mutex<HashMap<String, ProjectState>>,
}

impl HnswVectorIndex {
    pub fn new() -> Self {
        Self::default()
    }
}

fn to_vec<E: std::fmt::Display>(e: E) -> CoreError {
    CoreError::Vector(e.to_string())
}

#[async_trait]
impl VectorIndexPort for HnswVectorIndex {
    async fn upsert(&self, project_id: &str, id: &str, vector: &[f32]) -> CoreResult<()> {
        let mut projects = self.projects.lock().map_err(to_vec)?;
        let state = projects.entry(project_id.to_string()).or_default();
        state.vectors.insert(id.to_string(), vector.to_vec());
        state.dirty = true;
        Ok(())
    }

    async fn query(&self, project_id: &str, vector: &[f32], k: usize) -> CoreResult<Vec<ScoredId>> {
        if k == 0 {
            return Ok(Vec::new());
        }
        let mut projects = self.projects.lock().map_err(to_vec)?;
        let Some(state) = projects.get_mut(project_id) else {
            return Ok(Vec::new());
        };
        state.ensure_built();
        let Some(graph) = state.graph.as_ref() else {
            return Ok(Vec::new());
        };
        let query = VecPoint(vector.to_vec());
        let mut search = Search::default();
        let scored = graph
            .search(&query, &mut search)
            .take(k)
            .map(|item| ScoredId {
                id: item.value.clone(),
                score: 1.0 - item.distance,
            })
            .collect();
        Ok(scored)
    }

    async fn remove(&self, project_id: &str, id: &str) -> CoreResult<()> {
        let mut projects = self.projects.lock().map_err(to_vec)?;
        if let Some(state) = projects.get_mut(project_id) {
            if state.vectors.remove(id).is_some() {
                state.dirty = true;
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::executor::block_on;

    fn unit(v: Vec<f32>) -> Vec<f32> {
        let n = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        if n == 0.0 {
            v
        } else {
            v.into_iter().map(|x| x / n).collect()
        }
    }

    #[test]
    fn finds_nearest_neighbour_and_scopes_by_project() {
        let idx = HnswVectorIndex::new();
        // Three well-separated unit vectors in project "p1".
        block_on(idx.upsert("p1", "a", &unit(vec![1.0, 0.0, 0.0]))).unwrap();
        block_on(idx.upsert("p1", "b", &unit(vec![0.0, 1.0, 0.0]))).unwrap();
        block_on(idx.upsert("p1", "c", &unit(vec![0.0, 0.0, 1.0]))).unwrap();
        // A different project must not leak in.
        block_on(idx.upsert("p2", "z", &unit(vec![1.0, 0.0, 0.0]))).unwrap();

        let hits = block_on(idx.query("p1", &unit(vec![0.9, 0.1, 0.0]), 2)).unwrap();
        assert_eq!(hits[0].id, "a", "nearest is a");
        assert!(hits[0].score > hits[1].score);
        assert!(hits.iter().all(|h| h.id != "z"), "p2 must not leak: {hits:?}");

        let p2 = block_on(idx.query("p2", &unit(vec![1.0, 0.0, 0.0]), 5)).unwrap();
        assert_eq!(p2.len(), 1);
        assert_eq!(p2[0].id, "z");
    }

    #[test]
    fn rebuilds_after_upsert_and_remove() {
        let idx = HnswVectorIndex::new();
        block_on(idx.upsert("p", "a", &unit(vec![1.0, 0.0, 0.0]))).unwrap();
        block_on(idx.upsert("p", "b", &unit(vec![0.0, 1.0, 0.0]))).unwrap();

        // First query builds the graph and returns b for a y-ward query.
        let before = block_on(idx.query("p", &unit(vec![0.1, 0.9, 0.0]), 1)).unwrap();
        assert_eq!(before[0].id, "b");

        // Remove b -> the next query must rebuild and fall back to a.
        block_on(idx.remove("p", "b")).unwrap();
        let after = block_on(idx.query("p", &unit(vec![0.1, 0.9, 0.0]), 1)).unwrap();
        assert_eq!(after[0].id, "a", "graph rebuilt without b");

        // Update a in place; the new vector must win.
        block_on(idx.upsert("p", "a", &unit(vec![0.0, 1.0, 0.0]))).unwrap();
        let updated = block_on(idx.query("p", &unit(vec![0.0, 1.0, 0.0]), 1)).unwrap();
        assert!((updated[0].score - 1.0).abs() < 1e-3, "a now points at y");
    }

    #[test]
    fn empty_and_k_zero_are_safe() {
        let idx = HnswVectorIndex::new();
        assert!(block_on(idx.query("missing", &[1.0, 0.0], 3)).unwrap().is_empty());
        block_on(idx.upsert("p", "a", &unit(vec![1.0, 0.0]))).unwrap();
        assert!(block_on(idx.query("p", &[1.0, 0.0], 0)).unwrap().is_empty());
    }
}
