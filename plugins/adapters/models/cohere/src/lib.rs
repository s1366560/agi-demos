//! Adapt request options and response positions for the native Cohere rerank protocol.
use serde::{Deserialize, Serialize};
use serde_json::json;

const MAX_CHUNKS_PER_DOCUMENT: u32 = 1;

#[derive(Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
enum Phase {
    Request {
        candidate_count: usize,
        limit: usize,
    },
    Response {
        candidate_count: usize,
        results: Vec<CohereScore>,
    },
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CohereScore {
    index: usize,
    relevance_score: f64,
}

#[derive(Serialize)]
struct Match {
    index: usize,
    score: f64,
}

fn adapt(input: &[u8]) -> Option<Vec<u8>> {
    let response = match serde_json::from_slice::<Phase>(input).ok()? {
        Phase::Request {
            candidate_count,
            limit,
        } => {
            if candidate_count == 0 || limit == 0 {
                return None;
            }
            json!({"top_n": candidate_count.min(limit),"max_chunks_per_doc": MAX_CHUNKS_PER_DOCUMENT})
        }
        Phase::Response {
            candidate_count,
            results,
        } => {
            let mut matches = Vec::with_capacity(results.len());
            for entry in results {
                if entry.index >= candidate_count || !(0.0..=1.0).contains(&entry.relevance_score) {
                    return None;
                }
                matches.push(Match {
                    index: entry.index,
                    score: entry.relevance_score,
                });
            }
            matches.sort_by(|a, b| b.score.total_cmp(&a.score));
            json!({"matches":matches})
        }
    };
    serde_json::to_vec(&response).ok()
}

#[cfg(target_arch = "wasm32")]
#[no_mangle]
pub extern "C" fn invoke(length: u32) -> u32 {
    if !(2..=65_536).contains(&length) {
        return 0;
    }
    let mut input = Vec::with_capacity(length as usize);
    // The structured ABI always supplies an object. Rust cannot borrow address zero.
    input.push(b'{');
    // SAFETY: build.rs reserves page zero for the host's initialized request.
    let tail = unsafe {
        std::slice::from_raw_parts(std::ptr::without_provenance::<u8>(1), length as usize - 1)
    };
    input.extend_from_slice(tail);
    let Some(output) = adapt(&input) else {
        return 0;
    };
    if output.len() > 65_536 {
        return 0;
    }
    // SAFETY: page one is the ABI response buffer, disjoint from the guest-owned output.
    unsafe {
        std::ptr::copy_nonoverlapping(
            output.as_ptr(),
            std::ptr::without_provenance_mut::<u8>(65_536),
            output.len(),
        )
    };
    output.len() as u32
}

#[cfg(test)]
mod tests {
    use super::adapt;
    use serde_json::{json, Value};
    #[test]
    fn projects_only_positions_and_scores_in_relevance_order() {
        let input = json!({"operation":"response", "candidate_count":2,"results":[{"index":0,"relevance_score":0.2},{"index":1,"relevance_score":0.9}]});
        let output = adapt(input.to_string().as_bytes()).unwrap();
        let data: Value = serde_json::from_slice(&output).unwrap();
        assert_eq!(
            data,
            json!({"matches":[{"index":1,"score":0.9},{"index":0,"score":0.2}]})
        );
    }
}
