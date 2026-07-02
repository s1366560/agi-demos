//! Hybrid graph/vector search **ranking math** — the deterministic fusion,
//! temporal-decay and diversity-rerank shared by the server (Neo4j) and device
//! (SQLite + `petgraph`) graph adapters.
//!
//! These are pure functions: no I/O, no `std::time` (ages are passed in as epoch
//! millis), no tokio. That is what lets them compile unchanged to
//! `wasm32-unknown-unknown` and, more importantly, be **byte-for-byte parity
//! checked** against the Python hybrid search
//! (`src/infrastructure/graph/search/hybrid_search.py`,
//! `src/infrastructure/memory/{temporal_decay,mmr}.py`). Every constant below is
//! lifted verbatim from that Python so a Rust-served graph query ranks results
//! identically (the F3 parity contract, `docs/architecture/04-spike-evidence.md`).
//!
//! Pipeline (mirrors `HybridSearchService`): `rrf_fuse` → `time_decay` →
//! `mmr_rerank`. [`hybrid_rank`] composes the three in order.

use serde::{Deserialize, Serialize};

/// RRF constant. Python `DEFAULT_RRF_K = 60`.
pub const RRF_K: f64 = 60.0;
/// Weight on the vector-search ranking. Python `DEFAULT_VECTOR_WEIGHT = 0.6`.
pub const VECTOR_WEIGHT: f64 = 0.6;
/// Weight on the keyword-search ranking. Python `DEFAULT_KEYWORD_WEIGHT = 0.4`.
pub const KEYWORD_WEIGHT: f64 = 0.4;
/// MMR relevance/diversity balance. Python `mmr_lambda = 0.7`.
pub const MMR_LAMBDA: f64 = 0.7;
/// Temporal-decay half-life. Python `temporal_half_life_days = 30.0`.
pub const HALF_LIFE_DAYS: f64 = 30.0;
/// Milliseconds per day (`86_400_000`) — bridges the core's epoch-millis clock to
/// the Python day-based decay.
pub const MS_PER_DAY: f64 = 86_400_000.0;

/// An id paired with a full-precision (`f64`) rank score. Distinct from
/// [`crate::ports::ScoredId`] (which is `f32`, matching embedding precision):
/// fusion arithmetic mirrors Python `float`, so we keep `f64` end to end to stay
/// parity-exact.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RankedId {
    pub id: String,
    pub score: f64,
}

/// A candidate for [`mmr_rerank`] / [`hybrid_rank`]: an id, the text used for
/// Jaccard diversity, its post-fusion relevance score, and the age (ms) used for
/// temporal decay.
#[derive(Debug, Clone, PartialEq)]
pub struct Candidate {
    pub id: String,
    pub content: String,
    pub score: f64,
    pub age_ms: i64,
}

/// **Reciprocal Rank Fusion** with per-list weights — the exact
/// `HybridSearchService._rrf_fusion`.
///
/// `score(id) = Σ_list weight_list · (1 / (k + rank))`, where `rank` is 1-based
/// within each already-ranked list and an id summed across both lists keeps the
/// total. Results are sorted by score descending; ties break by `id` ascending
/// for determinism (Python relies on dict-insertion order + a stable sort, which
/// is not reproducible cross-language — an explicit id tiebreak is the portable
/// equivalent).
pub fn rrf_fuse(
    vector_ranked: &[String],
    keyword_ranked: &[String],
    vector_weight: f64,
    keyword_weight: f64,
    k: f64,
) -> Vec<RankedId> {
    // Preserve first-seen order (vector list first, then keyword) so the id
    // tiebreak is the only nondeterminism we introduce, and it is total.
    let mut order: Vec<String> = Vec::new();
    let mut scores: std::collections::HashMap<String, f64> = std::collections::HashMap::new();

    let mut accumulate = |list: &[String], weight: f64| {
        for (i, id) in list.iter().enumerate() {
            let rank = (i + 1) as f64;
            let contribution = weight * (1.0 / (k + rank));
            let entry = scores.entry(id.clone());
            if let std::collections::hash_map::Entry::Vacant(_) = entry {
                order.push(id.clone());
            }
            *scores.entry(id.clone()).or_insert(0.0) += contribution;
        }
    };
    accumulate(vector_ranked, vector_weight);
    accumulate(keyword_ranked, keyword_weight);

    let mut fused: Vec<RankedId> = order
        .into_iter()
        .map(|id| {
            let score = scores[&id];
            RankedId { id, score }
        })
        .collect();
    fused.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.id.cmp(&b.id))
    });
    fused
}

/// Exponential **temporal decay** — the exact `apply_temporal_decay`.
///
/// `decayed = score · 0.5^(age_days / half_life_days)` for a positive age, and
/// `score` unchanged for a non-positive age (future/now). Identity note: Python
/// computes `exp(-(ln2/half_life_days)·age_days)`, which is algebraically
/// `0.5^(age/half_life)`; we use the latter form (same value, no separate `ln`).
pub fn time_decay(score: f64, age_ms: i64, half_life_days: f64) -> f64 {
    if age_ms <= 0 || half_life_days <= 0.0 {
        return score;
    }
    let age_days = age_ms as f64 / MS_PER_DAY;
    score * 0.5_f64.powf(age_days / half_life_days)
}

/// Lowercase alphanumeric+underscore tokenizer — Python `tokenize`
/// (`re.findall(r"[a-z0-9_]+", text.lower())`).
pub fn tokenize(text: &str) -> std::collections::BTreeSet<String> {
    let lower = text.to_lowercase();
    let mut tokens = std::collections::BTreeSet::new();
    let mut cur = String::new();
    for ch in lower.chars() {
        if ch.is_ascii_alphanumeric() || ch == '_' {
            cur.push(ch);
        } else if !cur.is_empty() {
            tokens.insert(std::mem::take(&mut cur));
        }
    }
    if !cur.is_empty() {
        tokens.insert(cur);
    }
    tokens
}

/// **Jaccard similarity** on token sets — Python `text_similarity` /
/// `jaccard_similarity`: `|A ∩ B| / |A ∪ B|`, and `0` when either side is empty.
pub fn jaccard(a: &str, b: &str) -> f64 {
    let sa = tokenize(a);
    let sb = tokenize(b);
    if sa.is_empty() || sb.is_empty() {
        return 0.0;
    }
    let inter = sa.intersection(&sb).count();
    let union = sa.union(&sb).count();
    if union == 0 {
        0.0
    } else {
        inter as f64 / union as f64
    }
}

/// **Maximal Marginal Relevance** rerank — the exact `mmr_rerank`.
///
/// Relevance is min-max normalized across the input; selection is greedy on
/// `λ·relevance − (1−λ)·max_jaccard_to_selected` (first pick uses `max_sim = 0`).
/// The returned score is rank-based (`1 − rank/len`) exactly like Python, so it is
/// an ordering signal, not the raw MMR value. Inputs of length ≤ 1 are returned
/// unchanged (as ids), matching the Python early return.
pub fn mmr_rerank(items: &[Candidate], lambda: f64) -> Vec<RankedId> {
    if items.len() <= 1 {
        return items
            .iter()
            .map(|c| RankedId {
                id: c.id.clone(),
                score: c.score,
            })
            .collect();
    }

    let min_score = items.iter().map(|c| c.score).fold(f64::INFINITY, f64::min);
    let max_score = items
        .iter()
        .map(|c| c.score)
        .fold(f64::NEG_INFINITY, f64::max);
    let range = if max_score > min_score {
        max_score - min_score
    } else {
        1.0
    };

    // (original index, normalized relevance)
    let mut remaining: Vec<usize> = (0..items.len()).collect();
    let relevance: Vec<f64> = items
        .iter()
        .map(|c| (c.score - min_score) / range)
        .collect();

    let mut selected: Vec<usize> = Vec::with_capacity(items.len());
    while !remaining.is_empty() {
        let mut best_pos: Option<usize> = None;
        let mut best_mmr = f64::NEG_INFINITY;
        for (pos, &idx) in remaining.iter().enumerate() {
            let max_sim = if selected.is_empty() {
                0.0
            } else {
                selected
                    .iter()
                    .map(|&s| jaccard(&items[idx].content, &items[s].content))
                    .fold(0.0_f64, f64::max)
            };
            let mmr = lambda * relevance[idx] - (1.0 - lambda) * max_sim;
            if mmr > best_mmr {
                best_mmr = mmr;
                best_pos = Some(pos);
            }
        }
        // `best_pos` is always Some while `remaining` is non-empty.
        let pos = best_pos.unwrap_or(0);
        selected.push(remaining.remove(pos));
    }

    let len = selected.len() as f64;
    selected
        .into_iter()
        .enumerate()
        .map(|(rank, idx)| RankedId {
            id: items[idx].id.clone(),
            score: 1.0 - (rank as f64 / len),
        })
        .collect()
}

/// Full hybrid ranking pipeline: **RRF fuse → temporal decay → MMR rerank**,
/// mirroring `HybridSearchService`'s post-processing order. `candidates` supplies
/// content/age for every id that could appear in either ranking; ids absent from
/// `candidates` are dropped (they cannot be decayed or diversified). Uses the
/// Python default constants.
pub fn hybrid_rank(
    vector_ranked: &[String],
    keyword_ranked: &[String],
    candidates: &[Candidate],
    now_ms: i64,
) -> Vec<RankedId> {
    let fused = rrf_fuse(
        vector_ranked,
        keyword_ranked,
        VECTOR_WEIGHT,
        KEYWORD_WEIGHT,
        RRF_K,
    );

    // Decay each fused score by the candidate's age, then re-sort (Python
    // re-sorts after decay before MMR).
    let by_id: std::collections::HashMap<&str, &Candidate> =
        candidates.iter().map(|c| (c.id.as_str(), c)).collect();
    let mut decayed: Vec<Candidate> = Vec::new();
    for r in &fused {
        if let Some(c) = by_id.get(r.id.as_str()) {
            let age = (now_ms - c.age_ms).max(0);
            decayed.push(Candidate {
                id: r.id.clone(),
                content: c.content.clone(),
                score: time_decay(r.score, age, HALF_LIFE_DAYS),
                age_ms: c.age_ms,
            });
        }
    }
    decayed.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.id.cmp(&b.id))
    });

    mmr_rerank(&decayed, MMR_LAMBDA)
}

#[cfg(test)]
mod tests {
    use super::*;

    // --- RRF: constants + exact formula ---------------------------------------

    #[test]
    fn rrf_constants_match_python() {
        assert_eq!(RRF_K, 60.0);
        assert_eq!(VECTOR_WEIGHT, 0.6);
        assert_eq!(KEYWORD_WEIGHT, 0.4);
        assert_eq!(MMR_LAMBDA, 0.7);
        assert_eq!(HALF_LIFE_DAYS, 30.0);
    }

    #[test]
    fn rrf_single_list_uses_weight_over_k_plus_rank() {
        // one vector list, id "a" at rank 1 → 0.6 * 1/(60+1)
        let out = rrf_fuse(&["a".into()], &[], VECTOR_WEIGHT, KEYWORD_WEIGHT, RRF_K);
        assert_eq!(out.len(), 1);
        let expected = 0.6 * (1.0 / 61.0);
        assert!((out[0].score - expected).abs() < 1e-12, "{:?}", out[0]);
    }

    #[test]
    fn rrf_sums_across_lists_for_shared_id() {
        // "a": rank1 vector + rank2 keyword
        let out = rrf_fuse(
            &["a".into(), "b".into()],
            &["b".into(), "a".into()],
            VECTOR_WEIGHT,
            KEYWORD_WEIGHT,
            RRF_K,
        );
        let a = out.iter().find(|r| r.id == "a").unwrap();
        let b = out.iter().find(|r| r.id == "b").unwrap();
        let a_expected = 0.6 * (1.0 / 61.0) + 0.4 * (1.0 / 62.0);
        let b_expected = 0.6 * (1.0 / 62.0) + 0.4 * (1.0 / 61.0);
        assert!((a.score - a_expected).abs() < 1e-12);
        assert!((b.score - b_expected).abs() < 1e-12);
        // a has more vector weight (higher-weighted list at rank1) → ranks first
        assert_eq!(out[0].id, "a");
    }

    #[test]
    fn rrf_ties_break_by_id_ascending() {
        // Symmetric single-list positions → identical scores → id tiebreak.
        let out = rrf_fuse(&["z".into(), "a".into()], &[], 1.0, 0.0, RRF_K);
        // z at rank1 (1/61) > a at rank2 (1/62); scores differ, so order is z,a.
        assert_eq!(out[0].id, "z");
        // Now make them equal by putting each first in its own list.
        let out2 = rrf_fuse(&["z".into()], &["a".into()], 0.5, 0.5, RRF_K);
        assert!((out2[0].score - out2[1].score).abs() < 1e-12);
        assert_eq!(out2[0].id, "a"); // tie → ascending id
    }

    // --- Temporal decay -------------------------------------------------------

    #[test]
    fn decay_at_one_half_life_halves_score() {
        let age = (HALF_LIFE_DAYS * MS_PER_DAY) as i64; // exactly 30 days
        let out = time_decay(1.0, age, HALF_LIFE_DAYS);
        assert!((out - 0.5).abs() < 1e-9, "{out}");
    }

    #[test]
    fn decay_zero_or_negative_age_is_identity() {
        assert_eq!(time_decay(0.8, 0, HALF_LIFE_DAYS), 0.8);
        assert_eq!(time_decay(0.8, -5_000, HALF_LIFE_DAYS), 0.8);
    }

    #[test]
    fn decay_two_half_lives_quarters_score() {
        let age = (2.0 * HALF_LIFE_DAYS * MS_PER_DAY) as i64;
        let out = time_decay(1.0, age, HALF_LIFE_DAYS);
        assert!((out - 0.25).abs() < 1e-9, "{out}");
    }

    // --- Jaccard / tokenize ---------------------------------------------------

    #[test]
    fn tokenize_matches_python_regex_semantics() {
        let t = tokenize("Hello, World_9! foo-bar");
        let got: Vec<&str> = t.iter().map(|s| s.as_str()).collect();
        // lowercased, split on non [a-z0-9_]; "foo-bar" → "foo","bar"
        assert_eq!(got, vec!["bar", "foo", "hello", "world_9"]);
    }

    #[test]
    fn jaccard_basic_and_empty() {
        assert_eq!(jaccard("a b c", "a b c"), 1.0);
        assert_eq!(jaccard("", "a"), 0.0);
        // {a,b} vs {b,c} → 1/3
        assert!((jaccard("a b", "b c") - (1.0 / 3.0)).abs() < 1e-12);
    }

    // --- MMR ------------------------------------------------------------------

    #[test]
    fn mmr_single_item_returned_unchanged() {
        let items = vec![Candidate {
            id: "x".into(),
            content: "hello".into(),
            score: 0.9,
            age_ms: 0,
        }];
        let out = mmr_rerank(&items, MMR_LAMBDA);
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].id, "x");
        assert_eq!(out[0].score, 0.9);
    }

    #[test]
    fn mmr_prefers_diverse_second_pick() {
        // a = top relevance; a2 = near-duplicate of a; b = distinct topic.
        // a2 and b share the SAME relevance (0.6) so MMR's diversity term is the
        // tiebreaker: with λ=0.7 the redundant a2 is penalized by its Jaccard
        // overlap with the already-selected a, so the diverse b is picked second.
        let items = vec![
            Candidate {
                id: "a".into(),
                content: "quantum physics lecture".into(),
                score: 1.0,
                age_ms: 0,
            },
            Candidate {
                id: "a2".into(),
                content: "quantum physics lecture notes".into(),
                score: 0.6,
                age_ms: 0,
            },
            Candidate {
                id: "b".into(),
                content: "italian pasta recipe".into(),
                score: 0.6,
                age_ms: 0,
            },
        ];
        let out = mmr_rerank(&items, MMR_LAMBDA);
        assert_eq!(out[0].id, "a");
        assert_eq!(
            out[1].id, "b",
            "diverse pick should beat the near-duplicate"
        );
        assert_eq!(out[2].id, "a2");
        // rank-based scores: 1, 1-1/3, 1-2/3
        assert!((out[0].score - 1.0).abs() < 1e-12);
        assert!((out[1].score - (1.0 - 1.0 / 3.0)).abs() < 1e-12);
    }

    #[test]
    fn mmr_high_relevance_duplicate_still_wins_when_lambda_favors_relevance() {
        // Contrast with the diversity case: when the near-duplicate a2 keeps a
        // much higher relevance than the diverse b, λ=0.7 lets relevance dominate
        // the diversity penalty, so a2 is (correctly) picked before b.
        let items = vec![
            Candidate {
                id: "a".into(),
                content: "quantum physics lecture".into(),
                score: 1.0,
                age_ms: 0,
            },
            Candidate {
                id: "a2".into(),
                content: "quantum physics lecture notes".into(),
                score: 0.95,
                age_ms: 0,
            },
            Candidate {
                id: "b".into(),
                content: "italian pasta recipe".into(),
                score: 0.5,
                age_ms: 0,
            },
        ];
        let out = mmr_rerank(&items, MMR_LAMBDA);
        assert_eq!(out[0].id, "a");
        assert_eq!(out[1].id, "a2");
        assert_eq!(out[2].id, "b");
    }

    // --- Full pipeline --------------------------------------------------------

    #[test]
    fn hybrid_rank_composes_fuse_decay_mmr() {
        let vector = vec!["a".to_string(), "b".to_string()];
        let keyword = vec!["b".to_string(), "c".to_string()];
        let now = 100 * MS_PER_DAY as i64;
        let candidates = vec![
            Candidate {
                id: "a".into(),
                content: "alpha topic".into(),
                score: 0.0,
                age_ms: now, // age 0 → no decay
            },
            Candidate {
                id: "b".into(),
                content: "beta topic".into(),
                score: 0.0,
                age_ms: now - (30 * MS_PER_DAY as i64), // one half-life old
            },
            Candidate {
                id: "c".into(),
                content: "gamma subject".into(),
                score: 0.0,
                age_ms: now,
            },
        ];
        let out = hybrid_rank(&vector, &keyword, &candidates, now);
        // All three ids survive (each appears in a ranking and has a candidate).
        let ids: std::collections::BTreeSet<&str> = out.iter().map(|r| r.id.as_str()).collect();
        assert_eq!(ids, ["a", "b", "c"].into_iter().collect());
        // Output is a valid MMR ordering: strictly descending rank scores.
        for w in out.windows(2) {
            assert!(w[0].score >= w[1].score);
        }
    }

    #[test]
    fn hybrid_rank_drops_ids_without_candidates() {
        // "ghost" is ranked but has no candidate → dropped before decay/MMR.
        let out = hybrid_rank(
            &["ghost".into(), "real".into()],
            &[],
            &[Candidate {
                id: "real".into(),
                content: "present".into(),
                score: 0.0,
                age_ms: 0,
            }],
            0,
        );
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].id, "real");
    }
}
