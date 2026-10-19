use super::*;
use agistack_core::ports::ToolDefinition;
use std::sync::atomic::{AtomicUsize, Ordering};

#[derive(Default)]
struct ConnectorProbe {
    calls: AtomicUsize,
}
#[async_trait]
impl ToolHost for ConnectorProbe {
    fn list_tools(&self) -> Vec<String> {
        vec!["computer_connector_call".into()]
    }
    fn tool_definition(&self, name: &str) -> Option<ToolDefinition> {
        (name=="computer_connector_call").then(||ToolDefinition::new(name,"Declared connector",json!({agistack_adapters_cua::CONNECTOR_OPERATION_EFFECTS:agistack_adapters_cua::native_connector_operations()})))
    }
    async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok("{}".into())
    }
}

#[tokio::test]
async fn read_only_run_exposes_declared_reads_but_never_dispatches_mutations_or_unknown_operations()
{
    let (root, store, run, _) =
        super::tests::running_host(DesktopPermissionProfile::ReadOnly).unwrap();
    let probe = Arc::new(ConnectorProbe::default());
    let host = AuthorizedRunToolHost::new(probe.clone(), store, run);
    assert!(host
        .list_tools()
        .contains(&"computer_connector_call".into()));
    for connector in ["calendar", "contacts", "messages"] {
        host.call_with_content(
            "computer_connector_call",
            &json!({"provider":"native","connector":connector,"operation":"list","arguments":{}})
                .to_string(),
        )
        .await
        .unwrap();
    }
    for operation in ["create", "delete", "read_calendar_because_name_looks_safe"] {
        assert!(host
            .call(
                "computer_connector_call",
                &json!({"connector":"calendar","operation":operation,"arguments":{}}).to_string()
            )
            .await
            .is_err());
    }
    assert_eq!(probe.calls.load(Ordering::SeqCst), 3);
    std::fs::remove_dir_all(root).unwrap();
}

#[tokio::test]
async fn plan_mode_accepts_exact_declared_connector_reads_and_blocks_other_operations() {
    let (root, store, run, _) =
        super::tests::running_host(DesktopPermissionProfile::ReadOnly).unwrap();
    let probe = Arc::new(ConnectorProbe::default());
    let host = super::super::PlanModeToolHost::new(probe.clone(), store, run.conversation_id);
    assert!(host
        .list_tools()
        .contains(&"computer_connector_call".into()));
    host.call(
        "computer_connector_call",
        r#"{"connector":"calendar","operation":"list","arguments":{}}"#,
    )
    .await
    .unwrap();
    assert!(host
        .call_with_content(
            "computer_connector_call",
            r#"{"connector":"calendar","operation":"create","arguments":{}}"#
        )
        .await
        .is_err());
    assert_eq!(probe.calls.load(Ordering::SeqCst), 1);
    std::fs::remove_dir_all(root).unwrap();
}
