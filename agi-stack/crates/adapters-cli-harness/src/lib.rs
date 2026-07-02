//! CLI-backend [`RuntimeHarness`] (ADR-0008 §4): the **second, non-embedded**
//! runtime family. Where [`agistack_core::EmbeddedHarness`] runs the ReAct loop
//! in-process, this harness delegates a whole turn to an **external agent CLI**
//! by spawning a subprocess — the `claude-cli` / `codex`-style backend OpenClaw
//! documents (`07-plugin-runtime-architecture.md` §4).
//!
//! Its whole reason to exist is to make the [`RuntimeHarness`] abstraction
//! *non-vacuous*: with two real families the [`HarnessRegistry`] genuinely
//! selects between "in-process loop" and "subprocess loop" under the same
//! policy/auto rules, instead of the trait being an abstraction over a single
//! implementation.
//!
//! **Portability boundary (ADR-0008 §4, invariant):** subprocess spawning lives
//! *only here*, in a server-only adapter crate. The core stays zero-subprocess /
//! zero-tokio and still compiles to `wasm32`; on device/browser the agent is
//! always the embedded harness.
//!
//! **Host prepares / harness executes (ADR-0008 §2):** the host packs a
//! [`RuntimePlan`] into the [`PreparedAttempt`]. This harness applies its
//! *structural* parts deterministically — [`RuntimePlan::normalize_tools`] before
//! advertising tools to the CLI, and [`RuntimePlan::classify_outcome`] on the
//! process exit code. No semantic judgment happens here.

use std::io::Write;
use std::process::{Command, Stdio};

use agistack_core::agent::{
    HarnessCtx, OutcomeKind, PreparedAttempt, RuntimeHarness, SessionState, SessionStatus,
    TurnOutcome,
};
use agistack_core::ports::{CoreError, CoreResult};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};

/// The JSON contract written to the CLI subprocess's stdin.
#[derive(Debug, Serialize)]
struct CliRequest<'a> {
    session_id: &'a str,
    goal: &'a str,
    project_id: Option<&'a str>,
    /// Tools advertised to the backend, already normalized by the host's
    /// [`RuntimePlan`] (aliases resolved) — a pure structural map.
    tools: Vec<String>,
}

/// The JSON contract parsed from the CLI subprocess's stdout.
#[derive(Debug, Deserialize)]
struct CliReply {
    /// The backend's final answer for the turn.
    answer: String,
    /// Backend-reported terminal status: `"finished"` or `"failed"`.
    #[serde(default)]
    status: Option<String>,
}

/// A [`RuntimeHarness`] backed by an external agent CLI (subprocess).
///
/// Selection is deterministic: [`supports`](RuntimeHarness::supports) returns
/// `Some(priority)` when the attempt's provider matches this backend's pin (or
/// when the backend declares no provider pin, meaning "any"), else `None`. The
/// registry's `auto` mode then does an arithmetic `max` over priorities, so a
/// higher-priority CLI backend wins over the embedded fallback.
pub struct CliBackendHarness {
    runtime_id: String,
    program: String,
    args: Vec<String>,
    provider: Option<String>,
    priority: u32,
    advertised_tools: Vec<String>,
    /// OpenClaw's `owns_native_compaction` flag (`07` §4): when a backend runs its
    /// own transcript compaction the host compactor must skip it. Recorded here so
    /// the host can honor it; a spike does not compact, but the contract is fixed.
    owns_native_compaction: bool,
}

impl CliBackendHarness {
    /// Build a CLI backend that runs `program args…`, pinned to `provider`
    /// (`None` = handles any provider), advertising `tools` to the subprocess.
    pub fn new(
        runtime_id: impl Into<String>,
        program: impl Into<String>,
        args: impl IntoIterator<Item = impl Into<String>>,
        provider: Option<&str>,
        priority: u32,
        tools: impl IntoIterator<Item = impl Into<String>>,
    ) -> Self {
        Self {
            runtime_id: runtime_id.into(),
            program: program.into(),
            args: args.into_iter().map(Into::into).collect(),
            provider: provider.map(|p| p.to_string()),
            priority,
            advertised_tools: tools.into_iter().map(Into::into).collect(),
            owns_native_compaction: true,
        }
    }

    /// Whether this backend runs its own transcript compaction (default `true`).
    pub fn owns_native_compaction(&self) -> bool {
        self.owns_native_compaction
    }

    /// Override the native-compaction flag (builder).
    pub fn with_native_compaction(mut self, owns: bool) -> Self {
        self.owns_native_compaction = owns;
        self
    }
}

#[async_trait]
impl RuntimeHarness for CliBackendHarness {
    fn runtime_id(&self) -> &str {
        &self.runtime_id
    }

    fn supports(&self, ctx: &HarnessCtx) -> Option<u32> {
        match &self.provider {
            Some(p) if *p == ctx.provider => Some(self.priority),
            Some(_) => None,
            None => Some(self.priority),
        }
    }

    async fn run_attempt(&self, attempt: PreparedAttempt) -> CoreResult<TurnOutcome> {
        // Host prepares / harness executes: apply the RuntimePlan's *structural*
        // policy (tool-name normalization) before advertising tools to the CLI.
        let tools = attempt.runtime_plan.normalize_tools(&self.advertised_tools);

        let request = CliRequest {
            session_id: &attempt.session_id,
            goal: &attempt.goal,
            project_id: attempt.project_id.as_deref(),
            tools,
        };
        let payload = serde_json::to_vec(&request)
            .map_err(|e| CoreError::Harness(format!("encode cli request: {e}")))?;

        // Subprocess spawning is confined to this server-only crate (ADR-0008 §4).
        let mut child = Command::new(&self.program)
            .args(&self.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| CoreError::Harness(format!("spawn {}: {e}", self.program)))?;

        // Write the request then drop stdin to signal EOF to the backend.
        {
            let mut stdin = child
                .stdin
                .take()
                .ok_or_else(|| CoreError::Harness("child stdin unavailable".into()))?;
            stdin
                .write_all(&payload)
                .map_err(|e| CoreError::Harness(format!("write cli stdin: {e}")))?;
        }

        let output = child
            .wait_with_output()
            .map_err(|e| CoreError::Harness(format!("wait cli: {e}")))?;

        // Structural exit-code classification is a deterministic host policy.
        let exit_code = output.status.code().unwrap_or(-1);
        let kind = attempt.runtime_plan.classify_outcome(exit_code);
        if kind == OutcomeKind::Failed {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Ok(failed_outcome(
                &self.runtime_id,
                &attempt,
                &format!("cli exited {exit_code}: {}", stderr.trim()),
            ));
        }

        let reply: CliReply = serde_json::from_slice(&output.stdout)
            .map_err(|e| CoreError::Harness(format!("decode cli reply: {e}")))?;

        let mut session = SessionState::new(
            &attempt.session_id,
            &attempt.goal,
            attempt.project_id.as_deref(),
        );
        session.answer = Some(reply.answer);
        session.status = match reply.status.as_deref() {
            Some("failed") => SessionStatus::Failed,
            _ => SessionStatus::Finished,
        };

        Ok(TurnOutcome {
            runtime_id: self.runtime_id.clone(),
            session,
        })
    }
}

/// Build a Failed [`TurnOutcome`] carrying `reason` as the answer.
fn failed_outcome(runtime_id: &str, attempt: &PreparedAttempt, reason: &str) -> TurnOutcome {
    let mut session = SessionState::new(
        &attempt.session_id,
        &attempt.goal,
        attempt.project_id.as_deref(),
    );
    session.answer = Some(reason.to_string());
    session.status = SessionStatus::Failed;
    TurnOutcome {
        runtime_id: runtime_id.to_string(),
        session,
    }
}
