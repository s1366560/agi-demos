use super::*;

#[test]
fn worker_conversation_id_matches_python_uuid5_contract() {
    assert_eq!(
        worker_conversation_id(
            "workspace-test",
            "agent-worker",
            "task-test",
            Some("attempt-test")
        ),
        "d267a78e-eefc-5d33-bfb3-ac4fa7ece855"
    );
}
