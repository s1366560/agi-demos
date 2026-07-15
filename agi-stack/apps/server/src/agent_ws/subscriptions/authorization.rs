use std::{
    collections::HashMap,
    time::{Duration, Instant},
};

use axum::extract::ws::WebSocket;
use serde_json::json;

use crate::{
    agent_conversations_api::{AgentConversationsApiError, ConversationSocketAccess},
    AppState,
};

use super::{send_json, Subscription};

pub(super) const CONVERSATION_AUTHORIZATION_LEASE: Duration = Duration::from_secs(30);
pub(super) const SCOPED_AUTHORIZATION_LEASE: Duration = Duration::from_secs(30);

pub(super) async fn reauthorize_conversation_subscriptions(
    app: &AppState,
    user_id: &str,
    socket: &mut WebSocket,
    subscriptions: &mut HashMap<String, Subscription>,
) -> Result<(), ()> {
    let now = Instant::now();
    let conversation_ids = subscriptions
        .iter()
        .filter(|(_, subscription)| conversation_authorization_needs_refresh(subscription, now))
        .map(|(conversation_id, _)| conversation_id.clone())
        .collect::<Vec<_>>();

    for conversation_id in conversation_ids {
        let access = app
            .agent_conversations
            .authorize_event_subscription(user_id, &conversation_id)
            .await;
        if refresh_conversation_authorization(
            access,
            subscriptions,
            &conversation_id,
            Instant::now(),
        ) {
            continue;
        }
        send_json(
            socket,
            json!({
                "type": "error",
                "conversation_id": conversation_id,
                "data": {"message": "Access denied"},
            }),
        )
        .await?;
    }
    Ok(())
}

pub(super) fn refresh_conversation_authorization(
    access: Result<ConversationSocketAccess, AgentConversationsApiError>,
    subscriptions: &mut HashMap<String, Subscription>,
    conversation_id: &str,
    authorized_at: Instant,
) -> bool {
    if matches!(access, Ok(ConversationSocketAccess::Allowed)) {
        if let Some(subscription) = subscriptions.get_mut(conversation_id) {
            subscription.conversation_authorized_at = Some(authorized_at);
        }
        true
    } else {
        subscriptions.remove(conversation_id);
        false
    }
}

pub(super) fn conversation_authorization_needs_refresh(
    subscription: &Subscription,
    now: Instant,
) -> bool {
    subscription
        .conversation_authorized_at
        .and_then(|authorized_at| now.checked_duration_since(authorized_at))
        .map(|elapsed| elapsed >= CONVERSATION_AUTHORIZATION_LEASE)
        .unwrap_or(true)
}

pub(super) async fn reauthorize_sandbox_subscriptions(
    app: &AppState,
    user_id: &str,
    socket: &mut WebSocket,
    subscriptions: &mut HashMap<String, Subscription>,
) -> Result<(), ()> {
    let now = Instant::now();
    let candidates = subscriptions
        .iter()
        .filter(|(_, subscription)| scoped_authorization_needs_refresh(subscription, now))
        .map(|(project_id, subscription)| (project_id.clone(), subscription.scope.clone()))
        .collect::<Vec<_>>();

    for (project_id, scope) in candidates {
        let allowed = match scope.as_ref() {
            Some(scope) if scope.project_id == project_id => matches!(
                app.auth
                    .authorize_project_event_subscription(
                        user_id,
                        &project_id,
                        Some(&scope.tenant_id),
                    )
                    .await,
                Ok(Some(resolved_tenant_id)) if resolved_tenant_id == scope.tenant_id
            ),
            _ => false,
        };
        if refresh_scoped_authorization(allowed, subscriptions, &project_id, Instant::now()) {
            continue;
        }
        send_json(
            socket,
            json!({
                "type": "error",
                "project_id": project_id,
                "data": {"message": "Access denied"},
            }),
        )
        .await?;
    }
    Ok(())
}

pub(super) async fn reauthorize_workspace_subscriptions(
    app: &AppState,
    user_id: &str,
    socket: &mut WebSocket,
    subscriptions: &mut HashMap<String, Subscription>,
) -> Result<(), ()> {
    let now = Instant::now();
    let candidates = subscriptions
        .iter()
        .filter(|(_, subscription)| scoped_authorization_needs_refresh(subscription, now))
        .map(|(workspace_id, subscription)| (workspace_id.clone(), subscription.scope.clone()))
        .collect::<Vec<_>>();

    for (workspace_id, scope) in candidates {
        let allowed = match scope.as_ref() {
            Some(scope) => {
                let workspace_access = app
                    .workspaces
                    .authorize_workspace_event_subscription(
                        user_id,
                        &workspace_id,
                        &scope.project_id,
                        Some(&scope.tenant_id),
                    )
                    .await;
                let project_access = app
                    .auth
                    .authorize_project_event_subscription(
                        user_id,
                        &scope.project_id,
                        Some(&scope.tenant_id),
                    )
                    .await;
                matches!(workspace_access, Ok(resolved_tenant_id) if resolved_tenant_id == scope.tenant_id)
                    && matches!(project_access, Ok(Some(resolved_tenant_id)) if resolved_tenant_id == scope.tenant_id)
            }
            None => false,
        };
        if refresh_scoped_authorization(allowed, subscriptions, &workspace_id, Instant::now()) {
            continue;
        }
        send_json(
            socket,
            json!({
                "type": "error",
                "workspace_id": workspace_id,
                "data": {"message": "Access denied"},
            }),
        )
        .await?;
    }
    Ok(())
}

pub(super) fn refresh_scoped_authorization(
    allowed: bool,
    subscriptions: &mut HashMap<String, Subscription>,
    subscription_id: &str,
    authorized_at: Instant,
) -> bool {
    if allowed {
        if let Some(scope) = subscriptions
            .get_mut(subscription_id)
            .and_then(|subscription| subscription.scope.as_mut())
        {
            scope.authorized_at = authorized_at;
            return true;
        }
    }
    subscriptions.remove(subscription_id);
    false
}

pub(super) fn scoped_authorization_needs_refresh(
    subscription: &Subscription,
    now: Instant,
) -> bool {
    subscription
        .scope
        .as_ref()
        .and_then(|scope| now.checked_duration_since(scope.authorized_at))
        .map(|elapsed| elapsed >= SCOPED_AUTHORIZATION_LEASE)
        .unwrap_or(true)
}
