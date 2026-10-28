//! Model-facing receipts preserve the authority of the recorded human response.
//!
//! This projection never creates grants. Tool authorization continues to use the
//! persisted decision and the host's exact permission keys, not this transcript.

use super::authority_store::DesktopHitlRequest;
use agistack_core::agent::types::HitlKind;
use serde_json::json;

pub(super) fn answer(request: &DesktopHitlRequest, fallback: &str) -> String {
    if request.kind != HitlKind::Permission {
        return fallback.to_owned();
    }
    json!({
        "type": "permission_response",
        "request_id": request.id,
        "conversation_id": request.conversation_id,
        "run_id": request.run_id,
        "authority_revision": request.authority_revision,
        "status": request.status,
        "decision": request.decision,
        "response_data": request.response_data,
        "response_actor": request.response_actor,
        "responded_at": request.responded_at,
    })
    .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    fn request(response: Value) -> DesktopHitlRequest {
        serde_json::from_value(json!({
            "id": "permission-step-1",
            "conversation_id": "conversation-1",
            "run_id": "run-1",
            "round": 2,
            "kind": "permission",
            "prompt": "Allow this recording once?",
            "decision": {
                "action": {"name": "computer_audio_start", "label": "Start recording"},
                "target": {"kind": "repl_step", "id": "step-1"},
                "data": {"summary": "microphone, maximum 3000 ms"},
                "reason": "Validate the requested recording",
                "risk": {"level": "medium", "rationale": "Captures nearby audio"},
                "reversibility": {"mode": "partial", "recovery": "Stop the recording"},
                "scope": {"kind": "repl_step", "ids": ["step-1"]},
                "evidence": [{"kind": "repl_step", "id": "step-1", "label": "Pending step"}]
            },
            "status": "responded",
            "authority_revision": 2,
            "created_at": "2026-10-22T04:39:30Z",
            "responded_at": "2026-10-22T04:39:38Z",
            "response_actor": "local_user",
            "response_data": response
        }))
        .expect("recorded response")
    }

    #[test]
    fn permission_receipt_binds_the_actual_once_response_to_its_pending_step() {
        let request = request(json!({"action": "allow", "granted": true, "scope": "once"}));
        let receipt: Value = serde_json::from_str(&answer(&request, "approved")).unwrap();
        assert_eq!(receipt["type"], "permission_response");
        assert_eq!(receipt["request_id"], request.id);
        assert_eq!(receipt["run_id"], "run-1");
        assert_eq!(receipt["status"], "responded");
        assert_eq!(receipt["authority_revision"], 2);
        assert_eq!(receipt["decision"], json!(request.decision));
        assert_eq!(receipt["response_data"], json!(request.response_data));
        assert_eq!(receipt["response_actor"], "local_user");
    }

    #[test]
    fn permission_receipt_never_infers_or_expands_response_scope() {
        for response in [
            json!({"action": "deny", "granted": false, "scope": "once"}),
            json!({"granted": true}),
            json!({"action": "allow", "granted": true, "scope": "session"}),
        ] {
            let request = request(response.clone());
            let receipt: Value = serde_json::from_str(&answer(&request, "approved")).unwrap();
            assert_eq!(receipt["response_data"], response);
            assert_eq!(receipt["decision"]["scope"]["ids"], json!(["step-1"]));
        }
    }

    #[test]
    fn non_permission_answers_keep_their_existing_content() {
        let mut request = request(json!({"answer": "Use the smaller image"}));
        request.kind = HitlKind::Clarification;
        assert_eq!(
            answer(&request, "Use the smaller image"),
            "Use the smaller image"
        );
        request.kind = HitlKind::EnvVar;
        assert_eq!(answer(&request, "redacted"), "redacted");
    }
}
