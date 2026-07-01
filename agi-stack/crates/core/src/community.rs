//! Louvain **community detection** over the entity graph — the portable,
//! modularity-maximising partition shared by the server (Neo4j) and device
//! (SQLite + `petgraph`) graph adapters.
//!
//! This mirrors the Python fallback path
//! (`src/infrastructure/graph/community/louvain_detector.py`
//! `_detect_with_networkx`), which builds an **undirected weighted** graph
//! (`nx.Graph`, `coalesce(r.weight, 1.0)` edge weights) and runs
//! `networkx.algorithms.community.louvain_communities`, then keeps communities
//! whose size is `>= min_community_size` and names them `Community_{i}`.
//!
//! ## Parity contract differs from [`crate::graph`]
//!
//! Unlike the ranking math in [`crate::graph`] (`rrf_fuse`/`time_decay`/
//! `mmr_rerank`), Louvain is **not byte-for-byte reproducible against Python**:
//! networkx's implementation randomises node visit order (it takes a `seed`, and
//! `LouvainDetector` fixes none), so the exact community ids and their
//! enumeration order vary run to run even in Python. The portable contract here
//! is therefore **structural + quality**, not identity:
//!
//! * every node lands in exactly one community (a true partition),
//! * the partition's **modularity** is a local optimum (no single-node move
//!   raises it) and dominates both the all-singletons and all-in-one baselines
//!   on a modular graph,
//! * communities smaller than `min_community_size` are dropped, and
//! * output is **deterministic for a given input** (fixed node ordering + strict
//!   gain threshold + normalised community ordering), so a Rust-served query is
//!   reproducible even though it is not identical to a specific Python run.
//!
//! Adapter concerns Python layers on top — the `CommunityNode` `uuid` (uuid4),
//! `project_id`/`tenant_id` scoping and LLM `summary` — live in the server/device
//! adapter, not in this pure math (no I/O, no `std::time`, no rng), which is what
//! lets it compile unchanged to `wasm32-unknown-unknown`.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Python `LouvainDetector(min_community_size=2)`.
pub const DEFAULT_MIN_COMMUNITY_SIZE: usize = 2;

/// Strict modularity-gain threshold: a node only moves when the gain exceeds the
/// "stay" baseline by more than this. Requiring strict improvement makes the
/// local-move loop monotone in modularity and therefore guaranteed to terminate,
/// and removes float-noise oscillation between equally-good communities.
const GAIN_EPS: f64 = 1e-12;

/// An undirected weighted edge between two entity ids. Mirrors the
/// `(e1)-[r]->(e2)` rows the Python collects, with `weight = coalesce(r.weight,
/// 1.0)`. Direction is ignored (the Python builds an undirected `nx.Graph`);
/// parallel edges between the same pair are summed.
#[derive(Debug, Clone, PartialEq)]
pub struct CommunityEdge {
    pub source: String,
    pub target: String,
    pub weight: f64,
}

impl CommunityEdge {
    /// Convenience constructor with the Python default weight of `1.0`.
    pub fn unit(source: impl Into<String>, target: impl Into<String>) -> Self {
        Self {
            source: source.into(),
            target: target.into(),
            weight: 1.0,
        }
    }
}

/// A detected community: the member node ids plus the `Community_{i}` name and
/// `member_count` that become a Python `CommunityNode`. Members are sorted for
/// deterministic output.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Community {
    pub name: String,
    pub members: Vec<String>,
    pub member_count: usize,
}

/// Internal integer-indexed undirected weighted graph. Self-loops
/// (`adj[i][i]`) appear only after aggregation and, per the modularity
/// convention, contribute **twice** to the incident node's degree.
struct WGraph {
    n: usize,
    adj: Vec<BTreeMap<usize, f64>>,
    degree: Vec<f64>,
    /// `2m` — the sum of all weighted degrees. Invariant across aggregation
    /// levels (total weight is conserved).
    m2: f64,
}

impl WGraph {
    fn build(n: usize, edges: &[(usize, usize, f64)]) -> Self {
        let mut adj: Vec<BTreeMap<usize, f64>> = vec![BTreeMap::new(); n];
        for &(a, b, w) in edges {
            if a == b {
                *adj[a].entry(a).or_insert(0.0) += w;
            } else {
                *adj[a].entry(b).or_insert(0.0) += w;
                *adj[b].entry(a).or_insert(0.0) += w;
            }
        }
        let mut degree = vec![0.0; n];
        for i in 0..n {
            let mut d = 0.0;
            for (&j, &w) in &adj[i] {
                d += w;
                if j == i {
                    // self-loop counts twice toward degree
                    d += w;
                }
            }
            degree[i] = d;
        }
        let m2 = degree.iter().sum();
        Self { n, adj, degree, m2 }
    }

    /// One Louvain **local-moving** phase. Returns the community label per node
    /// (values in `0..n`, not yet compacted) and whether any node moved.
    fn local_move(&self) -> (Vec<usize>, bool) {
        let mut comm: Vec<usize> = (0..self.n).collect();
        let mut tot: Vec<f64> = self.degree.clone();
        let mut any_move = false;

        loop {
            let mut moved = false;
            for i in 0..self.n {
                let ci = comm[i];
                let di = self.degree[i];
                // Isolate i from its current community.
                tot[ci] -= di;

                // Sum edge weight from i into each neighbouring community.
                let mut w_to: BTreeMap<usize, f64> = BTreeMap::new();
                for (&j, &w) in &self.adj[i] {
                    if j == i {
                        continue;
                    }
                    *w_to.entry(comm[j]).or_insert(0.0) += w;
                }

                // Baseline: stay in ci. Iterate candidates in sorted order and
                // keep the first strict maximum, so ties prefer staying and the
                // scan is deterministic.
                let stay_gain = w_to.get(&ci).copied().unwrap_or(0.0) - tot[ci] * di / self.m2;
                let mut best_c = ci;
                let mut best_gain = stay_gain;
                for (&c, &ki_in) in &w_to {
                    let gain = ki_in - tot[c] * di / self.m2;
                    if gain > best_gain + GAIN_EPS {
                        best_gain = gain;
                        best_c = c;
                    }
                }

                comm[i] = best_c;
                tot[best_c] += di;
                if best_c != ci {
                    moved = true;
                    any_move = true;
                }
            }
            if !moved {
                break;
            }
        }
        (comm, any_move)
    }
}

/// Compact arbitrary community labels to a dense `0..k` range, mapping each node
/// to its new label. Ordering is by ascending original label for determinism.
fn compact(comm: &[usize]) -> (Vec<usize>, usize) {
    let mut relabel: BTreeMap<usize, usize> = BTreeMap::new();
    for &c in comm {
        let next = relabel.len();
        relabel.entry(c).or_insert(next);
    }
    let mapped = comm.iter().map(|c| relabel[c]).collect();
    (mapped, relabel.len())
}

/// Aggregate `graph` by `labels` (dense `0..k`) into a `k`-node graph where each
/// community becomes a super-node; intra-community edges (and prior self-loops)
/// fold into super-node self-loops.
fn aggregate(graph: &WGraph, labels: &[usize], k: usize) -> Vec<(usize, usize, f64)> {
    let mut acc: BTreeMap<(usize, usize), f64> = BTreeMap::new();
    for i in 0..graph.n {
        let cu = labels[i];
        for (&j, &w) in &graph.adj[i] {
            if j < i {
                continue; // undirected: visit each unordered pair once
            }
            if j == i {
                // existing self-loop weight stays a self-loop
                *acc.entry((cu, cu)).or_insert(0.0) += w;
            } else {
                let cv = labels[j];
                let key = if cu <= cv { (cu, cv) } else { (cv, cu) };
                *acc.entry(key).or_insert(0.0) += w;
            }
        }
    }
    let _ = k;
    acc.into_iter().map(|((a, b), w)| (a, b, w)).collect()
}

/// Build a stable node index: ids from `nodes` first (in order), then any
/// endpoint appearing only in `edges` (in encounter order) — mirroring networkx
/// auto-adding edge endpoints not seen as nodes.
fn index_nodes(
    nodes: &[String],
    edges: &[CommunityEdge],
) -> (Vec<String>, BTreeMap<String, usize>) {
    let mut id_of: BTreeMap<String, usize> = BTreeMap::new();
    let mut ids: Vec<String> = Vec::new();
    let push = |id: &str, ids: &mut Vec<String>, id_of: &mut BTreeMap<String, usize>| {
        if !id_of.contains_key(id) {
            id_of.insert(id.to_string(), ids.len());
            ids.push(id.to_string());
        }
    };
    for n in nodes {
        push(n, &mut ids, &mut id_of);
    }
    for e in edges {
        push(&e.source, &mut ids, &mut id_of);
        push(&e.target, &mut ids, &mut id_of);
    }
    (ids, id_of)
}

/// Run Louvain and return the community label per original node (dense `0..k`).
fn partition(n: usize, base_edges: &[(usize, usize, f64)]) -> Vec<usize> {
    let mut current_of_original: Vec<usize> = (0..n).collect();
    let mut graph = WGraph::build(n, base_edges);

    // No edges → every node is its own community; nothing to merge.
    if graph.m2 == 0.0 {
        return current_of_original;
    }

    loop {
        let (comm, moved) = graph.local_move();
        let (labels, k) = compact(&comm);
        // Converged: nothing merged this level.
        if !moved || k == graph.n {
            // Still fold this level's (possibly reordered) labels through.
            for o in current_of_original.iter_mut() {
                *o = labels[*o];
            }
            break;
        }
        for o in current_of_original.iter_mut() {
            *o = labels[*o];
        }
        let agg_edges = aggregate(&graph, &labels, k);
        graph = WGraph::build(k, &agg_edges);
        if k == 1 {
            break;
        }
    }
    current_of_original
}

/// Detect communities in an undirected weighted entity graph via Louvain.
///
/// Communities smaller than `min_community_size` are dropped (Python default
/// `2`; use [`DEFAULT_MIN_COMMUNITY_SIZE`]). Surviving communities are ordered
/// deterministically — by descending size, then ascending first member id — and
/// named `Community_{i}` by that order (Python uses the same `Community_{i}`
/// scheme over networkx's nondeterministic enumeration; we normalise the order).
pub fn detect_communities(
    nodes: &[String],
    edges: &[CommunityEdge],
    min_community_size: usize,
) -> Vec<Community> {
    let (ids, id_of) = index_nodes(nodes, edges);
    let n = ids.len();
    if n < 2 {
        return Vec::new();
    }
    let base_edges: Vec<(usize, usize, f64)> = edges
        .iter()
        .map(|e| (id_of[&e.source], id_of[&e.target], e.weight))
        .collect();

    let labels = partition(n, &base_edges);

    // Group original node indices by community label.
    let mut groups: BTreeMap<usize, Vec<String>> = BTreeMap::new();
    for (i, &c) in labels.iter().enumerate() {
        groups.entry(c).or_default().push(ids[i].clone());
    }

    let mut kept: Vec<Vec<String>> = groups
        .into_values()
        .filter(|m| m.len() >= min_community_size)
        .map(|mut m| {
            m.sort();
            m
        })
        .collect();

    // Deterministic community ordering: larger first, then by first member id.
    kept.sort_by(|a, b| b.len().cmp(&a.len()).then_with(|| a[0].cmp(&b[0])));

    kept.into_iter()
        .enumerate()
        .map(|(i, members)| Community {
            name: format!("Community_{i}"),
            member_count: members.len(),
            members,
        })
        .collect()
}

/// **Modularity** `Q` of a partition of `nodes`/`edges` into `groups` — the
/// standard `Q = Σ_c [ in_c / 2m - (tot_c / 2m)^2 ]`. Nodes not listed in any
/// group are treated as their own singleton community. Exposed for quality
/// assertions and for adapters that want to score a candidate partition.
pub fn modularity(nodes: &[String], edges: &[CommunityEdge], groups: &[Vec<String>]) -> f64 {
    let (ids, id_of) = index_nodes(nodes, edges);
    let n = ids.len();
    let base_edges: Vec<(usize, usize, f64)> = edges
        .iter()
        .map(|e| (id_of[&e.source], id_of[&e.target], e.weight))
        .collect();
    let graph = WGraph::build(n, &base_edges);
    if graph.m2 == 0.0 {
        return 0.0;
    }

    // Assign a community id per node index; ungrouped nodes get unique singletons.
    let mut comm = vec![usize::MAX; n];
    for (c, group) in groups.iter().enumerate() {
        for id in group {
            if let Some(&i) = id_of.get(id) {
                comm[i] = c;
            }
        }
    }
    let mut next = groups.len();
    for c in comm.iter_mut() {
        if *c == usize::MAX {
            *c = next;
            next += 1;
        }
    }

    modularity_indexed(&graph, &comm)
}

/// `Q` for an integer-labelled partition of an already-built graph.
fn modularity_indexed(graph: &WGraph, comm: &[usize]) -> f64 {
    let ncomm = comm.iter().copied().max().map(|m| m + 1).unwrap_or(0);
    let mut in_c = vec![0.0; ncomm];
    let mut tot_c = vec![0.0; ncomm];
    for i in 0..graph.n {
        tot_c[comm[i]] += graph.degree[i];
        for (&j, &w) in &graph.adj[i] {
            if comm[j] == comm[i] {
                // A_ij summed over both i,j in c. Self-loop A_ii = 2*w.
                in_c[comm[i]] += if i == j { 2.0 * w } else { w };
            }
        }
    }
    let m2 = graph.m2;
    let mut q = 0.0;
    for c in 0..ncomm {
        q += in_c[c] / m2 - (tot_c[c] / m2).powi(2);
    }
    q
}

#[cfg(test)]
mod tests {
    use super::*;

    fn e(a: &str, b: &str) -> CommunityEdge {
        CommunityEdge::unit(a, b)
    }

    /// Two triangles {a,b,c} and {x,y,z} joined by one weak bridge c-x.
    fn two_triangles() -> (Vec<String>, Vec<CommunityEdge>) {
        let nodes: Vec<String> = ["a", "b", "c", "x", "y", "z"]
            .iter()
            .map(|s| s.to_string())
            .collect();
        let edges = vec![
            e("a", "b"),
            e("b", "c"),
            e("a", "c"),
            e("x", "y"),
            e("y", "z"),
            e("x", "z"),
            e("c", "x"), // bridge
        ];
        (nodes, edges)
    }

    #[test]
    fn splits_two_triangles() {
        let (nodes, edges) = two_triangles();
        let comms = detect_communities(&nodes, &edges, DEFAULT_MIN_COMMUNITY_SIZE);
        assert_eq!(comms.len(), 2, "expected two communities");
        for c in &comms {
            assert_eq!(c.member_count, 3);
            assert_eq!(c.members.len(), 3);
        }
        // Each triangle stays together.
        let all: Vec<String> = comms.iter().flat_map(|c| c.members.clone()).collect();
        let find = |m: &str| {
            comms
                .iter()
                .find(|c| c.members.iter().any(|x| x == m))
                .unwrap()
        };
        assert_eq!(find("a").members, find("b").members);
        assert_eq!(find("a").members, find("c").members);
        assert_eq!(find("x").members, find("y").members);
        assert_ne!(find("a").name, find("x").name);
        assert_eq!(all.len(), 6);
    }

    #[test]
    fn detected_beats_baselines_on_modularity() {
        let (nodes, edges) = two_triangles();
        let comms = detect_communities(&nodes, &edges, 1);
        let groups: Vec<Vec<String>> = comms.iter().map(|c| c.members.clone()).collect();
        let q_detected = modularity(&nodes, &edges, &groups);

        let singletons: Vec<Vec<String>> = nodes.iter().map(|n| vec![n.clone()]).collect();
        let q_singletons = modularity(&nodes, &edges, &singletons);

        let all_in_one = vec![nodes.clone()];
        let q_all = modularity(&nodes, &edges, &all_in_one);

        assert!(
            q_detected > q_singletons,
            "detected {q_detected} !> singletons {q_singletons}"
        );
        assert!(
            q_detected > q_all,
            "detected {q_detected} !> all-in-one {q_all}"
        );
        assert!(q_detected > 0.0);
    }

    #[test]
    fn local_optimum_no_single_move_improves() {
        let (nodes, edges) = two_triangles();
        let comms = detect_communities(&nodes, &edges, 1);
        let groups: Vec<Vec<String>> = comms.iter().map(|c| c.members.clone()).collect();
        let base_q = modularity(&nodes, &edges, &groups);

        // Try moving every node into every other community; none should beat base.
        for src in 0..groups.len() {
            for member_idx in 0..groups[src].len() {
                for dst in 0..groups.len() {
                    if dst == src {
                        continue;
                    }
                    let mut g = groups.clone();
                    let node = g[src].remove(member_idx);
                    g[dst].push(node);
                    let q = modularity(&nodes, &edges, &g);
                    assert!(
                        q <= base_q + 1e-9,
                        "move improved modularity: {q} > {base_q} (not a local optimum)"
                    );
                }
            }
        }
    }

    #[test]
    fn min_community_size_filters_small() {
        // A triangle plus a detached pair {p,q}. With min size 3 the pair drops.
        let nodes: Vec<String> = ["a", "b", "c", "p", "q"]
            .iter()
            .map(|s| s.to_string())
            .collect();
        let edges = vec![e("a", "b"), e("b", "c"), e("a", "c"), e("p", "q")];

        let all = detect_communities(&nodes, &edges, 2);
        assert_eq!(all.len(), 2, "min size 2 keeps triangle + pair");

        let big = detect_communities(&nodes, &edges, 3);
        assert_eq!(big.len(), 1, "min size 3 drops the pair");
        assert_eq!(big[0].member_count, 3);
    }

    #[test]
    fn deterministic_across_runs() {
        let (nodes, edges) = two_triangles();
        let a = detect_communities(&nodes, &edges, 1);
        let b = detect_communities(&nodes, &edges, 1);
        let c = detect_communities(&nodes, &edges, 1);
        assert_eq!(a, b);
        assert_eq!(b, c);
    }

    #[test]
    fn respects_edge_weights() {
        // Square a-b-c-d-a. Heavy a-b and c-d, light b-c and d-a: two pairs.
        let nodes: Vec<String> = ["a", "b", "c", "d"].iter().map(|s| s.to_string()).collect();
        let edges = vec![
            CommunityEdge {
                source: "a".into(),
                target: "b".into(),
                weight: 10.0,
            },
            CommunityEdge {
                source: "c".into(),
                target: "d".into(),
                weight: 10.0,
            },
            CommunityEdge {
                source: "b".into(),
                target: "c".into(),
                weight: 1.0,
            },
            CommunityEdge {
                source: "d".into(),
                target: "a".into(),
                weight: 1.0,
            },
        ];
        let comms = detect_communities(&nodes, &edges, 2);
        assert_eq!(comms.len(), 2);
        let find = |m: &str| {
            comms
                .iter()
                .find(|c| c.members.iter().any(|x| x == m))
                .unwrap()
        };
        assert_eq!(
            find("a").members,
            find("b").members,
            "heavy edge keeps a,b together"
        );
        assert_eq!(
            find("c").members,
            find("d").members,
            "heavy edge keeps c,d together"
        );
        assert_ne!(find("a").name, find("c").name);
    }

    #[test]
    fn too_few_nodes_returns_empty() {
        assert!(detect_communities(&[], &[], 2).is_empty());
        assert!(detect_communities(&["solo".into()], &[], 2).is_empty());
    }

    #[test]
    fn nodes_without_edges_yield_no_community() {
        // Three isolated nodes, no edges: m2 == 0, all singletons, filtered out.
        let nodes: Vec<String> = ["a", "b", "c"].iter().map(|s| s.to_string()).collect();
        let comms = detect_communities(&nodes, &[], 2);
        assert!(comms.is_empty());
        // Modularity of any partition on an edgeless graph is 0.
        assert_eq!(modularity(&nodes, &[], &[nodes.clone()]), 0.0);
    }

    #[test]
    fn edge_only_endpoints_are_indexed() {
        // Node list empty but edges reference ids: networkx auto-adds endpoints.
        let edges = vec![e("a", "b"), e("b", "c"), e("a", "c")];
        let comms = detect_communities(&[], &edges, 2);
        assert_eq!(comms.len(), 1);
        assert_eq!(comms[0].member_count, 3);
        assert_eq!(comms[0].members, vec!["a", "b", "c"]);
    }

    #[test]
    fn parallel_edges_are_summed() {
        // Two a-b rows sum to weight 2.0; modularity uses the combined weight.
        let nodes: Vec<String> = ["a", "b"].iter().map(|s| s.to_string()).collect();
        let edges = vec![e("a", "b"), e("a", "b")];
        // Single community of the pair.
        let q = modularity(&nodes, &edges, &[nodes.clone()]);
        // in_c = 2*2.0 = 4, tot = 4, m2 = 4 => 4/4 - (4/4)^2 = 1 - 1 = 0.
        assert!((q - 0.0).abs() < 1e-12);
        let comms = detect_communities(&nodes, &edges, 2);
        assert_eq!(comms.len(), 1);
        assert_eq!(comms[0].member_count, 2);
    }
}
