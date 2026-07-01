//! Pluggable runtime harness (ADR-0008) end-to-end against real adapters: the
//! built-in [`EmbeddedHarness`] wraps a live [`ReActEngine`] over in-memory
//! checkpoints, while a specialized (provider-native) harness is registered
//! alongside it. Proves the registry's `auto` + policy + fallback selection picks
//! the right loop *and* that the chosen loop actually executes.

use std::sync::Arc;

use async_trait::async_trait;
use futures::executor::block_on;

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, StubLlm};
use agistack_core::ports::{CoreResult, ToolHost};
use agistack_core::{
    EmbeddedHarness, HarnessCtx, HarnessPolicy, HarnessRegistry, PreparedAttempt, ReActEngine,
    RuntimeHarness, SelectionReason, SessionState, SessionStatus, TurnOutcome,
};

/// Minimal tool host so the embedded ReAct loop has something to call.
struct EchoToolHost;

#[async_trait]
impl ToolHost for EchoToolHost {
    fn list_tools(&self) -> Vec<String> {
        vec!["len".to_string()]
    }
    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        Ok(serde_json::json!({ "tool": tool, "echo": input_json }).to_string())
    }
}

/// A specialized harness standing in for a provider-native loop (e.g. Codex). It
/// supports only its declared provider and returns a canned, recognisable answer
/// without driving the ReAct loop — enough to prove the registry routed to it.
struct ProviderHarness {
    id: String,
    provider: String,
}

#[async_trait]
impl RuntimeHarness for ProviderHarness {
    fn runtime_id(&self) -> &str {
        &self.id
    }
    fn supports(&self, ctx: &HarnessCtx) -> Option<u32> {
        (ctx.provider == self.provider).then_some(50)
    }
    async fn run_attempt(&self, attempt: PreparedAttempt) -> CoreResult<TurnOutcome> {
        let mut session = SessionState::new(&attempt.session_id, &attempt.goal, None);
        session.answer = Some(format!("handled-by-{}", self.id));
        session.status = SessionStatus::Finished;
        Ok(TurnOutcome {
            runtime_id: self.id.clone(),
            session,
        })
    }
}

/// Build the built-in embedded harness around a real ReAct engine.
fn embedded() -> Arc<dyn RuntimeHarness> {
    let engine = ReActEngine::new(
        Arc::new(StubLlm),
        Arc::new(EchoToolHost),
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(FixedClock(0)),
    );
    Arc::new(EmbeddedHarness::new("openclaw", engine))
}

/// `auto`: a matching specialized harness wins; a non-matching ctx falls back to
/// the built-in embedded loop, which actually runs (tool invoked, answer set).
#[test]
fn auto_routes_to_specialized_else_runs_embedded() {
    let mut reg = HarnessRegistry::new(embedded());
    reg.register(Arc::new(ProviderHarness {
        id: "codex".into(),
        provider: "openai".into(),
    }));

    // openai -> specialized harness handles it.
    let (_, reason) = reg.select(&HarnessCtx::new("openai", "gpt-4o"));
    assert_eq!(reason, SelectionReason::Auto);
    let outcome = block_on(reg.run(PreparedAttempt::new(
        "s-openai",
        "do the thing",
        Some("p1"),
        HarnessCtx::new("openai", "gpt-4o"),
    )))
    .unwrap();
    assert_eq!(outcome.runtime_id, "codex");
    assert_eq!(outcome.session.answer.as_deref(), Some("handled-by-codex"));

    // anthropic -> no specialized harness; the embedded ReAct loop runs for real.
    let (_, reason) = reg.select(&HarnessCtx::new("anthropic", "opus"));
    assert_eq!(reason, SelectionReason::Fallback);
    let outcome = block_on(reg.run(PreparedAttempt::new(
        "s-anthropic",
        "summarize hello",
        Some("p1"),
        HarnessCtx::new("anthropic", "opus"),
    )))
    .unwrap();
    assert_eq!(outcome.runtime_id, "openclaw");
    assert_eq!(outcome.session.status, SessionStatus::Finished);
    let answer = outcome.session.answer.expect("embedded loop produced an answer");
    assert!(
        answer.contains("\"tool\":\"len\""),
        "embedded ReAct loop should have invoked the tool: {answer}"
    );
}

/// A provider policy pin forces the built-in embedded harness even for a ctx the
/// specialized harness would otherwise win under `auto`.
#[test]
fn policy_pin_overrides_auto() {
    let mut reg = HarnessRegistry::new(embedded())
        .with_policy(HarnessPolicy::new().pin_provider("openai", "openclaw"));
    reg.register(Arc::new(ProviderHarness {
        id: "codex".into(),
        provider: "openai".into(),
    }));

    let (h, reason) = reg.select(&HarnessCtx::new("openai", "gpt-4o"));
    assert_eq!(h.runtime_id(), "openclaw");
    assert_eq!(reason, SelectionReason::ProviderPolicy);

    let outcome = block_on(reg.run(PreparedAttempt::new(
        "s-pinned",
        "summarize hello",
        Some("p1"),
        HarnessCtx::new("openai", "gpt-4o"),
    )))
    .unwrap();
    // The embedded loop ran (not the specialized harness), despite ctx=openai.
    assert_eq!(outcome.runtime_id, "openclaw");
    assert_eq!(outcome.session.status, SessionStatus::Finished);
}
