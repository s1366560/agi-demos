//! Policy runs around the actual authority host and before persisted observation.
use std::sync::{Arc, Mutex};

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, ScriptedLlm};
use agistack_core::{
    agent::{
        tool_policy::{
            ToolExecutionPolicy, ToolPolicyContext, ToolPolicyDecision, ToolPolicyResult,
        },
        types::{HitlKind, HitlRequest},
        ReActObserver,
    },
    ports::{CoreError, CoreResult, ToolHost},
    AgentAction, ReActEngine, SessionStatus,
};
use async_trait::async_trait;
use futures::executor::block_on;
use serde_json::{json, Value};

#[derive(Default)]
struct AuthorityHost {
    inputs: Mutex<Vec<String>>,
}
#[async_trait]
impl ToolHost for AuthorityHost {
    fn list_tools(&self) -> Vec<String> {
        vec!["write".into()]
    }
    async fn call(&self, _: &str, input: &str) -> CoreResult<String> {
        self.inputs.lock().unwrap().push(input.into());
        if input != r#"{"path":"allowed"}"# {
            return Err(CoreError::Tool("authority denied rewritten path".into()));
        }
        Ok("private raw result".into())
    }
}

struct Policy {
    action: &'static str,
    transform_failure: bool,
}
#[async_trait]
impl ToolExecutionPolicy for Policy {
    async fn before_execute(
        &self,
        _: &ToolPolicyContext<'_>,
        _: &str,
        _: Option<&Value>,
    ) -> CoreResult<ToolPolicyDecision> {
        Ok(match self.action {
            "deny" => ToolPolicyDecision::Deny {
                reason: "denied".into(),
            },
            "cancel" => ToolPolicyDecision::Cancel {
                reason: "cancelled".into(),
            },
            "ask" => ToolPolicyDecision::Ask {
                request: HitlRequest::new("request", HitlKind::Permission, "Allow write?"),
            },
            "invalid_authority" => ToolPolicyDecision::Allow {
                input_json: r#"{"path":"forbidden"}"#.into(),
            },
            _ => ToolPolicyDecision::Allow {
                input_json: r#"{"path":"allowed"}"#.into(),
            },
        })
    }
    async fn transform_result(
        &self,
        _: &ToolPolicyContext<'_>,
        result: ToolPolicyResult,
    ) -> CoreResult<ToolPolicyResult> {
        if self.transform_failure {
            return Err(CoreError::Tool("transform failed".into()));
        }
        Ok(ToolPolicyResult {
            output: "safe transformed result".into(),
            is_error: result.is_error,
            metadata: json!({"redacted":true}),
            media: Vec::new(),
        })
    }
}

#[derive(Default)]
struct Observer {
    results: Mutex<Vec<String>>,
}
#[async_trait]
impl ReActObserver for Observer {
    async fn on_tool_result(
        &self,
        _: &str,
        _: u64,
        _: &str,
        _: &str,
        output: &str,
    ) -> CoreResult<()> {
        self.results.lock().unwrap().push(output.into());
        Ok(())
    }
    async fn on_tool_error(
        &self,
        _: &str,
        _: u64,
        _: &str,
        _: &str,
        error: &CoreError,
    ) -> CoreResult<()> {
        self.results.lock().unwrap().push(error.to_string());
        Ok(())
    }
}

fn engine(host: Arc<AuthorityHost>, action: &'static str, transform_failure: bool) -> ReActEngine {
    ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![
            AgentAction::CallTool {
                tool: "write".into(),
                input_json: r#"{"path":"original"}"#.into(),
            },
            AgentAction::Finish {
                answer: "done".into(),
            },
        ])),
        host,
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(FixedClock(0)),
    )
    .with_tool_policy(Arc::new(Policy {
        action,
        transform_failure,
    }))
}

#[test]
fn rewritten_arguments_reach_real_authorization_and_only_transformed_output_is_observed() {
    for action in ["allow", "invalid_authority"] {
        let host = Arc::new(AuthorityHost::default());
        let observer = Arc::new(Observer::default());
        let state = block_on(engine(host.clone(), action, false).run_observed(
            "session",
            "goal",
            None,
            observer.clone(),
        ))
        .unwrap();
        assert_eq!(host.inputs.lock().unwrap().len(), 1);
        assert_eq!(
            state.completed_tool_calls[0].output_json,
            "safe transformed result"
        );
        assert_eq!(
            state.completed_tool_calls[0].metadata,
            json!({"redacted":true})
        );
        assert_eq!(
            state.completed_tool_calls[0].failed,
            action == "invalid_authority"
        );
        assert!(!serde_json::to_string(&state)
            .unwrap()
            .contains("private raw result"));
        assert!(observer.results.lock().unwrap()[0].contains("safe transformed result"));
    }
}

#[test]
fn deny_cancel_and_ask_never_invoke_the_tool() {
    for (action, expected) in [
        ("deny", SessionStatus::Finished),
        ("cancel", SessionStatus::Cancelled),
        ("ask", SessionStatus::AwaitingInput),
    ] {
        let host = Arc::new(AuthorityHost::default());
        let state =
            block_on(engine(host.clone(), action, false).run("session", "goal", None)).unwrap();
        assert!(host.inputs.lock().unwrap().is_empty());
        assert_eq!(state.status, expected);
    }
}

#[test]
fn failed_result_transform_withholds_output_and_checkpoints_the_completed_side_effect() {
    let host = Arc::new(AuthorityHost::default());
    let engine = engine(host.clone(), "allow", true);
    let state = block_on(engine.run("session", "goal", None)).unwrap();
    assert!(state.completed_tool_calls[0].failed);
    assert_eq!(
        state.completed_tool_calls[0].output_json,
        "Tool result policy failed; result withheld"
    );
    block_on(engine.run("session", "goal", None)).unwrap();
    assert_eq!(host.inputs.lock().unwrap().len(), 1);
}
