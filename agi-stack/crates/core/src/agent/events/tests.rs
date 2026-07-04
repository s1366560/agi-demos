use super::*;
use serde_json::{json, Value};

#[test]
fn wire_values_round_trip_for_every_variant() {
    // Guards against a rename typo across all 165 variants: the serde wire
    // string must parse back to the same variant, and serde must agree.
    for &t in AgentEventType::ALL {
        assert_eq!(
            AgentEventType::from_wire(t.as_str()),
            Some(t),
            "from_wire({})",
            t.as_str()
        );
        let ser = serde_json::to_string(&t).unwrap();
        assert_eq!(
            ser,
            format!("\"{}\"", t.as_str()),
            "serde rename for {:?}",
            t
        );
        let de: AgentEventType = serde_json::from_str(&ser).unwrap();
        assert_eq!(de, t);
    }
    assert_eq!(AgentEventType::ALL.len(), 165);
    assert_eq!(AgentEventType::from_wire("not_a_real_event"), None);
}

#[test]
fn category_matches_python_mapping() {
    // Explicit non-Agent arms.
    assert_eq!(
        AgentEventType::ClarificationAsked.category(),
        EventCategory::Hitl
    );
    assert_eq!(
        AgentEventType::EnvVarRequested.category(),
        EventCategory::Hitl
    );
    assert_eq!(
        AgentEventType::SandboxCreated.category(),
        EventCategory::Sandbox
    );
    assert_eq!(
        AgentEventType::TerminalStarted.category(),
        EventCategory::Sandbox
    );
    assert_eq!(
        AgentEventType::HttpServiceError.category(),
        EventCategory::Sandbox
    );
    assert_eq!(
        AgentEventType::UserMessage.category(),
        EventCategory::Message
    );
    assert_eq!(AgentEventType::CostUpdate.category(), EventCategory::System);
    assert_eq!(
        AgentEventType::ContextCompacted.category(),
        EventCategory::System
    );
    assert_eq!(AgentEventType::Retry.category(), EventCategory::System);
    // Default-Agent long-tail (unmapped in Python EVENT_CATEGORIES).
    assert_eq!(
        AgentEventType::MemoryRecalled.category(),
        EventCategory::Agent
    );
    assert_eq!(
        AgentEventType::ArtifactCreated.category(),
        EventCategory::Agent
    );
    assert_eq!(AgentEventType::Thought.category(), EventCategory::Agent);
    assert_eq!(EventCategory::Hitl.as_str(), "hitl");
}

#[test]
fn classification_predicates_match_python_sets() {
    assert!(AgentEventType::ThoughtDelta.is_delta());
    assert!(AgentEventType::TextEnd.is_delta());
    assert!(!AgentEventType::Thought.is_delta());

    assert!(AgentEventType::Complete.is_terminal());
    assert!(AgentEventType::Error.is_terminal());
    assert!(AgentEventType::Cancelled.is_terminal());
    assert!(!AgentEventType::Status.is_terminal());

    assert!(AgentEventType::PermissionAsked.requires_human_response());
    assert!(AgentEventType::A2uiActionAsked.requires_human_response());
    assert!(!AgentEventType::DecisionAnswered.requires_human_response());

    assert!(AgentEventType::CompactNeeded.is_internal());
    assert!(AgentEventType::Retry.is_internal());
    assert!(!AgentEventType::Status.is_internal());
}

#[test]
fn envelope_wrap_shape_matches_python_to_dict() {
    let env = EventEnvelope::wrap(
        AgentEventType::Thought,
        json!({"text": "hello"}),
        "evt_test01",
        "2024-01-01T00:00:00Z",
    );
    let v = env.to_value();
    assert_eq!(v["schema_version"], json!("1.0"));
    assert_eq!(v["event_id"], json!("evt_test01"));
    assert_eq!(v["event_type"], json!("thought"));
    assert_eq!(v["timestamp"], json!("2024-01-01T00:00:00Z"));
    assert_eq!(v["source"], json!("memstack"));
    // Absent correlation/causation serialize as explicit null (shape parity).
    assert_eq!(v["correlation_id"], Value::Null);
    assert_eq!(v["causation_id"], Value::Null);
    assert_eq!(v["payload"], json!({"text": "hello"}));
    assert_eq!(v["metadata"], json!({}));
    assert_eq!(env.typed(), Some(AgentEventType::Thought));
    assert_eq!(env.category(), Some(EventCategory::Agent));
}

#[test]
fn child_inherits_correlation_and_sets_causation() {
    let parent = EventEnvelope::wrap(AgentEventType::Start, json!({}), "evt_parent", "t0")
        .with_correlation("corr_1", None)
        .with_metadata("tenant_id", json!("acme"));

    let child = parent.child(AgentEventType::Thought, json!({"i": 1}), "evt_child", "t1");
    assert_eq!(child.correlation_id.as_deref(), Some("corr_1"));
    assert_eq!(child.causation_id.as_deref(), Some("evt_parent"));
    // Parent metadata is merged into the child.
    assert_eq!(child.metadata["tenant_id"], json!("acme"));
    assert_eq!(child.event_type, "thought");
}

#[test]
fn json_round_trip_is_lossless() {
    let env = EventEnvelope::wrap(
        AgentEventType::TaskComplete,
        json!({"task_id": "t7"}),
        "evt_x",
        "t0",
    )
    .with_correlation("c9", Some("evt_cause".to_string()));
    let s = env.to_json();
    let back = EventEnvelope::from_json(&s).unwrap();
    assert_eq!(back, env);
    assert_eq!(back.causation_id.as_deref(), Some("evt_cause"));
}

#[test]
fn derive_event_id_is_deterministic_and_shaped() {
    let a = derive_event_id("round:3|type:thought");
    let b = derive_event_id("round:3|type:thought");
    assert_eq!(a, b);
    assert!(a.starts_with("evt_"));
    assert_eq!(a.len(), 4 + 12); // "evt_" + 12 hex chars
    assert!(a[4..].chars().all(|c| c.is_ascii_hexdigit()));
    assert_ne!(a, derive_event_id("round:4|type:thought"));
}
