//! Integration tests for the CLI-backend harness. They spawn a real fixture
//! subprocess (`fixture_echo`, built by this crate) so the JSON stdin/stdout
//! round-trip is exercised end to end — the proof that a *second, non-embedded*
//! harness family works under the same registry as the embedded loop.

use std::sync::Arc;

use agistack_adapters_cli_harness::CliBackendHarness;
use agistack_core::agent::{
    HarnessCtx, PreparedAttempt, RuntimeHarness, RuntimePlan, SelectionReason, SessionStatus,
};
use agistack_core::ports::{CoreError, CoreResult};
use async_trait::async_trait;
use futures::executor::block_on;

/// Path to the fixture subprocess Cargo builds for this crate.
const FIXTURE: &str = env!("CARGO_BIN_EXE_fixture_echo");

/// A trivial in-process fallback harness (stands in for the embedded ReAct loop,
/// which would need a full engine to construct). Supports any ctx at priority 0.
struct InlineFallback;

#[async_trait]
impl RuntimeHarness for InlineFallback {
    fn runtime_id(&self) -> &str {
        "inline"
    }
    fn supports(&self, _ctx: &HarnessCtx) -> Option<u32> {
        Some(0)
    }
    async fn run_attempt(
        &self,
        attempt: PreparedAttempt,
    ) -> CoreResult<agistack_core::agent::TurnOutcome> {
        let mut session = agistack_core::agent::SessionState::new(
            &attempt.session_id,
            &attempt.goal,
            attempt.project_id.as_deref(),
        );
        session.answer = Some("inline".into());
        session.status = SessionStatus::Finished;
        Ok(agistack_core::agent::TurnOutcome {
            runtime_id: "inline".into(),
            session,
        })
    }
}

fn cli_backend(tools: &[&str]) -> CliBackendHarness {
    CliBackendHarness::new(
        "codex",
        FIXTURE,
        Vec::<String>::new(),
        Some("anthropic"),
        10,
        tools.iter().map(|s| s.to_string()),
    )
}

#[test]
fn registry_picks_cli_backend_for_pinned_provider_else_fallback() {
    let mut reg = agistack_core::agent::HarnessRegistry::new(Arc::new(InlineFallback));
    reg.register(Arc::new(cli_backend(&["read"])));

    // Provider the CLI backend handles -> auto-selected over the fallback.
    let (h, reason) = reg.select(&HarnessCtx::new("anthropic", "claude"));
    assert_eq!(h.runtime_id(), "codex");
    assert_eq!(reason, SelectionReason::Auto);

    // A provider it does not handle -> universal fallback.
    let (h, reason) = reg.select(&HarnessCtx::new("openai", "gpt"));
    assert_eq!(h.runtime_id(), "inline");
    assert_eq!(reason, SelectionReason::Fallback);
}

#[test]
fn round_trips_prepared_attempt_through_subprocess() {
    let harness = cli_backend(&["read", "write"]);
    let attempt = PreparedAttempt::new(
        "s1",
        "summarize the repo",
        Some("p1"),
        HarnessCtx::new("anthropic", "claude"),
    );
    let outcome = block_on(harness.run_attempt(attempt)).unwrap();

    assert_eq!(outcome.runtime_id, "codex");
    assert_eq!(outcome.session.status, SessionStatus::Finished);
    let answer = outcome.session.answer.unwrap();
    // The fixture echoes the goal and the advertised tools back.
    assert!(answer.contains("summarize the repo"), "answer: {answer}");
    assert!(answer.contains("read,write"), "answer: {answer}");
}

#[test]
fn host_runtime_plan_normalizes_tool_aliases_before_dispatch() {
    // Advertise a legacy alias; the host RuntimePlan canonicalizes it to `read`
    // before the CLI ever sees it (host prepares / harness executes).
    let harness = cli_backend(&["legacy_read", "write"]);
    let plan = Arc::new(RuntimePlan::new().with_alias("legacy_read", "read"));
    let attempt = PreparedAttempt::new("s2", "go", None, HarnessCtx::new("anthropic", "claude"))
        .with_runtime_plan(plan);

    let outcome = block_on(harness.run_attempt(attempt)).unwrap();
    let answer = outcome.session.answer.unwrap();
    assert!(answer.contains("read,write"), "answer: {answer}");
    assert!(!answer.contains("legacy_read"), "alias leaked: {answer}");
}

#[test]
fn nonzero_exit_is_classified_as_failed() {
    let harness = cli_backend(&["read"]);
    // The fixture exits 7 for this sentinel goal.
    let attempt =
        PreparedAttempt::new("s3", "__fail__", None, HarnessCtx::new("anthropic", "claude"));
    let outcome = block_on(harness.run_attempt(attempt)).unwrap();

    assert_eq!(outcome.session.status, SessionStatus::Failed);
    let answer = outcome.session.answer.unwrap();
    assert!(answer.contains("cli exited 7"), "answer: {answer}");
}

#[test]
fn missing_program_surfaces_harness_error() {
    let harness = CliBackendHarness::new(
        "codex",
        "/no/such/program-xyzzy",
        Vec::<String>::new(),
        None,
        5,
        Vec::<String>::new(),
    );
    let attempt = PreparedAttempt::new("s4", "go", None, HarnessCtx::new("anthropic", "claude"));
    let err = block_on(harness.run_attempt(attempt)).unwrap_err();
    assert!(matches!(err, CoreError::Harness(_)), "got {err:?}");
}
