use std::collections::HashMap;

use axum::extract::ws::{Message, WebSocket};
use serde_json::{json, Value};

use crate::AppState;

const EVENT_REPLAY_BATCH: usize = 100;
const MAX_EVENTS_PER_FLUSH: usize = 256;
const MAX_SUBSCRIPTIONS_PER_CONNECTION: usize = 64;

#[derive(Debug, Clone, Default)]
struct Subscription {
    last_id: String,
    message_id: Option<String>,
    from_time_us: Option<i64>,
    from_counter: Option<u64>,
}

#[derive(Debug, Default)]
pub(super) struct ConnectionSubscriptions {
    conversations: HashMap<String, Subscription>,
    sandboxes: HashMap<String, Subscription>,
}

impl ConnectionSubscriptions {
    pub(super) fn subscribe_conversation(
        &mut self,
        conversation_id: String,
        last_id: Option<String>,
        message_id: Option<String>,
        from_time_us: Option<i64>,
        from_counter: Option<u64>,
    ) -> bool {
        if !self.can_add(self.conversations.contains_key(&conversation_id)) {
            return false;
        }
        self.conversations.insert(
            conversation_id,
            Subscription {
                last_id: last_id.unwrap_or_default(),
                message_id,
                from_time_us,
                from_counter,
            },
        );
        true
    }

    pub(super) fn ensure_conversation(
        &mut self,
        conversation_id: String,
        message_id: Option<String>,
    ) -> bool {
        if !self.can_add(self.conversations.contains_key(&conversation_id)) {
            return false;
        }
        self.conversations
            .entry(conversation_id)
            .or_insert_with(|| Subscription {
                message_id,
                ..Subscription::default()
            });
        true
    }

    pub(super) fn unsubscribe_conversation(&mut self, conversation_id: &str) {
        self.conversations.remove(conversation_id);
    }

    pub(super) fn subscribe_sandbox(&mut self, project_id: String) -> bool {
        if !self.can_add(self.sandboxes.contains_key(&project_id)) {
            return false;
        }
        self.sandboxes.entry(project_id).or_default();
        true
    }

    pub(super) fn unsubscribe_sandbox(&mut self, project_id: &str) {
        self.sandboxes.remove(project_id);
    }

    fn can_add(&self, already_subscribed: bool) -> bool {
        already_subscribed || self.active_count() < MAX_SUBSCRIPTIONS_PER_CONNECTION
    }

    fn active_count(&self) -> usize {
        self.conversations.len() + self.sandboxes.len()
    }
}

pub(super) async fn flush_event_subscriptions(
    app: &AppState,
    socket: &mut WebSocket,
    subscriptions: &mut ConnectionSubscriptions,
) -> Result<(), ()> {
    let mut sent_this_flush = 0;
    flush_conversation_subscriptions(
        app,
        socket,
        &mut subscriptions.conversations,
        &mut sent_this_flush,
    )
    .await?;
    flush_sandbox_subscriptions(
        app,
        socket,
        &mut subscriptions.sandboxes,
        &mut sent_this_flush,
    )
    .await?;
    Ok(())
}

async fn flush_conversation_subscriptions(
    app: &AppState,
    socket: &mut WebSocket,
    subscriptions: &mut HashMap<String, Subscription>,
    sent_this_flush: &mut usize,
) -> Result<(), ()> {
    for (conversation_id, subscription) in subscriptions.iter_mut() {
        let Some(limit) = replay_limit(*sent_this_flush) else {
            break;
        };
        let entries = app
            .events
            .read_after(
                &agent_stream_topic(conversation_id),
                &subscription.last_id,
                limit,
            )
            .await
            .map_err(|_| ())?;
        for entry in entries {
            let entry_id = entry.id;
            let message = conversation_entry_to_ws_message(conversation_id, &entry.payload);
            if subscription_allows(subscription, &message) {
                send_json(socket, message).await?;
                *sent_this_flush += 1;
            }
            subscription.last_id = entry_id;
            if replay_limit(*sent_this_flush).is_none() {
                break;
            }
        }
    }
    Ok(())
}

async fn flush_sandbox_subscriptions(
    app: &AppState,
    socket: &mut WebSocket,
    subscriptions: &mut HashMap<String, Subscription>,
    sent_this_flush: &mut usize,
) -> Result<(), ()> {
    for (project_id, subscription) in subscriptions.iter_mut() {
        let Some(limit) = replay_limit(*sent_this_flush) else {
            break;
        };
        let entries = app
            .events
            .read_after(
                &sandbox_stream_topic(project_id),
                &subscription.last_id,
                limit,
            )
            .await
            .map_err(|_| ())?;
        for entry in entries {
            let entry_id = entry.id;
            let message = sandbox_entry_to_ws_message(project_id, &entry.payload, &entry_id);
            send_json(socket, message).await?;
            *sent_this_flush += 1;
            subscription.last_id = entry_id;
            if replay_limit(*sent_this_flush).is_none() {
                break;
            }
        }
    }
    Ok(())
}

fn replay_limit(sent_this_flush: usize) -> Option<usize> {
    MAX_EVENTS_PER_FLUSH
        .checked_sub(sent_this_flush)
        .map(|remaining| remaining.min(EVENT_REPLAY_BATCH))
        .filter(|remaining| *remaining > 0)
}

fn subscription_allows(subscription: &Subscription, message: &Value) -> bool {
    if let Some(expected_message_id) = subscription.message_id.as_deref() {
        let actual_message_id = message
            .pointer("/data/message_id")
            .and_then(Value::as_str)
            .or_else(|| message.get("message_id").and_then(Value::as_str));
        if let Some(actual_message_id) = actual_message_id {
            if actual_message_id != expected_message_id {
                return false;
            }
        }
    }
    if let Some(from_time_us) = subscription.from_time_us {
        let Some(event_time_us) = event_time_us(message) else {
            return false;
        };
        if event_time_us < from_time_us {
            return false;
        }
        if event_time_us == from_time_us {
            let from_counter = subscription.from_counter.unwrap_or_default();
            return event_counter(message).unwrap_or_default() >= from_counter;
        }
    }
    true
}

fn event_time_us(message: &Value) -> Option<i64> {
    message
        .get("event_time_us")
        .and_then(Value::as_i64)
        .or_else(|| message.get("time_us").and_then(Value::as_i64))
}

fn event_counter(message: &Value) -> Option<u64> {
    message
        .get("event_counter")
        .and_then(Value::as_u64)
        .or_else(|| message.get("counter").and_then(Value::as_u64))
}

fn conversation_entry_to_ws_message(conversation_id: &str, payload: &str) -> Value {
    let parsed: Value = serde_json::from_str(payload).unwrap_or_else(|_| json!({}));
    if parsed.get("type").is_some() {
        let mut message = parsed;
        if let Some(obj) = message.as_object_mut() {
            obj.insert("conversation_id".to_string(), json!(conversation_id));
        }
        return message;
    }
    if parsed.get("event_type").is_some() {
        return json!({
            "type": parsed
                .get("event_type")
                .and_then(Value::as_str)
                .unwrap_or("message"),
            "conversation_id": conversation_id,
            "message_id": parsed.get("message_id").cloned().unwrap_or(Value::Null),
            "counter": parsed.get("counter").cloned().unwrap_or(Value::Null),
            "time_us": parsed.get("time_us").cloned().unwrap_or(Value::Null),
            "data": parsed.get("payload").cloned().unwrap_or(Value::Null),
            "envelope": parsed,
        });
    }
    json!({
        "type": "error",
        "conversation_id": conversation_id,
        "data": {"message": "Malformed event payload"}
    })
}

fn sandbox_entry_to_ws_message(project_id: &str, payload: &str, entry_id: &str) -> Value {
    let event_data: Value = serde_json::from_str(payload).unwrap_or_else(|_| json!({}));
    json!({
        "type": "sandbox_event",
        "routing_key": format!("sandbox:{project_id}"),
        "project_id": project_id,
        "data": event_data,
        "event_id": entry_id,
    })
}

async fn send_json(socket: &mut WebSocket, value: Value) -> Result<(), ()> {
    socket
        .send(Message::Text(value.to_string()))
        .await
        .map_err(|_| ())
}

fn agent_stream_topic(conversation_id: &str) -> String {
    format!("agent:events:{conversation_id}")
}

fn sandbox_stream_topic(project_id: &str) -> String {
    format!("sandbox:events:{project_id}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stream_payload_matches_frontend_contract() {
        let payload = json!({
            "event_type": "agent_token",
            "conversation_id": "c1",
            "message_id": "m1",
            "counter": 7,
            "time_us": 1234,
            "payload": {"text": "hi"}
        });

        let value = conversation_entry_to_ws_message("c1", &payload.to_string());

        assert_eq!(value["type"], "agent_token");
        assert_eq!(value["conversation_id"], "c1");
        assert_eq!(value["message_id"], "m1");
        assert_eq!(value["counter"], 7);
        assert_eq!(value["time_us"], 1234);
        assert_eq!(value["data"]["text"], "hi");
    }

    #[test]
    fn appended_payload_shape_is_preserved_for_frontend() {
        let payload = json!({
            "type": "complete",
            "data": {"answer": "ok", "message_id": "m1"},
            "event_time_us": 7,
            "event_counter": 2,
        });

        let value = conversation_entry_to_ws_message("c1", &payload.to_string());

        assert_eq!(value["type"], "complete");
        assert_eq!(value["conversation_id"], "c1");
        assert_eq!(value["data"]["answer"], "ok");
        assert_eq!(value["event_time_us"], 7);
        assert_eq!(value["event_counter"], 2);
    }

    #[test]
    fn subscription_filters_by_message_and_cursor_metadata() {
        let subscription = Subscription {
            last_id: "0-0".to_string(),
            message_id: Some("m1".to_string()),
            from_time_us: Some(10),
            from_counter: Some(2),
        };

        assert!(subscription_allows(
            &subscription,
            &json!({"data": {"message_id": "m1"}, "event_time_us": 10, "event_counter": 2})
        ));
        assert!(!subscription_allows(
            &subscription,
            &json!({"data": {"message_id": "m2"}, "event_time_us": 10, "event_counter": 2})
        ));
        assert!(!subscription_allows(
            &subscription,
            &json!({"data": {"message_id": "m1"}, "event_time_us": 9, "event_counter": 2})
        ));
        assert!(!subscription_allows(
            &subscription,
            &json!({"data": {"message_id": "m1"}, "event_time_us": 10, "event_counter": 1})
        ));
    }

    #[test]
    fn subscription_limit_counts_sandbox_and_conversation_streams() {
        let mut subscriptions = ConnectionSubscriptions::default();
        for index in 0..MAX_SUBSCRIPTIONS_PER_CONNECTION {
            assert!(subscriptions.ensure_conversation(format!("c{index}"), None));
        }

        assert!(!subscriptions.subscribe_sandbox("p1".to_string()));
        assert!(subscriptions.ensure_conversation("c0".to_string(), Some("m1".to_string())));
        subscriptions.unsubscribe_conversation("c0");
        assert!(subscriptions.subscribe_sandbox("p1".to_string()));
        assert!(!subscriptions.ensure_conversation("new".to_string(), None));
    }

    #[test]
    fn replay_limit_stops_at_flush_budget() {
        assert_eq!(replay_limit(0), Some(EVENT_REPLAY_BATCH));
        assert_eq!(replay_limit(MAX_EVENTS_PER_FLUSH - 1), Some(1));
        assert_eq!(replay_limit(MAX_EVENTS_PER_FLUSH), None);
    }

    #[test]
    fn sandbox_payload_matches_frontend_contract() {
        let payload = json!({
            "type": "sandbox.started",
            "data": {"sandbox_id": "s1", "status": "running"},
            "timestamp": "2026-07-05T00:00:00Z"
        });

        let value = sandbox_entry_to_ws_message("p1", &payload.to_string(), "7-0");

        assert_eq!(value["type"], "sandbox_event");
        assert_eq!(value["routing_key"], "sandbox:p1");
        assert_eq!(value["project_id"], "p1");
        assert_eq!(value["event_id"], "7-0");
        assert_eq!(value["data"]["type"], "sandbox.started");
        assert_eq!(value["data"]["data"]["status"], "running");
    }
}
