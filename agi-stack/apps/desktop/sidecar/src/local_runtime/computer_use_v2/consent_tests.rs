//! Exercise production hosts and management with private mock IPC, never OS connectors.
use super::*;
use crate::local_runtime::knowledge_authority_v2::agent_access::{self, RunAuthorization};
use agistack_core::agent::tool_policy::ToolPolicyContext;
#[path = "consent_preflight_tests.rs"]
mod consent_preflight_tests;
#[path = "consent_provenance_tests.rs"]
mod consent_provenance_tests;
#[path = "hitl_validation_tests.rs"]
mod hitl_validation_tests;
#[path = "local_stop_dispatch_tests.rs"]
mod local_stop_dispatch_tests;
#[path = "locked_use_consent_tests.rs"]
mod locked_use_consent_tests;

struct Fixture {
    state: Arc<LocalRuntimeState>,
    owner: Owner,
    conversation: LocalConversation,
    authorization: Arc<RunAuthorization>,
    helper: management_lifecycle_tests::Helper,
}
impl Fixture {
    async fn new() -> Self {
        let token = "cua-native-consent-fixture";
        let state = crate::local_runtime::tests::test_state(token);
        cloud_tests::publish_factory(&state, true).await;
        let auth = state
            .session_store
            .validate_session_credential(token, chrono::Utc::now().timestamp_millis())
            .unwrap()
            .unwrap();
        let owner = Owner {
            user_id: auth.user.user_id.clone(),
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: auth.workspace.project_id.clone(),
            device_id: state.session_store.installation_id().into(),
        };
        store::update(
            &state.session_store.connection().unwrap(),
            &owner,
            0,
            "enable",
            None,
        )
        .unwrap();
        let helper = management_lifecycle_tests::Helper::new(false);
        assert!(state.computer_use.client.set(helper.client.clone()).is_ok());
        let conversation = LocalConversation {
            id: "native-consent-conversation".into(),
            tenant_id: owner.tenant_id.clone(),
            project_id: owner.project_id.clone(),
            title: "Fixture".into(),
            workspace_id: None,
            capability_mode: Default::default(),
            current_mode: crate::local_runtime::ConversationRunMode::Plan,
            created_at: crate::local_runtime::now_iso(),
            updated_at: crate::local_runtime::now_iso(),
        };
        state
            .session_store
            .insert_conversation(&conversation)
            .unwrap();
        let authorization = RunAuthorization::capture(
            auth,
            Some(cloud::factory_lease(&state, &owner).unwrap()),
            &conversation,
            "native-message",
            None,
        )
        .unwrap();
        Self {
            state,
            owner,
            conversation,
            authorization,
            helper,
        }
    }
    async fn call(&self, host: &dyn ToolHost, round: u64, input: Value) -> CoreResult<Value> {
        let context = ToolPolicyContext {
            session_id: "logical-engine-session",
            round,
            tool: "computer_connector_call",
        };
        let result = call_identity::scope(
            &context,
            host.call_with_content(context.tool, &input.to_string()),
        )
        .await?;
        Ok(serde_json::from_str(&result.output_json).unwrap())
    }
    async fn grant(&self, id: &Value, scope: &str) -> Result<Value, String> {
        api::operation(
            &self.state,
            &self.owner,
            serde_json::from_value(json!({"action":"grant","request_id":id,"scope":scope}))
                .unwrap(),
        )
        .await
    }
}

#[tokio::test]
async fn old_local_host_cannot_resolve_or_dispatch_after_generic_v2_factory_disable() {
    let fixture = Fixture::new().await;
    agent_access::scope(Some(fixture.authorization.clone()), async {
        let host = tool_host(&fixture.state, &fixture.conversation, None).unwrap();
        cloud_tests::publish_factory(&fixture.state, false).await;
        assert!(host
            .call("computer_get_app_state", r#"{"app":"fixture"}"#)
            .await
            .unwrap_err()
            .to_string()
            .contains("cua_factory_disabled"));
        assert!(
            !fixture.helper.root.join("requests").exists(),
            "disabled old host must not even resolve an application"
        );
    })
    .await;
    fixture.helper.client.shutdown().await;
}

#[tokio::test]
async fn local_connector_read_grants_never_cover_writes_and_exact_once_is_consumed() {
    let fixture = Fixture::new().await;
    agent_access::scope(Some(fixture.authorization.clone()), async {
        let host = tool_host(&fixture.state, &fixture.conversation, None).unwrap();
        let read = json!({"connector":"calendar","operation":"list","arguments":{}});
        let first = fixture.call(host.as_ref(), 1, read.clone()).await.unwrap();
        let schema=&first["decision_context_schema"];
        assert_eq!(schema["required"],json!(["action","target","data","reason","risk","reversibility","scope","evidence"]));
        assert_eq!(schema["properties"]["reversibility"]["required"],json!(["mode"]));
        assert_eq!(schema["properties"]["target"]["properties"]["id"]["const"],first["request"]["request_id"]);
        assert!(schema["properties"]["risk"]["properties"]["level"].get("default").is_none(),"the model judges risk; the host only provides its enum");
        let mut agent_decision=json!({"action":{"name":"computer_connector_call","label":"Read fixture calendar"},"target":{"kind":"computer_app","id":first["request"]["request_id"]},"data":{"summary":"Mock calendar read"},"reason":"Agent provided fixture rationale","risk":{"level":"medium","rationale":"Agent provided fixture assessment"},"reversibility":{"mode":"partial","recovery":"Agent provided recovery description"},"scope":{"kind":"account","ids":[first["request"]["app"]]},"evidence":[{"kind":"native_request","id":first["request"]["request_id"],"label":"Fixture native consent"}]});
        assert!(serde_json::from_value::<agistack_core::agent::types::DecisionContext>(agent_decision.clone()).unwrap().is_complete());
        agent_decision.as_object_mut().unwrap().remove("reversibility");
        assert!(serde_json::from_value::<agistack_core::agent::types::DecisionContext>(agent_decision).is_err());
        assert_eq!(first["request"]["app"], "connector:native:calendar");
        assert_eq!(first["request"]["capability"], "calendar");
        fixture
            .grant(&first["request"]["request_id"], "always")
            .await
            .unwrap();
        assert!(fixture
            .call(host.as_ref(), 2, read)
            .await
            .unwrap()
            .get("error")
            .is_none());
        let write =
            json!({"connector":"calendar","operation":"create","arguments":{"title":"Fixture"}});
        let pending = fixture.call(host.as_ref(), 3, write.clone()).await.unwrap();
        assert_eq!(pending["scopes"], json!(["once"]));
        assert_eq!(pending["request"]["capability"], "connector_action");
        let id = &pending["request"]["request_id"];
        for broad in ["session", "always"] {
            assert_eq!(
                fixture.grant(id, broad).await.unwrap_err(),
                "cua_action_requires_once"
            );
        }
        fixture.grant(id, "once").await.unwrap();
        let changed =
            json!({"connector":"calendar","operation":"create","arguments":{"title":"Other"}});
        let unmatched = fixture.call(host.as_ref(), 4, changed).await.unwrap();
        assert_ne!(unmatched["request"]["request_id"], *id);
        assert!(fixture
            .call(host.as_ref(), 5, write.clone())
            .await
            .unwrap()
            .get("error")
            .is_none());
        let second = fixture.call(host.as_ref(), 6, write).await.unwrap();
        assert_eq!(second["error"], "cua_permission_required");
        assert_ne!(second["request"]["request_id"], *id);
        let contacts = fixture
            .call(
                host.as_ref(),
                7,
                json!({"connector":"contacts","operation":"list","arguments":{}}),
            )
            .await
            .unwrap();
        assert_eq!(contacts["request"]["app"], "connector:native:contacts");
        assert_ne!(
            contacts["request"]["identity_digest"],
            first["request"]["identity_digest"]
        );
        assert_eq!(
            fixture
                .helper
                .requests()
                .iter()
                .filter(|request| request["method"] == "connector_call")
                .count(),
            2
        );
    })
    .await;
    fixture
        .state
        .computer_use
        .stop_owner(&fixture.state, &fixture.owner, "revoked")
        .await;
}
