mod authorization;
mod scope_validation;

use std::{collections::HashMap, time::Instant};

use axum::extract::ws::{Message, WebSocket};
use serde_json::{json, Value};

use crate::AppState;

#[cfg(test)]
use authorization::{
    conversation_authorization_needs_refresh, refresh_conversation_authorization,
    refresh_scoped_authorization, scoped_authorization_needs_refresh,
    CONVERSATION_AUTHORIZATION_LEASE, SCOPED_AUTHORIZATION_LEASE,
};
use authorization::{
    reauthorize_conversation_subscriptions, reauthorize_sandbox_subscriptions,
    reauthorize_workspace_subscriptions,
};
use scope_validation::{sandbox_message_matches_scope, workspace_message_matches_scope};

const EVENT_REPLAY_BATCH: usize = 100;
const MAX_EVENTS_PER_FLUSH: usize = 256;
const MAX_SUBSCRIPTIONS_PER_CONNECTION: usize = 64;

#[derive(Debug, Clone)]
struct SubscriptionScope {
    tenant_id: String,
    project_id: String,
    authorized_at: Instant,
}

#[derive(Debug, Clone, Default)]
struct Subscription {
    last_id: String,
    message_id: Option<String>,
    from_time_us: Option<i64>,
    from_counter: Option<u64>,
    conversation_authorized_at: Option<Instant>,
    scope: Option<SubscriptionScope>,
}

#[derive(Debug, Default)]
pub(super) struct ConnectionSubscriptions {
    conversations: HashMap<String, Subscription>,
    sandboxes: HashMap<String, Subscription>,
    workspaces: HashMap<String, Subscription>,
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
                conversation_authorized_at: Some(Instant::now()),
                scope: None,
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
        let authorization_time = Instant::now();
        self.conversations
            .entry(conversation_id)
            .and_modify(|subscription| {
                subscription.conversation_authorized_at = Some(authorization_time);
            })
            .or_insert_with(|| Subscription {
                message_id,
                conversation_authorized_at: Some(authorization_time),
                ..Subscription::default()
            });
        true
    }

    pub(super) fn unsubscribe_conversation(&mut self, conversation_id: &str) {
        self.conversations.remove(conversation_id);
    }

    #[cfg(test)]
    pub(super) fn contains_conversation(&self, conversation_id: &str) -> bool {
        self.conversations.contains_key(conversation_id)
    }

    pub(super) fn subscribe_workspace(
        &mut self,
        workspace_id: String,
        project_id: String,
        tenant_id: String,
        last_id: Option<String>,
    ) -> bool {
        if !self.can_add(self.workspaces.contains_key(&workspace_id)) {
            return false;
        }
        self.workspaces.insert(
            workspace_id,
            Subscription {
                last_id: last_id.unwrap_or_default(),
                scope: Some(SubscriptionScope {
                    tenant_id,
                    project_id,
                    authorized_at: Instant::now(),
                }),
                ..Subscription::default()
            },
        );
        true
    }

    pub(super) fn unsubscribe_workspace(&mut self, workspace_id: &str) {
        self.workspaces.remove(workspace_id);
    }

    #[cfg(test)]
    pub(super) fn contains_workspace(&self, workspace_id: &str) -> bool {
        self.workspaces.contains_key(workspace_id)
    }

    pub(super) fn subscribe_sandbox(&mut self, project_id: String, tenant_id: String) -> bool {
        if !self.can_add(self.sandboxes.contains_key(&project_id)) {
            return false;
        }
        self.sandboxes.insert(
            project_id.clone(),
            Subscription {
                scope: Some(SubscriptionScope {
                    tenant_id,
                    project_id,
                    authorized_at: Instant::now(),
                }),
                ..Subscription::default()
            },
        );
        true
    }

    pub(super) fn unsubscribe_sandbox(&mut self, project_id: &str) {
        self.sandboxes.remove(project_id);
    }

    #[cfg(test)]
    pub(super) fn contains_sandbox(&self, project_id: &str) -> bool {
        self.sandboxes.contains_key(project_id)
    }

    fn can_add(&self, already_subscribed: bool) -> bool {
        already_subscribed || self.active_count() < MAX_SUBSCRIPTIONS_PER_CONNECTION
    }

    fn active_count(&self) -> usize {
        self.conversations.len() + self.sandboxes.len() + self.workspaces.len()
    }
}

pub(super) async fn flush_event_subscriptions(
    app: &AppState,
    user_id: &str,
    socket: &mut WebSocket,
    subscriptions: &mut ConnectionSubscriptions,
) -> Result<(), ()> {
    let mut sent_this_flush = 0;
    reauthorize_conversation_subscriptions(app, user_id, socket, &mut subscriptions.conversations)
        .await?;
    reauthorize_sandbox_subscriptions(app, user_id, socket, &mut subscriptions.sandboxes).await?;
    reauthorize_workspace_subscriptions(app, user_id, socket, &mut subscriptions.workspaces)
        .await?;
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
    flush_workspace_subscriptions(
        app,
        socket,
        &mut subscriptions.workspaces,
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
            if !sandbox_message_matches_scope(subscription, &message) {
                subscription.last_id = entry_id;
                continue;
            }
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

async fn flush_workspace_subscriptions(
    app: &AppState,
    socket: &mut WebSocket,
    subscriptions: &mut HashMap<String, Subscription>,
    sent_this_flush: &mut usize,
) -> Result<(), ()> {
    for (workspace_id, subscription) in subscriptions.iter_mut() {
        let Some(limit) = replay_limit(*sent_this_flush) else {
            break;
        };
        let entries = app
            .events
            .read_after(
                &workspace_stream_topic(workspace_id),
                &subscription.last_id,
                limit,
            )
            .await
            .map_err(|_| ())?;
        for entry in entries {
            let entry_id = entry.id;
            let message = workspace_entry_to_ws_message(workspace_id, &entry.payload, &entry_id);
            if !workspace_message_matches_scope(subscription, &message) {
                subscription.last_id = entry_id;
                continue;
            }
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

fn workspace_entry_to_ws_message(workspace_id: &str, payload: &str, entry_id: &str) -> Value {
    let parsed: Value = serde_json::from_str(payload).unwrap_or_else(|_| json!({}));
    if parsed.get("type").is_some() {
        let mut message = parsed;
        if let Some(obj) = message.as_object_mut() {
            obj.insert("workspace_id".to_string(), json!(workspace_id));
            obj.insert(
                "routing_key".to_string(),
                json!(format!("workspace:{workspace_id}")),
            );
            obj.insert("event_id".to_string(), json!(entry_id));
        }
        return message;
    }
    json!({
        "type": "error",
        "workspace_id": workspace_id,
        "routing_key": format!("workspace:{workspace_id}"),
        "event_id": entry_id,
        "data": {"message": "Malformed workspace event payload"}
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

fn workspace_stream_topic(workspace_id: &str) -> String {
    format!("workspace:events:{workspace_id}")
}

#[cfg(test)]
mod tests {
    use std::time::{Duration, Instant};

    use crate::agent_conversations_api::{AgentConversationsApiError, ConversationSocketAccess};

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
            conversation_authorized_at: None,
            scope: None,
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

        assert!(!subscriptions.subscribe_sandbox("p1".to_string(), "t1".to_string()));
        assert!(!subscriptions.subscribe_workspace(
            "w1".to_string(),
            "p1".to_string(),
            "t1".to_string(),
            None,
        ));
        assert!(subscriptions.ensure_conversation("c0".to_string(), Some("m1".to_string())));
        subscriptions.unsubscribe_conversation("c0");
        assert!(subscriptions.subscribe_sandbox("p1".to_string(), "t1".to_string()));
        assert!(!subscriptions.subscribe_workspace(
            "w1".to_string(),
            "p1".to_string(),
            "t1".to_string(),
            None,
        ));
        subscriptions.unsubscribe_sandbox("p1");
        assert!(subscriptions.subscribe_workspace(
            "w1".to_string(),
            "p1".to_string(),
            "t1".to_string(),
            Some("7-0".to_string()),
        ));
        assert!(!subscriptions.ensure_conversation("new".to_string(), None));
    }

    #[test]
    fn replay_limit_stops_at_flush_budget() {
        assert_eq!(replay_limit(0), Some(EVENT_REPLAY_BATCH));
        assert_eq!(replay_limit(MAX_EVENTS_PER_FLUSH - 1), Some(1));
        assert_eq!(replay_limit(MAX_EVENTS_PER_FLUSH), None);
    }

    #[test]
    fn conversation_authorization_lease_requires_periodic_refresh() {
        let authorized_at = Instant::now();
        let subscription = Subscription {
            conversation_authorized_at: Some(authorized_at),
            ..Subscription::default()
        };

        assert!(!conversation_authorization_needs_refresh(
            &subscription,
            authorized_at + CONVERSATION_AUTHORIZATION_LEASE - Duration::from_millis(1),
        ));
        assert!(conversation_authorization_needs_refresh(
            &subscription,
            authorized_at + CONVERSATION_AUTHORIZATION_LEASE,
        ));
        assert!(conversation_authorization_needs_refresh(
            &Subscription::default(),
            authorized_at,
        ));
    }

    #[test]
    fn conversation_authorization_refresh_fails_closed_and_removes_subscription() {
        for access in [
            Ok(ConversationSocketAccess::Denied),
            Ok(ConversationSocketAccess::NotFound),
            Err(AgentConversationsApiError::internal(
                "authorization unavailable",
            )),
        ] {
            let mut subscriptions =
                HashMap::from([("conversation-private".to_string(), Subscription::default())]);

            assert!(!refresh_conversation_authorization(
                access,
                &mut subscriptions,
                "conversation-private",
                Instant::now(),
            ));
            assert!(!subscriptions.contains_key("conversation-private"));
        }

        let authorized_at = Instant::now();
        let mut subscriptions =
            HashMap::from([("conversation-owned".to_string(), Subscription::default())]);
        assert!(refresh_conversation_authorization(
            Ok(ConversationSocketAccess::Allowed),
            &mut subscriptions,
            "conversation-owned",
            authorized_at,
        ));
        assert_eq!(
            subscriptions["conversation-owned"].conversation_authorized_at,
            Some(authorized_at)
        );
    }

    #[test]
    fn scoped_authorization_lease_refreshes_without_resetting_cursor() {
        let authorized_at = Instant::now();
        let subscription = Subscription {
            last_id: "41-0".to_string(),
            scope: Some(SubscriptionScope {
                tenant_id: "tenant-1".to_string(),
                project_id: "project-1".to_string(),
                authorized_at,
            }),
            ..Subscription::default()
        };
        assert!(!scoped_authorization_needs_refresh(
            &subscription,
            authorized_at + SCOPED_AUTHORIZATION_LEASE - Duration::from_millis(1),
        ));
        assert!(scoped_authorization_needs_refresh(
            &subscription,
            authorized_at + SCOPED_AUTHORIZATION_LEASE,
        ));

        let refreshed_at = authorized_at + SCOPED_AUTHORIZATION_LEASE;
        let mut subscriptions = HashMap::from([("project-1".to_string(), subscription)]);
        assert!(refresh_scoped_authorization(
            true,
            &mut subscriptions,
            "project-1",
            refreshed_at,
        ));
        assert_eq!(subscriptions["project-1"].last_id, "41-0");
        assert_eq!(
            subscriptions["project-1"]
                .scope
                .as_ref()
                .map(|scope| scope.authorized_at),
            Some(refreshed_at)
        );

        assert!(!refresh_scoped_authorization(
            false,
            &mut subscriptions,
            "project-1",
            Instant::now(),
        ));
        assert!(!subscriptions.contains_key("project-1"));
    }

    #[test]
    fn scoped_event_payloads_reject_conflicting_project_or_tenant_metadata() {
        let subscription = Subscription {
            scope: Some(SubscriptionScope {
                tenant_id: "tenant-1".to_string(),
                project_id: "project-1".to_string(),
                authorized_at: Instant::now(),
            }),
            ..Subscription::default()
        };
        let sandbox_allowed = sandbox_entry_to_ws_message(
            "project-1",
            &json!({
                "type": "sandbox.started",
                "project_id": "project-1",
                "tenant_id": "tenant-1",
            })
            .to_string(),
            "1-0",
        );
        let sandbox_denied = sandbox_entry_to_ws_message(
            "project-1",
            &json!({"type": "sandbox.started", "project_id": "project-other"}).to_string(),
            "2-0",
        );
        assert!(sandbox_message_matches_scope(
            &subscription,
            &sandbox_allowed
        ));
        assert!(!sandbox_message_matches_scope(
            &subscription,
            &sandbox_denied
        ));

        let workspace_allowed = workspace_entry_to_ws_message(
            "workspace-1",
            &json!({
                "type": "workspace_event",
                "project_id": "project-1",
                "tenant_id": "tenant-1",
            })
            .to_string(),
            "3-0",
        );
        let workspace_denied = workspace_entry_to_ws_message(
            "workspace-1",
            &json!({"type": "workspace_event", "tenant_id": "tenant-other"}).to_string(),
            "4-0",
        );
        assert!(workspace_message_matches_scope(
            &subscription,
            &workspace_allowed
        ));
        assert!(!workspace_message_matches_scope(
            &subscription,
            &workspace_denied
        ));
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

    #[test]
    fn workspace_payload_matches_frontend_contract() {
        let payload = json!({
            "type": "workspace_agent_mention_token_chunk",
            "workspace_id": "original-workspace",
            "project_id": "p1",
            "data": {
                "message_id": "m1",
                "chunk_index": 0,
                "content_delta": "hello"
            },
            "event_time_us": 1234
        });

        let value = workspace_entry_to_ws_message("w1", &payload.to_string(), "8-0");

        assert_eq!(value["type"], "workspace_agent_mention_token_chunk");
        assert_eq!(value["workspace_id"], "w1");
        assert_eq!(value["routing_key"], "workspace:w1");
        assert_eq!(value["event_id"], "8-0");
        assert_eq!(value["project_id"], "p1");
        assert_eq!(value["data"]["message_id"], "m1");
        assert_eq!(value["data"]["content_delta"], "hello");
        assert_eq!(value["event_time_us"], 1234);
    }
}
