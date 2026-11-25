//! Conversation UI approval preferences, independent from runtime permission grants.
use serde::{Deserialize, Deserializer};

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum ApprovalMode {
    Ask,
    AutoEdit,
    FullAccess,
}

impl ApprovalMode {
    pub(super) fn as_str(self) -> &'static str {
        match self {
            Self::Ask => "ask",
            Self::AutoEdit => "auto_edit",
            Self::FullAccess => "full_access",
        }
    }
}

pub(super) fn deserialize_mode<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<ApprovalMode>, D::Error> {
    ApprovalMode::deserialize(deserializer).map(Some)
}

pub(super) fn deserialize_present<'de, D, T>(deserializer: D) -> Result<Option<Option<T>>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(deserializer).map(Some)
}

#[cfg(test)]
mod tests {
    use super::super::{session_store::DesktopSessionStore, ConversationConfigBody};

    #[cfg(feature = "legacy-business")]
    #[tokio::test]
    async fn approval_config_patch_preserves_model_route_and_renders_saved_mode() {
        use axum::{
            body::Body,
            http::{Request, StatusCode},
        };
        use tower::ServiceExt;
        let state = super::super::tests::test_state("approval-secret");
        super::super::tests::seed_plan_conversation(&state, "approval-route");
        let route = super::super::LlmRouteTarget {
            provider_id: "unchanged-provider".into(),
            model_id: "unchanged-model".into(),
        };
        state
            .session_store
            .update_conversation_llm_route("approval-route", Some(&route), "now")
            .expect("existing route");
        let app = super::super::local_router(state.clone());
        for mode in ["full_access", "ask"] {
            let response = app.clone().oneshot(Request::builder()
                .method("PATCH")
                .uri("/api/v1/agent/conversations/approval-route/config?project_id=local-project&tenant_id=local")
                .header("authorization", "Bearer approval-secret")
                .header("content-type", "application/json")
                .body(Body::from(serde_json::json!({"approval_mode":mode}).to_string()))
                .expect("request")).await.expect("response");
            assert_eq!(response.status(), StatusCode::OK);
            let bytes = axum::body::to_bytes(response.into_body(), 1024 * 1024)
                .await
                .expect("body");
            let value: serde_json::Value = serde_json::from_slice(&bytes).expect("json");
            assert_eq!(value["agent_config"]["approval_mode"], mode);
            assert_eq!(
                value["agent_config"]["llm_route_override"]["model_id"],
                "unchanged-model"
            );
        }
    }

    #[test]
    fn approval_config_survives_reopen_without_changing_model_route() {
        let path =
            std::env::temp_dir().join(format!("approval-config-{}.db", uuid::Uuid::new_v4()));
        {
            let store = DesktopSessionStore::open(&path).expect("store");
            let connection = store.connection().expect("connection");
            connection.execute(
                "INSERT INTO desktop_conversations(id,project_id,updated_at,value_json) VALUES ('approval','project','now','{}')", [],
            ).expect("fixture conversation");
            drop(connection);
            assert_eq!(
                store.conversation_approval_mode("approval").expect("read"),
                None
            );
            let route = super::super::LlmRouteTarget {
                provider_id: "provider".into(),
                model_id: "model".into(),
            };
            store
                .update_conversation_llm_route("approval", Some(&route), "now")
                .expect("route");
            for mode in [super::ApprovalMode::FullAccess, super::ApprovalMode::Ask] {
                store
                    .update_conversation_approval_mode("approval", mode)
                    .expect("save mode");
            }
        }
        let store = DesktopSessionStore::open(&path).expect("reopen");
        assert_eq!(
            store
                .conversation_approval_mode("approval")
                .expect("mode")
                .as_deref(),
            Some("ask")
        );
        assert_eq!(
            store
                .conversation_llm_route("approval")
                .expect("route")
                .expect("route preserved")
                .model_id,
            "model"
        );
        drop(store);
        std::fs::remove_file(path).expect("remove fixture");
    }

    #[test]
    fn local_hitl_accepts_outer_approval_mode_without_trusting_response_markers() {
        let body: super::super::HitlResponseBody = serde_json::from_value(serde_json::json!({
            "request_id":"request", "hitl_type":"permission", "approval_mode":"full_access",
            "response_data":{"action":"allow","granted":true,"scope":"once"},
            "expected_revision":1,"idempotency_key":"local-auto",
        }))
        .expect("automatic preference is valid outer metadata");
        assert_eq!(body.response_data["granted"], true);
        assert!(body.response_data.get("auto_approved").is_none());
    }

    #[test]
    fn approval_config_validates_modes_and_preserves_route_presence() {
        for mode in ["ask", "auto_edit", "full_access"] {
            let body: ConversationConfigBody = serde_json::from_value(serde_json::json!({
                "approval_mode": mode,
            }))
            .expect("valid approval mode");
            assert_eq!(body.approval_mode.expect("present").as_str(), mode);
            assert!(body.llm_model_override.is_none());
            assert!(body.llm_route_override.is_none());
        }
        for mode in [
            serde_json::Value::Null,
            serde_json::json!("automatic"),
            serde_json::json!(true),
        ] {
            assert!(
                serde_json::from_value::<ConversationConfigBody>(serde_json::json!({
                    "approval_mode": mode,
                }))
                .is_err()
            );
        }
        let clear: ConversationConfigBody =
            serde_json::from_str(r#"{"llm_model_override":null,"llm_route_override":null}"#)
                .expect("explicit route clear");
        assert_eq!(clear.llm_model_override, Some(None));
        assert!(matches!(clear.llm_route_override, Some(None)));
    }
}
