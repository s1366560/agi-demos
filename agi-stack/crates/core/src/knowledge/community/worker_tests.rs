use super::*;
use crate::{
    agent::TranscriptEntry,
    knowledge::{
        community::{CommunityProjection, CommunitySource},
        processing::{ProcessingProjection, ProcessingRelationship},
    },
    model::{Entity, Episode},
    ports::MemoryDraft,
};
use async_trait::async_trait;
use std::sync::atomic::{AtomicUsize, Ordering};

fn fixture() -> CommunityInput {
    let source = ProcessingSource {
        tenant_id: "t".into(),
        project_id: "p".into(),
        memory_id: "m".into(),
        revision: 1,
        change_sequence: 1,
    };
    CommunityInput {
        build_id: "build-1".into(),
        graph_digest: "a".repeat(64),
        candidate: CommunityCandidate {
            membership_digest: "b".repeat(64),
            members: (0..2)
                .map(|entity_index| EntityReference {
                    source: source.clone(),
                    entity_index,
                })
                .collect(),
        },
        snapshot: CommunitySnapshot {
            tenant_id: "t".into(),
            project_id: "p".into(),
            algorithm_version: COMMUNITY_ALGORITHM_VERSION.into(),
            min_community_size: 2,
            graph_digest: "a".repeat(64),
            sources: vec![CommunitySource {
                source,
                payload: json!({"content":"untrusted input"}),
                processing_state: Some(ProcessingState::Completed),
                processing_attempt: Some(1),
                audited_projection: Some(CommunityProjection {
                    audit_attempt: 1,
                    audit_digest: "c".repeat(64),
                    projection: ProcessingProjection {
                        entities: vec![
                            Entity {
                                name: "a".into(),
                                kind: "test".into(),
                            },
                            Entity {
                                name: "b".into(),
                                kind: "test".into(),
                            },
                        ],
                        relationships: vec![ProcessingRelationship {
                            source_index: 0,
                            target_index: 1,
                            relation_type: "rel".into(),
                            fact: "fact".into(),
                            score: 1.0,
                        }],
                    },
                }),
            }],
        },
    }
}
fn submission(input: &CommunityInput) -> CommunitySubmission {
    CommunitySubmission {
        build_id: input.build_id.clone(),
        graph_digest: input.graph_digest.clone(),
        candidate_id: input.candidate.membership_digest.clone(),
        members: input.candidate.members.clone(),
        decision: CommunityDecision::Ready {
            name: "A community".into(),
            summary: "Supported summary".into(),
            rationale: "Supported by relationship zero".into(),
            evidence: vec![CommunityEvidence {
                source: input.candidate.members[0].source.clone(),
                entity_index: 0,
                relationship_index: Some(0),
            }],
        },
    }
}
fn action(submission: &CommunitySubmission) -> AgentAction {
    AgentAction::CallTool {
        tool: SUBMIT_COMMUNITY_TOOL.into(),
        input_json: serde_json::to_string(submission).unwrap(),
    }
}
#[test]
fn accepts_structured_ready_and_insufficient_without_inventing_verdict() {
    let input = fixture();
    let mut result = submission(&input);
    assert!(input.validate());
    assert_eq!(
        parse_submission(&action(&result), &input),
        Some(result.clone())
    );
    result.decision = CommunityDecision::InsufficientEvidence {
        rationale: "Cannot establish semantic coherence".into(),
        evidence: vec![],
    };
    assert_eq!(parse_submission(&action(&result), &input), Some(result));
}
#[test]
fn rejects_identity_and_order_changes() {
    let input = fixture();
    for change in 0..6 {
        let mut result = submission(&input);
        match change {
            0 => result.build_id.push('x'),
            1 => result.graph_digest = "d".repeat(64),
            2 => result.candidate_id = "e".repeat(64),
            3 => result.members.reverse(),
            4 => result.members[0].source.revision += 1,
            _ => result.members.push(result.members[0].clone()),
        }
        assert!(parse_submission(&action(&result), &input).is_none());
    }
}
#[test]
fn rejects_nonmember_stale_and_unrelated_evidence() {
    let mut input = fixture();
    input.snapshot.sources[0]
        .audited_projection
        .as_mut()
        .unwrap()
        .projection
        .entities
        .push(Entity {
            name: "outside".into(),
            kind: "test".into(),
        });
    input.snapshot.sources[0]
        .audited_projection
        .as_mut()
        .unwrap()
        .projection
        .relationships
        .push(ProcessingRelationship {
            source_index: 0,
            target_index: 2,
            relation_type: "outside".into(),
            fact: "outside".into(),
            score: 1.0,
        });
    for change in 0..5 {
        let mut result = submission(&input);
        let CommunityDecision::Ready { evidence, .. } = &mut result.decision else {
            unreachable!()
        };
        match change {
            0 => evidence[0].source.revision += 1,
            1 => evidence[0].entity_index = 2,
            2 => evidence[0].relationship_index = Some(1),
            3 => evidence[0].relationship_index = Some(u32::MAX),
            _ => evidence.clear(),
        };
        assert!(!result.validate(&input));
    }
}
#[test]
fn rejects_unaudited_wrong_scope_duplicate_and_oversized_inputs() {
    for change in 0..10 {
        let mut input = fixture();
        match change {
            0 => input.snapshot.sources[0].audited_projection = None,
            1 => input.snapshot.sources[0].processing_attempt = Some(2),
            2 => input.snapshot.sources[0].source.tenant_id = "other".into(),
            3 => input
                .snapshot
                .sources
                .push(input.snapshot.sources[0].clone()),
            4 => input.candidate.members[0].entity_index = 100,
            5 => input.candidate.members[1] = input.candidate.members[0].clone(),
            6 => input.snapshot.sources[0].payload = json!("x".repeat(MAX_INPUT_BYTES)),
            7 => input.candidate.members = vec![input.candidate.members[0].clone(); 4097],
            8 => input.snapshot.sources = vec![input.snapshot.sources[0].clone(); 1025],
            _ => input.snapshot.graph_digest = "d".repeat(64),
        }
        assert!(!input.validate(), "case {change}");
    }
}
#[test]
fn rejects_unknown_missing_and_non_tool_responses() {
    let input = fixture();
    let baseline = serde_json::to_value(submission(&input)).unwrap();
    for change in 0..4 {
        let mut value = baseline.clone();
        match change {
            0 => {
                value["extra"] = json!(true);
            }
            1 => {
                value["decision"]["extra"] = json!(true);
            }
            2 => {
                value["decision"]["evidence"][0]["source"]["extra"] = json!(true);
            }
            _ => {
                value["decision"]["evidence"][0]
                    .as_object_mut()
                    .unwrap()
                    .remove("relationship_index");
            }
        }
        assert!(parse_submission(
            &AgentAction::CallTool {
                tool: SUBMIT_COMMUNITY_TOOL.into(),
                input_json: value.to_string()
            },
            &input
        )
        .is_none());
    }
    assert!(parse_submission(
        &AgentAction::Finish {
            answer: baseline.to_string()
        },
        &input
    )
    .is_none());
    assert!(parse_submission(
        &AgentAction::CallTool {
            tool: "other".into(),
            input_json: baseline.to_string()
        },
        &input
    )
    .is_none());
}
#[test]
fn validates_all_output_limits() {
    let input = fixture();
    for change in 0..5 {
        let mut result = submission(&input);
        let CommunityDecision::Ready {
            name,
            summary,
            rationale,
            evidence,
        } = &mut result.decision
        else {
            unreachable!()
        };
        match change {
            0 => *name = "x".repeat(257),
            1 => *summary = "x".repeat(16385),
            2 => *rationale = "x".repeat(4097),
            3 => *evidence = vec![evidence[0].clone(); 257],
            _ => *rationale = " ".into(),
        };
        assert!(!result.validate(&input));
    }
}
struct Spy(AtomicUsize);
#[async_trait]
impl LlmPort for Spy {
    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        panic!("not extraction")
    }
    async fn decide(
        &self,
        _: &str,
        _: u64,
        _: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        panic!("must use structured tools")
    }
    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[ToolDefinition],
    ) -> CoreResult<AgentAction> {
        self.0.fetch_add(1, Ordering::SeqCst);
        assert_eq!(round, 1);
        assert!(transcript.is_empty());
        assert_eq!(tools.len(), 1);
        assert_eq!(tools[0], community_tool());
        assert!(goal.contains("untrusted"));
        assert!(goal.contains("metadata"));
        Ok(AgentAction::Finish {
            answer: "no submission".into(),
        })
    }
}
#[test]
fn request_is_single_bounded_structured_call_and_does_not_fallback() {
    let spy = Spy(AtomicUsize::new(0));
    let mut input = fixture();
    let response = futures::executor::block_on(request_community(&spy, &input)).unwrap();
    assert!(parse_submission(&response, &input).is_none());
    assert_eq!(spy.0.load(Ordering::SeqCst), 1);
    input.snapshot.sources[0].payload = json!("x".repeat(MAX_INPUT_BYTES));
    assert!(futures::executor::block_on(request_community(&spy, &input)).is_err());
    assert_eq!(spy.0.load(Ordering::SeqCst), 1);
}

#[test]
fn accepts_exact_unicode_limits_and_entity_only_evidence() {
    let input = fixture();
    let mut result = submission(&input);
    let CommunityDecision::Ready {
        name,
        summary,
        rationale,
        evidence,
    } = &mut result.decision
    else {
        unreachable!()
    };
    *name = "界".repeat(256);
    *summary = "界".repeat(16384);
    *rationale = "界".repeat(4096);
    evidence[0].relationship_index = None;
    *evidence = vec![evidence[0].clone(); 256];
    assert_eq!(parse_submission(&action(&result), &input), Some(result));
}

#[test]
fn rejects_nonincident_relation_and_invalid_insufficient_evidence() {
    let mut input = fixture();
    let projection = &mut input.snapshot.sources[0]
        .audited_projection
        .as_mut()
        .unwrap()
        .projection;
    projection.relationships.push(ProcessingRelationship {
        source_index: 1,
        target_index: 1,
        relation_type: "self".into(),
        fact: "self".into(),
        score: 1.0,
    });
    let mut result = submission(&input);
    let evidence = CommunityEvidence {
        source: input.candidate.members[0].source.clone(),
        entity_index: 0,
        relationship_index: Some(1),
    };
    result.decision = CommunityDecision::InsufficientEvidence {
        rationale: "Not enough coherent evidence".into(),
        evidence: vec![evidence],
    };
    assert!(input.validate());
    assert!(!result.validate(&input));
    result.decision = CommunityDecision::InsufficientEvidence {
        rationale: "x".repeat(4097),
        evidence: vec![],
    };
    assert!(!result.validate(&input));
}
