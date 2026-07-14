use agistack_adapters_postgres::{AutomationPayload, AutomationRunContext, AutomationRunStatus};
use agistack_plugin_host::{Tool, Trust};
use chrono::{DateTime, Duration, Utc};

use super::*;

struct ClassifiedTool {
    name: &'static str,
    access: ToolAccessClass,
}

#[async_trait]
impl Tool for ClassifiedTool {
    fn name(&self) -> &str {
        self.name
    }

    fn version(&self) -> &str {
        "1.0.0"
    }

    fn trust(&self) -> Trust {
        Trust::Builtin
    }

    fn access_class(&self) -> ToolAccessClass {
        self.access
    }

    async fn invoke(&self, input_json: &str) -> CoreResult<String> {
        Ok(input_json.to_string())
    }
}

fn now() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-07-14T10:00:00Z")
        .expect("fixed time")
        .with_timezone(&Utc)
}

fn lease() -> AutomationRunLease {
    AutomationRunLease {
        context: AutomationRunContext {
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            job_id: "job-1".to_string(),
            run_id: "run-1".to_string(),
            runtime_execution_id: "run-1".to_string(),
            conversation_id: "conversation-1".to_string(),
            actor_user_id: "user-1".to_string(),
            actor_api_key_id: None,
            payload: AutomationPayload::AgentTurn {
                message: "run".to_string(),
            },
            timeout_seconds: 60,
            status: AutomationRunStatus::Running,
        },
        runtime_revision: 1,
        lease_owner: "runtime-worker".to_string(),
        lease_token: "runtime-lease".to_string(),
        lease_expires_at: now() + Duration::seconds(30),
        deadline_at: now() + Duration::seconds(60),
    }
}

#[tokio::test]
async fn scoped_host_lists_and_invokes_only_declared_pure_tools() {
    let registry = HotPlugRegistry::new();
    registry.register_tool(Arc::new(ClassifiedTool {
        name: "pure",
        access: ToolAccessClass::Pure,
    }));
    registry.register_tool(Arc::new(ClassifiedTool {
        name: "read",
        access: ToolAccessClass::ScopedRead,
    }));
    registry.register_tool(Arc::new(ClassifiedTool {
        name: "write",
        access: ToolAccessClass::Mutating,
    }));
    let host = RegistryAutomationToolHostFactory::new(registry)
        .for_run(&lease())
        .expect("valid run authority");

    assert_eq!(host.list_tools(), vec!["pure"]);
    assert_eq!(
        host.call("pure", r#"{"value":1}"#).await.unwrap(),
        r#"{"value":1}"#
    );
    assert!(host.call("read", "{}").await.is_err());
    assert!(host.call("write", "{}").await.is_err());
}

#[test]
fn mismatched_runtime_execution_id_fails_before_host_creation() {
    let mut invalid = lease();
    invalid.context.runtime_execution_id = "another-run".to_string();
    let factory = RegistryAutomationToolHostFactory::new(HotPlugRegistry::new());

    assert!(factory.for_run(&invalid).is_err());
}

#[tokio::test]
async fn hot_swap_to_stronger_access_class_is_checked_again_at_call_time() {
    let registry = HotPlugRegistry::new();
    registry.register_tool(Arc::new(ClassifiedTool {
        name: "dynamic",
        access: ToolAccessClass::Pure,
    }));
    let host = RegistryAutomationToolHostFactory::new(registry.clone())
        .for_run(&lease())
        .expect("valid run authority");
    assert_eq!(host.list_tools(), vec!["dynamic"]);

    registry.replace_tool(Arc::new(ClassifiedTool {
        name: "dynamic",
        access: ToolAccessClass::Mutating,
    }));

    assert!(host.call("dynamic", "{}").await.is_err());
}
