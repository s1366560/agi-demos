use std::sync::Arc;

use agistack_core::agent::tool_policy::{
    ToolExecutionPolicy, ToolPolicyContext, ToolPolicyDecision, ToolPolicyResult,
};
use futures::executor::block_on;
use serde_json::json;

use super::{
    super::{
        context::{event_store_v2, service_store_v2},
        parse_profile_snapshot_v2,
        tool_policy_adapter::GenerationToolExecutionPolicyV2,
        FiberPhaseV2, LoaderV2, PluginContractV2, ProfileEntryV2, ScopeKindV2, TrustKindV2,
    },
    *,
};

fn scope() -> ScopeV2 {
    ScopeV2 {
        kind: ScopeKindV2::Session,
        tenant_id: Some("tenant-a".into()),
        project_id: Some("project-a".into()),
        session_id: Some("session-a".into()),
    }
}

fn context() -> ContextV2 {
    let manifest: Value = serde_json::from_str(include_str!(
        "../../../../../config/plugin-manifests-v2/memstack-native-target-hosts.v2.json"
    ))
    .unwrap();
    let mut contract: PluginContractV2 = serde_json::from_value(
        manifest["modules"]
            .as_array()
            .unwrap()
            .iter()
            .find(|module| module["module_ref"] == "builtin://memstack/rust-server/generation-host")
            .unwrap()["contract"]
            .clone(),
    )
    .unwrap();
    contract.events.handles = contract.events.emits.clone();
    let events = contract
        .events
        .emits
        .iter()
        .map(|event| (event.event.clone(), event.clone()))
        .collect();
    let entry: ProfileEntryV2 = serde_json::from_value(json!({
        "entry_id":"policy", "plugin_ref":"policy", "module_ref":"builtin://test/policy", "parent_entry_id":null,
        "config":{}, "enabled":true,"inject":{},"isolate":{},"permissions":[],"quotas":{},"restart_policy":"hot-generation","scope":scope(),
    })).unwrap();
    let context = ContextV2::new(
        &entry,
        Arc::new(contract),
        Arc::new(events),
        service_store_v2(),
        event_store_v2(),
    );
    context.set_phase(FiberPhaseV2::Active);
    context
}

fn policy(context: &ContextV2) -> GenerationToolExecutionPolicyV2 {
    GenerationToolExecutionPolicyV2::new(
        Arc::new(TrustedToolPolicyV2::new(context.clone())),
        scope(),
        "operation-a".into(),
        "digest-a".into(),
    )
}

fn call() -> ToolPolicyContext<'static> {
    ToolPolicyContext {
        session_id: "session-a:message",
        round: 0,
        tool: "write",
    }
}

#[test]
fn declared_waterfalls_rewrite_validate_and_preserve_conversation_scope() {
    block_on(async {
        let context = context();
        context
            .on(TOOLS_BEFORE_EXECUTE_EVENT_V2, |mut value| async move {
                assert_eq!(value["session_id"], "session-a");
                value["arguments"] = json!({"path":"safe"});
                Ok(value)
            })
            .unwrap();
        context
            .on(TOOLS_RESULT_TRANSFORM_EVENT_V2, |mut value| async move {
                value["result"] =
                    json!({"output":"safe", "is_error":true, "metadata":{"redacted":true}});
                Ok(value)
            })
            .unwrap();
        let policy = policy(&context);
        let schema = json!({"type":"object", "required":["path"], "properties":{"path":{"const":"safe"}}, "additionalProperties":false});
        let decision = policy
            .before_execute(&call(), r#"{"path":"original"}"#, Some(&schema))
            .await
            .unwrap();
        assert!(
            matches!(decision, ToolPolicyDecision::Allow { input_json } if input_json == r#"{"path":"safe"}"#)
        );
        let result = policy
            .transform_result(
                &call(),
                ToolPolicyResult {
                    output: "private".into(),
                    is_error: false,
                    metadata: json!({}),
                    media: Vec::new(),
                },
            )
            .await
            .unwrap();
        assert_eq!(result.output, "safe");
        assert!(result.is_error);
        assert_eq!(result.metadata, json!({"redacted":true}));
        let invalid = json!({"type":"object","properties":{"path":{"const":"other"}}});
        assert!(policy
            .before_execute(&call(), "{}", Some(&invalid))
            .await
            .is_err());
    });
}

#[test]
fn identity_mutation_and_disposed_generation_fail_closed() {
    block_on(async {
        let context = context();
        context
            .on(TOOLS_BEFORE_EXECUTE_EVENT_V2, |mut value| async move {
                value["operation_id"] = json!("forged");
                Ok(value)
            })
            .unwrap();
        assert!(policy(&context)
            .before_execute(&call(), "{}", None)
            .await
            .is_err());
        context.set_phase(FiberPhaseV2::Disposed);
        assert!(policy(&context)
            .before_execute(&call(), "{}", None)
            .await
            .is_err());
    });
}

#[test]
fn result_block_discards_private_output() {
    block_on(async {
        let context = context();
        context
            .on(TOOLS_RESULT_TRANSFORM_EVENT_V2, |mut value| async move {
                value["decision"] = json!({"kind":"block"});
                Ok(value)
            })
            .unwrap();
        let result = policy(&context)
            .transform_result(
                &call(),
                ToolPolicyResult {
                    output: "private".into(),
                    is_error: false,
                    metadata: json!({}),
                    media: Vec::new(),
                },
            )
            .await
            .unwrap();
        assert_eq!(result.output, "Tool result withheld by policy");
        assert!(result.is_error);
    });
}

#[test]
fn non_builtin_policy_handler_is_rejected_before_activation() {
    block_on(async {
        let mut snapshot = parse_profile_snapshot_v2(include_str!(
            "../../../../../shared/fixtures/platform-plugin-profile.v2.json"
        ))
        .unwrap();
        snapshot.manifests[0].trust = TrustKindV2::Signed;
        snapshot.manifests[0].modules[0].contract.events.handles[0].event =
            TOOLS_BEFORE_EXECUTE_EVENT_V2.into();
        let result = LoaderV2::new([]).stage(snapshot).await;
        assert!(
            matches!(result, Err(RuntimeV2Error::Module(message)) if message == "tool execution policies require trusted bundled modules")
        );
    });
}
