//! MCP app results stay private until the tool result policy accepts their body.

use std::{
    future::Future,
    sync::{Arc, Mutex},
};

use serde_json::Value;

use super::LocalRuntimeState;

pub(super) struct PendingResultEvent {
    state: Arc<LocalRuntimeState>,
    conversation_id: String,
    item: Value,
}

tokio::task_local! {
    static PENDING: Arc<Mutex<Vec<PendingResultEvent>>>;
}

pub(super) async fn capture<F: Future>(future: F) -> (F::Output, Vec<PendingResultEvent>) {
    let pending = Arc::new(Mutex::new(Vec::new()));
    let result = PENDING.scope(pending.clone(), future).await;
    let events = std::mem::take(&mut *pending.lock().expect("pending tool result events"));
    (result, events)
}

pub(super) fn append(state: &Arc<LocalRuntimeState>, conversation_id: &str, item: Value) {
    if let Ok(pending) = PENDING.try_with(Arc::clone) {
        pending
            .lock()
            .expect("pending tool result events")
            .push(PendingResultEvent {
                state: state.clone(),
                conversation_id: conversation_id.into(),
                item,
            });
    } else {
        state.append_timeline(conversation_id, item);
    }
}

pub(super) fn publish(events: Vec<PendingResultEvent>) {
    for event in events {
        event
            .state
            .append_timeline(&event.conversation_id, event.item);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn result_events_wait_for_acceptance_and_dropping_does_not_publish() {
        let state = super::super::tests::test_state("result-policy-test");
        let conversation_id = "result-policy-conversation";
        super::super::tests::seed_plan_conversation(&state, conversation_id);
        let count = state.session_store.timeline_count(conversation_id).unwrap();
        let (_, discarded) = capture(async {
            append(&state, conversation_id, serde_json::json!({"id":"discarded","type":"mcp_app_result","data":{"output":"private"}}));
            assert_eq!(state.session_store.timeline_count(conversation_id).unwrap(), count);
        }).await;
        assert_eq!(discarded.len(), 1);
        drop(discarded);
        assert_eq!(
            state.session_store.timeline_count(conversation_id).unwrap(),
            count
        );
        let (_, accepted) = capture(async {
            append(&state, conversation_id, serde_json::json!({"id":"accepted","type":"mcp_app_result","data":{"output":"accepted"}}));
        }).await;
        publish(accepted);
        assert_eq!(
            state.session_store.timeline_count(conversation_id).unwrap(),
            count + 1
        );
    }
}
