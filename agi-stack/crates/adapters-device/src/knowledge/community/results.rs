//! Audited result persistence. Provider calls never execute under these locks.

use agistack_core::knowledge::community::{build::*, result::*, worker::*};
use serde::de::DeserializeOwned;

use super::{
    builds::{read::read_build, transact},
    *,
};

mod audit;
mod read;
mod schema;
mod selection;
pub(super) use schema::migrate;

const MAX_RECORD_BYTES: usize = 2 * 1024 * 1024;

fn encode(value: &impl Serialize) -> KnowledgeResult<String> {
    let json = serde_json::to_string(value).map_err(storage)?;
    if json.len() > MAX_RECORD_BYTES {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(json)
}

fn decode_json<T: DeserializeOwned>(json: &str) -> KnowledgeResult<T> {
    if json.len() > MAX_RECORD_BYTES {
        return Err(KnowledgeError::Conflict);
    }
    serde_json::from_str(json).map_err(storage)
}

fn candidate_input(
    build: &CommunityBuildInput,
    candidate_id: &str,
) -> KnowledgeResult<Option<CommunityInput>> {
    let Some(candidate) = build
        .candidates
        .iter()
        .find(|c| c.membership_digest == candidate_id)
    else {
        return Ok(None);
    };
    let input = CommunityInput {
        build_id: build.receipt.build_id.clone(),
        graph_digest: build.receipt.graph_digest.clone(),
        candidate: candidate.clone(),
        snapshot: build.snapshot.clone(),
    };
    if !input.validate() {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(Some(input))
}

fn current_graph(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    build: &CommunityBuildInput,
) -> KnowledgeResult<bool> {
    Ok(
        fingerprint(&capture(tx, scope, build.snapshot.min_community_size)?)?
            == build.receipt.graph_digest,
    )
}

impl SqliteKnowledgeRepository {
    pub fn community_candidate_input_durable(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        candidate_id: &str,
    ) -> KnowledgeResult<Option<CommunityInput>> {
        validate(scope, candidate_id)?;
        self.community_build_durable(scope, build_id)?
            .map(|build| candidate_input(&build, candidate_id))
            .transpose()
            .map(Option::flatten)
    }
}

#[cfg(test)]
mod tests;
