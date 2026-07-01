//! Pluggable agent runtime: the [`RuntimeHarness`] trait + a [`HarnessRegistry`]
//! that resolves *which* execution loop runs a given attempt (ADR-0008).
//!
//! OpenClaw's insight (`07-plugin-runtime-architecture.md` §1/§4): the *agent
//! runtime* is a layer orthogonal to provider / model / channel. Its
//! implementation is a **harness**, and several may coexist — the built-in
//! embedded ReAct loop, a provider-native loop, or a CLI backend. The host
//! prepares a fully-resolved [`PreparedAttempt`]; the selected harness only
//! executes it ("host prepares / harness executes", ADR-0008 §2).
//!
//! Selection is **deterministic** (Agent First): the *policy* — which runtime to
//! use for which `(provider, model)` — is a config/agent decision captured in
//! [`HarnessPolicy`]; the registry itself only does set lookups, an arithmetic
//! `max` over priorities, and a fallback. The runtime is re-resolved every round
//! (whole-session pins are ignored, ADR-0008 §3), so a harness can be swapped at
//! a round boundary exactly like a tool table.
//!
//! Portability: the trait and registry carry no tokio / no `std::time`. The
//! built-in [`EmbeddedHarness`] wraps [`ReActEngine`], so it runs identically on
//! the server, on device, and in the browser. A CLI-backend harness (which would
//! spawn a subprocess) is server-only and lives outside the core (ADR-0008 §4).

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use async_trait::async_trait;

use crate::agent::react::ReActEngine;
use crate::agent::types::SessionState;
use crate::ports::CoreResult;

/// The selection context the host hands the registry: the resolved
/// `(provider, model)` for this round. Policy lookups and [`RuntimeHarness::supports`]
/// key off it.
#[derive(Debug, Clone)]
pub struct HarnessCtx {
    pub provider: String,
    pub model: String,
}

impl HarnessCtx {
    pub fn new(provider: impl Into<String>, model: impl Into<String>) -> Self {
        Self {
            provider: provider.into(),
            model: model.into(),
        }
    }
}

/// A fully host-prepared attempt. The host resolves provider / auth / session /
/// tools up front and packs them here; the harness does not re-resolve any of it
/// (ADR-0008 §2). Alongside the session identity + goal + selection ctx it carries
/// a [`RuntimePlan`] — the **host-owned policy bundle** (tool normalization,
/// outcome classification, silent-tool set) a non-embedded harness applies while
/// executing. Because the policy is pure data + pure functions it stays in the
/// core and is shared by every harness family (embedded in-process or CLI
/// subprocess), which is exactly what makes the [`RuntimeHarness`] abstraction
/// non-vacuous once a second family exists (ADR-0008 §2).
#[derive(Debug, Clone)]
pub struct PreparedAttempt {
    pub session_id: String,
    pub goal: String,
    pub project_id: Option<String>,
    pub ctx: HarnessCtx,
    /// Host-owned execution policy the harness applies (default is empty).
    pub runtime_plan: Arc<RuntimePlan>,
}

impl PreparedAttempt {
    pub fn new(
        session_id: impl Into<String>,
        goal: impl Into<String>,
        project_id: Option<&str>,
        ctx: HarnessCtx,
    ) -> Self {
        Self {
            session_id: session_id.into(),
            goal: goal.into(),
            project_id: project_id.map(|p| p.to_string()),
            ctx,
            runtime_plan: Arc::new(RuntimePlan::new()),
        }
    }

    /// Attach a host-owned [`RuntimePlan`] policy bundle (default is empty).
    pub fn with_runtime_plan(mut self, plan: Arc<RuntimePlan>) -> Self {
        self.runtime_plan = plan;
        self
    }
}

/// Structural classification of a runtime/subprocess turn result — pure data, no
/// judgment. A CLI-backend harness maps a process exit code through this; the
/// engine's *semantic* verdict (why it failed, what to do) is a separate concern
/// (Wave N's supervisor).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutcomeKind {
    /// The runtime finished cleanly (exit code 0).
    Completed,
    /// The runtime exited with a non-zero code.
    Failed,
}

/// The host-owned policy bundle a harness applies while executing a
/// [`PreparedAttempt`] — "host prepares / harness executes" (ADR-0008 §2).
///
/// It is **pure data + pure functions**: no IO, no runtime, no `std::time`. That
/// is the whole point — the policy proves it does not depend on any concrete
/// runtime, so it lives in the core and both the embedded and CLI-backend
/// families share it. It captures three host decisions:
///   - **tool normalization** — canonicalize advertised tool names/aliases before
///     handing them to the runtime;
///   - **silent tools** — which tools' output is suppressed from the transcript;
///   - **outcome classification** — map a raw exit code to a structural
///     [`OutcomeKind`] (deterministic; the semantic verdict is Wave N's job).
#[derive(Debug, Clone, Default)]
pub struct RuntimePlan {
    tool_aliases: BTreeMap<String, String>,
    silent_tools: BTreeSet<String>,
}

impl RuntimePlan {
    pub fn new() -> Self {
        Self::default()
    }

    /// Map a tool alias to its canonical name (builder).
    pub fn with_alias(mut self, from: impl Into<String>, to: impl Into<String>) -> Self {
        self.tool_aliases.insert(from.into(), to.into());
        self
    }

    /// Mark a tool's output as silent/suppressed (builder).
    pub fn with_silent(mut self, tool: impl Into<String>) -> Self {
        self.silent_tools.insert(tool.into());
        self
    }

    /// Canonicalize one tool name (its alias target, or unchanged).
    pub fn normalize_tool(&self, name: &str) -> String {
        self.tool_aliases
            .get(name)
            .cloned()
            .unwrap_or_else(|| name.to_string())
    }

    /// Canonicalize a list of tool names — a pure structural map.
    pub fn normalize_tools(&self, names: &[String]) -> Vec<String> {
        names.iter().map(|n| self.normalize_tool(n)).collect()
    }

    /// Whether a tool's output is suppressed from the user-visible transcript.
    pub fn is_silent(&self, tool: &str) -> bool {
        self.silent_tools.contains(tool)
    }

    /// Classify a raw process exit code — arithmetic/structural, deterministic.
    pub fn classify_outcome(&self, exit_code: i32) -> OutcomeKind {
        if exit_code == 0 {
            OutcomeKind::Completed
        } else {
            OutcomeKind::Failed
        }
    }
}

/// What a harness returns after executing an attempt: the resulting session plus
/// the id of the runtime that actually handled it (so callers/tests can observe
/// which harness the registry selected).
#[derive(Debug, Clone)]
pub struct TurnOutcome {
    pub runtime_id: String,
    pub session: SessionState,
}

/// A pluggable agent execution loop (ADR-0008). The built-in ReAct loop
/// ([`EmbeddedHarness`]) is one implementation; third parties register more via
/// the capability model (ADR-0007, bundled-only trust).
#[async_trait]
pub trait RuntimeHarness: Send + Sync {
    /// Stable id, e.g. `"openclaw"` (built-in embedded), `"codex"`, `"claude-cli"`.
    fn runtime_id(&self) -> &str;

    /// `Some(priority)` if this harness can handle `ctx` (higher wins under
    /// `auto`); `None` if it cannot.
    fn supports(&self, ctx: &HarnessCtx) -> Option<u32>;

    /// Execute a host-prepared attempt to a terminal turn outcome.
    async fn run_attempt(&self, attempt: PreparedAttempt) -> CoreResult<TurnOutcome>;
}

/// Config-resolved runtime preferences (the *policy* half of selection),
/// populated by the host from tenant/agent config; the registry only reads it.
#[derive(Debug, Default, Clone)]
pub struct HarnessPolicy {
    /// `(provider, model)` -> runtime_id. Highest precedence.
    model_scoped: BTreeMap<(String, String), String>,
    /// `provider` -> runtime_id. Lower precedence than model-scoped.
    provider_scoped: BTreeMap<String, String>,
}

impl HarnessPolicy {
    pub fn new() -> Self {
        Self::default()
    }

    /// Pin a specific `(provider, model)` to a runtime id (highest precedence).
    pub fn pin_model(
        mut self,
        provider: impl Into<String>,
        model: impl Into<String>,
        runtime_id: impl Into<String>,
    ) -> Self {
        self.model_scoped
            .insert((provider.into(), model.into()), runtime_id.into());
        self
    }

    /// Pin a whole provider to a runtime id (lower precedence than model pins).
    pub fn pin_provider(
        mut self,
        provider: impl Into<String>,
        runtime_id: impl Into<String>,
    ) -> Self {
        self.provider_scoped
            .insert(provider.into(), runtime_id.into());
        self
    }

    /// The policy-preferred runtime id for `ctx` (model-scoped beats
    /// provider-scoped), paired with the reason it matched.
    fn preferred(&self, ctx: &HarnessCtx) -> Option<(&str, SelectionReason)> {
        if let Some(rid) = self
            .model_scoped
            .get(&(ctx.provider.clone(), ctx.model.clone()))
        {
            return Some((rid.as_str(), SelectionReason::ModelPolicy));
        }
        if let Some(rid) = self.provider_scoped.get(&ctx.provider) {
            return Some((rid.as_str(), SelectionReason::ProviderPolicy));
        }
        None
    }
}

/// How a harness was chosen — surfaced for observability and tests.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SelectionReason {
    /// A `(provider, model)` policy pin matched a supporting harness.
    ModelPolicy,
    /// A `provider` policy pin matched a supporting harness.
    ProviderPolicy,
    /// `auto`: the highest `supports()` priority among registered harnesses.
    Auto,
    /// No policy pin and no harness matched; the built-in fallback was used.
    Fallback,
}

/// Holds the available harnesses + the policy, and resolves one per round.
///
/// Selection priority (ADR-0008 §3): model-scoped policy > provider-scoped
/// policy > `auto` (max `supports` priority) > fallback. Every step is a
/// deterministic lookup / arithmetic `max` — the only *semantic* input is the
/// policy content, which the host/agent authored.
pub struct HarnessRegistry {
    /// The `auto` pool: specialized harnesses, consulted by `supports()`.
    harnesses: Vec<Arc<dyn RuntimeHarness>>,
    /// The built-in last resort (typically [`EmbeddedHarness`]). Dispatchable by
    /// id for policy pins, but not part of the `auto` pool.
    fallback: Arc<dyn RuntimeHarness>,
    policy: HarnessPolicy,
}

impl HarnessRegistry {
    /// Build a registry whose universal fallback is `fallback` (typically the
    /// built-in embedded ReAct harness). The `auto` pool starts empty.
    pub fn new(fallback: Arc<dyn RuntimeHarness>) -> Self {
        Self {
            harnesses: Vec::new(),
            fallback,
            policy: HarnessPolicy::new(),
        }
    }

    pub fn with_policy(mut self, policy: HarnessPolicy) -> Self {
        self.policy = policy;
        self
    }

    /// Register an additional (specialized) harness into the `auto` pool. Deduped
    /// by `runtime_id`: re-registering an id replaces it — a registry hot-swap at
    /// a round boundary (ADR-0006 / ADR-0008 §3).
    pub fn register(&mut self, harness: Arc<dyn RuntimeHarness>) {
        let rid = harness.runtime_id().to_string();
        self.harnesses.retain(|h| h.runtime_id() != rid);
        self.harnesses.push(harness);
    }

    /// Look up a harness by id, including the fallback.
    fn by_id(&self, rid: &str) -> Option<Arc<dyn RuntimeHarness>> {
        if self.fallback.runtime_id() == rid {
            return Some(self.fallback.clone());
        }
        self.harnesses
            .iter()
            .find(|h| h.runtime_id() == rid)
            .cloned()
    }

    /// Resolve the harness for `ctx`, returning it with the reason it was chosen.
    pub fn select(&self, ctx: &HarnessCtx) -> (Arc<dyn RuntimeHarness>, SelectionReason) {
        // 1/2. Policy pin (model-scoped beats provider-scoped) — honored only if
        // the named harness exists AND still supports this ctx.
        if let Some((rid, reason)) = self.policy.preferred(ctx) {
            if let Some(h) = self.by_id(rid) {
                if h.supports(ctx).is_some() {
                    return (h, reason);
                }
            }
        }

        // 3. auto: the supporting harness with the highest priority. Ties broken
        // deterministically by runtime_id so selection is reproducible.
        let mut best: Option<(u32, &Arc<dyn RuntimeHarness>)> = None;
        for h in &self.harnesses {
            if let Some(prio) = h.supports(ctx) {
                let better = match best {
                    None => true,
                    Some((bp, bh)) => prio > bp || (prio == bp && h.runtime_id() < bh.runtime_id()),
                };
                if better {
                    best = Some((prio, h));
                }
            }
        }
        if let Some((_, h)) = best {
            return (h.clone(), SelectionReason::Auto);
        }

        // 4. fallback.
        (self.fallback.clone(), SelectionReason::Fallback)
    }

    /// Select the harness for `attempt.ctx` and run it.
    pub async fn run(&self, attempt: PreparedAttempt) -> CoreResult<TurnOutcome> {
        let (harness, _reason) = self.select(&attempt.ctx);
        harness.run_attempt(attempt).await
    }

    /// The ids of all dispatchable harnesses (fallback included), for
    /// observability. Sorted for determinism.
    pub fn runtime_ids(&self) -> Vec<String> {
        let mut ids: Vec<String> = self
            .harnesses
            .iter()
            .map(|h| h.runtime_id().to_string())
            .collect();
        ids.push(self.fallback.runtime_id().to_string());
        ids.sort();
        ids.dedup();
        ids
    }
}

/// The built-in **embedded** harness: the [`ReActEngine`] adapted to the
/// [`RuntimeHarness`] trait. Runtime-agnostic, so it is the universal harness on
/// every platform (ADR-0008 §4). It supports any ctx at the lowest priority,
/// making it the natural `auto`/fallback choice when no specialized harness wins.
pub struct EmbeddedHarness {
    engine: ReActEngine,
    runtime_id: String,
}

impl EmbeddedHarness {
    /// Wrap an engine under a runtime id (the built-in default is `"openclaw"`).
    pub fn new(runtime_id: impl Into<String>, engine: ReActEngine) -> Self {
        Self {
            engine,
            runtime_id: runtime_id.into(),
        }
    }
}

#[async_trait]
impl RuntimeHarness for EmbeddedHarness {
    fn runtime_id(&self) -> &str {
        &self.runtime_id
    }

    /// The embedded loop is universal: it can run any `(provider, model)` — at the
    /// lowest priority, so a specialized harness always wins under `auto`.
    fn supports(&self, _ctx: &HarnessCtx) -> Option<u32> {
        Some(0)
    }

    async fn run_attempt(&self, attempt: PreparedAttempt) -> CoreResult<TurnOutcome> {
        let session = self
            .engine
            .run(
                &attempt.session_id,
                &attempt.goal,
                attempt.project_id.as_deref(),
            )
            .await?;
        Ok(TurnOutcome {
            runtime_id: self.runtime_id.clone(),
            session,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::types::{Role, SessionStatus, TranscriptEntry};
    use futures::executor::block_on;

    /// A minimal fake harness whose `supports` is gated on a provider and whose
    /// `run_attempt` returns a Finished session tagged with the harness id — just
    /// enough to assert *which* harness the registry selected and ran.
    struct FakeHarness {
        id: String,
        support_provider: Option<String>,
        prio: u32,
    }

    impl FakeHarness {
        fn universal(id: &str, prio: u32) -> Arc<Self> {
            Arc::new(Self {
                id: id.into(),
                support_provider: None,
                prio,
            })
        }
        fn for_provider(id: &str, provider: &str, prio: u32) -> Arc<Self> {
            Arc::new(Self {
                id: id.into(),
                support_provider: Some(provider.into()),
                prio,
            })
        }
    }

    #[async_trait]
    impl RuntimeHarness for FakeHarness {
        fn runtime_id(&self) -> &str {
            &self.id
        }
        fn supports(&self, ctx: &HarnessCtx) -> Option<u32> {
            match &self.support_provider {
                None => Some(self.prio),
                Some(p) if *p == ctx.provider => Some(self.prio),
                _ => None,
            }
        }
        async fn run_attempt(&self, attempt: PreparedAttempt) -> CoreResult<TurnOutcome> {
            let mut session = SessionState::new(&attempt.session_id, &attempt.goal, None);
            session.push_unique(TranscriptEntry::new(0, Role::Answer, self.id.clone()));
            session.answer = Some(self.id.clone());
            session.status = SessionStatus::Finished;
            Ok(TurnOutcome {
                runtime_id: self.id.clone(),
                session,
            })
        }
    }

    fn fallback() -> Arc<dyn RuntimeHarness> {
        FakeHarness::universal("builtin", 0)
    }

    #[test]
    fn empty_pool_resolves_to_fallback() {
        let reg = HarnessRegistry::new(fallback());
        let (h, reason) = reg.select(&HarnessCtx::new("anthropic", "opus"));
        assert_eq!(h.runtime_id(), "builtin");
        assert_eq!(reason, SelectionReason::Fallback);
    }

    #[test]
    fn auto_picks_supporting_specialized_harness() {
        let mut reg = HarnessRegistry::new(fallback());
        reg.register(FakeHarness::for_provider("codex", "openai", 10));

        // ctx matches the specialized harness -> auto picks it.
        let (h, reason) = reg.select(&HarnessCtx::new("openai", "gpt"));
        assert_eq!(h.runtime_id(), "codex");
        assert_eq!(reason, SelectionReason::Auto);

        // ctx does not match -> falls back to the built-in.
        let (h, reason) = reg.select(&HarnessCtx::new("anthropic", "opus"));
        assert_eq!(h.runtime_id(), "builtin");
        assert_eq!(reason, SelectionReason::Fallback);
    }

    #[test]
    fn auto_breaks_priority_ties_then_by_id() {
        let mut reg = HarnessRegistry::new(fallback());
        reg.register(FakeHarness::universal("zeta", 5));
        reg.register(FakeHarness::universal("alpha", 5));
        reg.register(FakeHarness::universal("beta", 9));
        // Highest priority wins regardless of registration order.
        let (h, _) = reg.select(&HarnessCtx::new("p", "m"));
        assert_eq!(h.runtime_id(), "beta");

        // Remove the high-prio one; the two prio-5 harnesses tie -> lowest id wins.
        let mut reg = HarnessRegistry::new(fallback());
        reg.register(FakeHarness::universal("zeta", 5));
        reg.register(FakeHarness::universal("alpha", 5));
        let (h, _) = reg.select(&HarnessCtx::new("p", "m"));
        assert_eq!(h.runtime_id(), "alpha");
    }

    #[test]
    fn model_policy_beats_provider_policy_and_auto() {
        let mut reg = HarnessRegistry::new(fallback()).with_policy(
            HarnessPolicy::new()
                .pin_model("openai", "gpt-4o", "model-harness")
                .pin_provider("openai", "provider-harness"),
        );
        reg.register(FakeHarness::universal("model-harness", 1));
        reg.register(FakeHarness::universal("provider-harness", 1));
        reg.register(FakeHarness::for_provider("auto-harness", "openai", 100));

        // (openai, gpt-4o): model pin wins over provider pin and over high-prio auto.
        let (h, reason) = reg.select(&HarnessCtx::new("openai", "gpt-4o"));
        assert_eq!(h.runtime_id(), "model-harness");
        assert_eq!(reason, SelectionReason::ModelPolicy);

        // (openai, other-model): no model pin -> provider pin wins over auto.
        let (h, reason) = reg.select(&HarnessCtx::new("openai", "gpt-3.5"));
        assert_eq!(h.runtime_id(), "provider-harness");
        assert_eq!(reason, SelectionReason::ProviderPolicy);
    }

    #[test]
    fn dangling_policy_pin_falls_through_to_auto() {
        // Policy names a runtime that was never registered -> the pin is ignored
        // and selection falls through to auto (a structural, self-healing fact).
        let mut reg = HarnessRegistry::new(fallback())
            .with_policy(HarnessPolicy::new().pin_provider("openai", "ghost"));
        reg.register(FakeHarness::for_provider("codex", "openai", 10));

        let (h, reason) = reg.select(&HarnessCtx::new("openai", "gpt"));
        assert_eq!(h.runtime_id(), "codex");
        assert_eq!(reason, SelectionReason::Auto);
    }

    #[test]
    fn register_dedups_by_runtime_id() {
        let mut reg = HarnessRegistry::new(fallback());
        reg.register(FakeHarness::for_provider("codex", "openai", 1));
        reg.register(FakeHarness::for_provider("codex", "anthropic", 1));
        // Only the latest "codex" survives.
        assert_eq!(reg.runtime_ids(), vec!["builtin", "codex"]);
        // The replacement's behaviour is in effect (now matches anthropic).
        let (h, _) = reg.select(&HarnessCtx::new("anthropic", "opus"));
        assert_eq!(h.runtime_id(), "codex");
    }

    #[test]
    fn run_dispatches_to_selected_harness() {
        let mut reg = HarnessRegistry::new(fallback());
        reg.register(FakeHarness::for_provider("codex", "openai", 10));

        let attempt = PreparedAttempt::new(
            "s1",
            "do it",
            Some("p1"),
            HarnessCtx::new("openai", "gpt"),
        );
        let outcome = block_on(reg.run(attempt)).unwrap();
        assert_eq!(outcome.runtime_id, "codex");
        assert_eq!(outcome.session.answer.as_deref(), Some("codex"));
        assert_eq!(outcome.session.status, SessionStatus::Finished);
    }

    #[test]
    fn runtime_plan_normalizes_tools_and_classifies_outcome() {
        let plan = RuntimePlan::new()
            .with_alias("legacy_read", "read")
            .with_silent("noisy");

        // Alias maps; unknown names pass through unchanged.
        assert_eq!(plan.normalize_tool("legacy_read"), "read");
        assert_eq!(plan.normalize_tool("write"), "write");
        assert_eq!(
            plan.normalize_tools(&["legacy_read".into(), "write".into()]),
            vec!["read".to_string(), "write".to_string()]
        );

        // Silent set membership.
        assert!(plan.is_silent("noisy"));
        assert!(!plan.is_silent("read"));

        // Structural exit-code classification (deterministic).
        assert_eq!(plan.classify_outcome(0), OutcomeKind::Completed);
        assert_eq!(plan.classify_outcome(1), OutcomeKind::Failed);
        assert_eq!(plan.classify_outcome(-1), OutcomeKind::Failed);
    }

    #[test]
    fn prepared_attempt_carries_runtime_plan() {
        let plan = Arc::new(RuntimePlan::new().with_alias("x", "y"));
        let attempt = PreparedAttempt::new("s", "g", None, HarnessCtx::new("p", "m"))
            .with_runtime_plan(plan);
        assert_eq!(attempt.runtime_plan.normalize_tool("x"), "y");
    }
}
