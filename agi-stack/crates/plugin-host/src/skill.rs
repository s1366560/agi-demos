//! The **L2 Skill** layer: a declarative tool composition gated by a sandboxed
//! Rhai trigger predicate.
//!
//! Design (`02-extensibility.md` §5b.6, "Skill = 数据 + Rhai"):
//!
//!   - A [`Skill`] is **pure data** (serde): a name/version, an ordered list of
//!     L1 tool `steps` it composes, and a `trigger` — a one-line Rhai expression
//!     returning `bool`. Because the whole thing (including the Rhai *source*) is
//!     serde-serializable, a skill ships to the edge as data and is compiled to
//!     an [`rhai::AST`] *there*, offline — no per-skill native code to cross-
//!     compile for iOS/Android/browser.
//!
//!   - The [`SkillEngine`] holds a **hardened, sandboxed** Rhai engine: no file /
//!     network / system access (Rhai has none by default), `eval` disabled, and
//!     an **instruction-count budget** (`set_max_operations`) so a runaway or
//!     adversarial trigger traps deterministically instead of hanging — note this
//!     is a *step counter*, not wall-clock, so it needs no `std::time` and stays
//!     true to the runtime-agnostic-core invariant (ADR-0001). It compiles on
//!     every target the registry does, incl. `wasm32` (browser).
//!
//! ## Trust & Agent First
//!
//! A Skill sits on the **configuration** trust tier (§5b.1): it carries no native
//! code and no ambient authority. It can only *orchestrate tools that were
//! already admitted under their own trust tier* — trusted `Trust::Builtin`
//! `dyn Trait` tools or `Trust::SandboxedWasm` tools (ADR-0002). A skill can
//! never escalate past the tools the host registered, so the trust axis is
//! preserved end-to-end.
//!
//! The Rhai `trigger` is an **author-declared, deterministic predicate** (config,
//! evaluated in a sandbox) — structurally the same as a gateway selector/rule or
//! [`crate::tool::Tool::should_run`]. It is *not* the engine making a semantic
//! verdict: the **semantic** decision of which skill matches a user's intent
//! remains an agent tool-call judgment (Agent First). `matches()` simply reports
//! every skill whose author-supplied predicate fires; an agent still owns the
//! choice of what to do with that set.

use std::collections::BTreeMap;
use std::sync::Arc;

use rhai::{Array, Dynamic, Engine, Scope, AST};
use serde::{Deserialize, Serialize};

use agistack_core::ports::{CoreError, CoreResult};

use crate::registry::HotPlugRegistry;

fn default_version() -> String {
    "0.0.0".to_string()
}

/// A declarative L2 skill: data + a Rhai trigger. Fully serde-portable so it can
/// be authored once and shipped to any platform as configuration.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct Skill {
    pub name: String,
    #[serde(default = "default_version")]
    pub version: String,
    #[serde(default)]
    pub description: String,
    /// A one-line Rhai expression returning `bool`, evaluated against a
    /// [`SkillContext`] scope (`query`, `keywords`, numeric `signals`). Examples:
    /// `query.contains("weather")` (keyword), `semantic_score > 0.8` (semantic),
    /// `query.contains("weather") || semantic_score > 0.8` (hybrid).
    pub trigger: String,
    /// The ordered L1 tool names this skill composes when it fires. Pure data;
    /// the tools themselves live in the [`HotPlugRegistry`].
    #[serde(default)]
    pub steps: Vec<String>,
}

impl Skill {
    /// Parse a skill from JSON (the portable on-the-wire form).
    pub fn from_json(s: &str) -> CoreResult<Self> {
        serde_json::from_str(s).map_err(|e| CoreError::Tool(format!("bad skill: {e}")))
    }
}

/// The opaque context a trigger is evaluated against. Built by the caller (e.g.
/// from the current turn) and projected into a Rhai [`Scope`].
#[derive(Debug, Clone, Default)]
pub struct SkillContext {
    /// The raw user query / latest message text.
    pub query: String,
    /// Pre-extracted keyword tokens (exposed to Rhai as an array).
    pub keywords: Vec<String>,
    /// Named numeric signals (e.g. `"semantic_score" -> 0.9`) for hybrid
    /// triggers. Each becomes a float variable of the same name in scope.
    pub signals: BTreeMap<String, f64>,
}

impl SkillContext {
    pub fn new(query: impl Into<String>) -> Self {
        Self {
            query: query.into(),
            ..Default::default()
        }
    }

    pub fn with_keywords<I, S>(mut self, kws: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        self.keywords = kws.into_iter().map(Into::into).collect();
        self
    }

    pub fn with_signal(mut self, name: impl Into<String>, value: f64) -> Self {
        self.signals.insert(name.into(), value);
        self
    }

    /// Project this context into a fresh Rhai scope.
    fn scope(&self) -> Scope<'static> {
        let mut scope = Scope::new();
        scope.push("query", self.query.clone());
        let arr: Array = self
            .keywords
            .iter()
            .map(|k| Dynamic::from(k.clone()))
            .collect();
        scope.push("keywords", arr);
        for (name, value) in &self.signals {
            scope.push(name.clone(), *value);
        }
        scope
    }
}

/// A skill whose trigger has been compiled to an executable AST. The AST is
/// cached so repeated evaluation does not re-parse.
struct CompiledSkill {
    skill: Skill,
    ast: AST,
}

/// The L2 skill engine: a sandboxed Rhai evaluator + a set of compiled skills.
///
/// `Send + Sync` (rhai `sync` feature) so it can sit beside the Send+Sync
/// [`HotPlugRegistry`] and be shared across server worker threads; on the edge it
/// runs single-threaded all the same.
pub struct SkillEngine {
    engine: Engine,
    skills: Vec<CompiledSkill>,
}

impl Default for SkillEngine {
    fn default() -> Self {
        Self::new()
    }
}

impl SkillEngine {
    /// Build a hardened, sandboxed engine. No IO is available in Rhai by default;
    /// we additionally cap instruction count (runaway protection, no wall-clock),
    /// bound memory growth, and disable `eval` so a trigger cannot escalate.
    pub fn new() -> Self {
        let mut engine = Engine::new();
        // Instruction budget — deterministic runaway protection (no std::time).
        engine.set_max_operations(50_000);
        // Bound recursion / nesting and memory growth from a hostile trigger.
        engine.set_max_expr_depths(64, 64);
        engine.set_max_string_size(8 * 1024);
        engine.set_max_array_size(1024);
        engine.set_max_map_size(1024);
        // No dynamic code generation from inside a trigger.
        engine.disable_symbol("eval");
        Self {
            engine,
            skills: Vec::new(),
        }
    }

    /// Compile and register a skill. A malformed trigger is rejected here (fail
    /// fast at load), not at evaluation time. Re-registering a name replaces it.
    pub fn register(&mut self, skill: Skill) -> CoreResult<()> {
        let ast = self
            .engine
            .compile(&skill.trigger)
            .map_err(|e| CoreError::Tool(format!("skill `{}`: bad trigger: {e}", skill.name)))?;
        self.skills.retain(|c| c.skill.name != skill.name);
        self.skills.push(CompiledSkill { skill, ast });
        Ok(())
    }

    /// Sorted names of registered skills.
    pub fn names(&self) -> Vec<String> {
        let mut names: Vec<String> = self.skills.iter().map(|c| c.skill.name.clone()).collect();
        names.sort();
        names
    }

    /// Look up a registered skill's data by name.
    pub fn get(&self, name: &str) -> Option<&Skill> {
        self.skills
            .iter()
            .find(|c| c.skill.name == name)
            .map(|c| &c.skill)
    }

    fn compiled(&self, name: &str) -> CoreResult<&CompiledSkill> {
        self.skills
            .iter()
            .find(|c| c.skill.name == name)
            .ok_or_else(|| CoreError::Tool(format!("unknown skill: {name}")))
    }

    /// Evaluate one skill's trigger against `ctx`. A sandbox violation (e.g.
    /// instruction budget exceeded) surfaces as a [`CoreError`], never a hang.
    pub fn evaluate(&self, name: &str, ctx: &SkillContext) -> CoreResult<bool> {
        let compiled = self.compiled(name)?;
        let mut scope = ctx.scope();
        self.engine
            .eval_ast_with_scope::<bool>(&mut scope, &compiled.ast)
            .map_err(|e| CoreError::Tool(format!("skill `{name}`: trigger failed: {e}")))
    }

    /// Every registered skill whose trigger fires for `ctx`, by name (sorted).
    /// This is the *structural* match set; the agent owns the semantic choice of
    /// what to do with it.
    pub fn matches(&self, ctx: &SkillContext) -> CoreResult<Vec<String>> {
        let mut fired = Vec::new();
        for compiled in &self.skills {
            if self.evaluate(&compiled.skill.name, ctx)? {
                fired.push(compiled.skill.name.clone());
            }
        }
        fired.sort();
        Ok(fired)
    }

    /// Run a skill end-to-end: gate on its trigger, then compose its `steps` by
    /// invoking each tool against the **current** registry snapshot in order,
    /// threading the same `input_json` to each. Returns a JSON object with the
    /// per-step outputs. Errors if the trigger does not fire or a step tool is
    /// missing.
    pub async fn run(
        &self,
        name: &str,
        ctx: &SkillContext,
        registry: &HotPlugRegistry,
        input_json: &str,
    ) -> CoreResult<String> {
        let compiled = self.compiled(name)?;
        if !self.evaluate(name, ctx)? {
            return Err(CoreError::Tool(format!("skill `{name}` did not trigger")));
        }
        // Pin one registry snapshot for the whole composition so a hot-swap
        // mid-skill cannot make the steps see two different tool sets
        // (round-boundary isolation, ADR-0005/0006).
        let snapshot = registry.snapshot();
        let mut outputs: Vec<serde_json::Value> = Vec::with_capacity(compiled.skill.steps.len());
        for step in &compiled.skill.steps {
            let tool: Arc<dyn crate::tool::Tool> = snapshot
                .get(step)
                .ok_or_else(|| CoreError::Tool(format!("skill `{name}`: unknown step tool: {step}")))?;
            let out = tool.invoke(input_json).await?;
            let parsed: serde_json::Value =
                serde_json::from_str(&out).unwrap_or(serde_json::Value::String(out));
            outputs.push(serde_json::json!({ "tool": step, "output": parsed }));
        }
        Ok(serde_json::json!({
            "skill": name,
            "fired": true,
            "steps": outputs,
        })
        .to_string())
    }
}
