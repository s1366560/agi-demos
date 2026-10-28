use super::*;
use crate::local_runtime::{
    authorized_tool_host::AuthorizedRunToolHost,
    execution_profile::{ExecutionProfile, ProfiledToolHost},
    knowledge_authority_v2::agent_access::{self, RunAuthorization},
    local_plugin_tool_host_v2::identity::{child_scope, ChildIdentityV2},
    resource_registry::ManagedResourceKind,
};
use agistack_core::agent::tool_policy::ToolPolicyContext;
use std::sync::atomic::{AtomicUsize, Ordering};

struct NativeFixture(Arc<AtomicUsize>);
#[async_trait]
impl ToolHost for NativeFixture {
    fn list_tools(&self) -> Vec<String> {
        vec!["computer_list_apps".into(), "computer_click".into()]
    }
    async fn call(&self, tool: &str, _: &str) -> CoreResult<String> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Ok(json!({"tool":tool}).to_string())
    }
}

async fn child_call(
    host: &dyn ToolHost,
    child: ChildIdentityV2,
    code: &str,
) -> CoreResult<ToolResult> {
    let context = ToolPolicyContext {
        session_id: &child.execution_id,
        round: 1,
        tool: "cua_repl_js",
    };
    child_scope(
        child.clone(),
        call_identity::scope(
            &context,
            host.call_with_content("cua_repl_js", &json!({"code":code}).to_string()),
        ),
    )
    .await
}

#[tokio::test]
async fn local_child_repl_uses_its_live_profile_and_never_parent_or_sibling_bindings() {
    let (state, conversation, run, root) = test_support::state("repl-child-test");
    let wire: Value = serde_json::from_str(include_str!(
        "../../../../../../../shared/profiles/memstack-default-bootstrap.v2.json"
    ))
    .unwrap();
    let snapshot = agistack_plugin_host::parse_profile_snapshot_v2(&wire.to_string()).unwrap();
    let generation = crate::local_runtime::platform_plugin_sync_v2::desktop_loader(None, None)
        .stage(snapshot.clone())
        .await
        .unwrap();
    state
        .platform_plugin_authority_v2
        .publish_local_baseline(&snapshot, &wire, generation)
        .await;
    let auth = state
        .session_store
        .validate_session_credential("repl-child-test", chrono::Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    let authorization = RunAuthorization::capture(
        auth,
        Some(Arc::new(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        )),
        &conversation,
        &run.message_id,
        Some(&run.id),
    )
    .unwrap();
    agent_access::scope(Some(authorization), async {
    let parent = state
        .claim_agent_run(&conversation.id, Some(&run.id))
        .unwrap();
    let parent_profile = state.execution_profile(&conversation).unwrap();
    let agent = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Agent,
            "project",
            &conversation.project_id,
            &parent_profile.agent.id,
        )
        .unwrap()
        .unwrap();
    let resource = json!({"id":"repl-child","name":"repl-child","status":"active","enabled":true,
        "project_id":conversation.project_id,"allowed_tools":["cua_repl_js","cua_repl_reset","computer_list_apps"],
        "allowed_skills":["*"],"allowed_mcp_servers":[]});
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::SubAgent,
            "tenant",
            &conversation.tenant_id,
            "repl-child",
            "active",
            None,
            resource.clone(),
            1,
        )
        .unwrap();
    let profile =
        ExecutionProfile::resolve(&parent_profile.agent.id, &agent, None, Some(&resource)).unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let inner: Arc<dyn ToolHost> = Arc::new(NativeFixture(calls.clone()));
    let profiled: Arc<dyn ToolHost> = Arc::new(ProfiledToolHost::new(inner.clone(), &profile));
    let authorized: Arc<dyn ToolHost> = Arc::new(AuthorizedRunToolHost::new(
        profiled,
        state.session_store.clone(),
        run.clone(),
    ));
    let host = wrap_tools(&state, authorized, &conversation, &run, &profile, None);
    let parent_host = wrap_tools(&state, inner, &conversation, &run, &parent_profile, None);
    let child = |id: &str| ChildIdentityV2 {
        execution_id: id.into(),
        subagent_id: "repl-child".into(),
        run_id: run.id.clone(),
        revision: run.revision,
    };
    for id in ["child-a", "child-b"] {
        state
            .subagent_controls
            .register(
                id,
                &conversation.id,
                &run,
                "repl-child",
                &parent_profile.agent.id,
                parent.clone(),
            )
            .unwrap();
    }
    assert!(host.list_tools().contains(&"cua_repl_js".into()));
    assert!(host
        .call_with_content("cua_repl_js", "{\"code\":\"1\"}")
        .await
        .unwrap_err()
        .to_string()
        .contains("child_identity"));
    let first=child_call(&*host,child("child-a"),"let childValue=42; await nodeRepl.rpc('computer.call',{tool:'computer_list_apps',arguments:{}})").await.unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&first.output_json).unwrap()["value"]["tool"],
        "computer_list_apps"
    );
    let sibling = child_call(&*host, child("child-b"), "typeof childValue")
        .await
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&sibling.output_json).unwrap()["value"],
        "undefined"
    );
    let retained = child_call(&*host, child("child-a"), "childValue")
        .await
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&retained.output_json).unwrap()["value"],
        42
    );
    let forbidden = child_call(
        &*host,
        child("child-a"),
        "await nodeRepl.rpc('computer.call',{tool:'computer_click',arguments:{}})",
    )
    .await
    .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&forbidden.output_json).unwrap()["ok"],
        false
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(child_call(&*parent_host, child("child-a"), "1")
        .await
        .unwrap_err()
        .to_string()
        .contains("parent_authority_forbidden"));
    state.subagent_controls.complete("child-a");
    assert!(state.subagent_controls.is_terminal("child-a"));
    assert!(child_call(&*host, child("child-a"), "1")
        .await
        .unwrap_err()
        .to_string()
        .contains("child_authority_revoked"));
    let sibling = child_call(&*host, child("child-b"), "2").await.unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&sibling.output_json).unwrap()["value"],
        2
    );
    let mut narrowed = resource;
    narrowed["allowed_tools"] = json!([]);
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::SubAgent,
            "tenant",
            &conversation.tenant_id,
            "repl-child",
            "active",
            None,
            narrowed,
            2,
        )
        .unwrap();
    assert!(child_call(&*host, child("child-b"), "3")
        .await
        .unwrap_err()
        .to_string()
        .contains("permissions_changed"));
    state.cua_repl.shutdown();
    }).await;
    state.platform_plugin_authority_v2.deactivate().await;
    drop(state);
    std::fs::remove_dir_all(root).unwrap();
}
