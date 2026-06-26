//! L2 Skill engine: declarative `Skill` data + sandboxed Rhai triggers composing
//! L1 tools from the hot-plug registry. Mirrors `02-extensibility.md` §5b.6.

use std::sync::Arc;

use futures::executor::block_on;

use agistack_plugin_host::native::{LenTool, UpperTool};
use agistack_plugin_host::registry::HotPlugRegistry;
use agistack_plugin_host::skill::{Skill, SkillContext, SkillEngine};

fn skill(name: &str, trigger: &str, steps: &[&str]) -> Skill {
    Skill {
        name: name.to_string(),
        version: "1.0.0".to_string(),
        description: String::new(),
        trigger: trigger.to_string(),
        steps: steps.iter().map(|s| s.to_string()).collect(),
    }
}

#[test]
fn keyword_semantic_and_hybrid_triggers_fire_as_authored() {
    let mut engine = SkillEngine::new();
    engine
        .register(skill("kw", r#"query.contains("weather")"#, &[]))
        .unwrap();
    engine
        .register(skill("sem", "semantic_score > 0.8", &[]))
        .unwrap();
    engine
        .register(skill(
            "hybrid",
            r#"query.contains("weather") || semantic_score > 0.8"#,
            &[],
        ))
        .unwrap();
    engine
        .register(skill("arr", r#"keywords.contains("forecast")"#, &[]))
        .unwrap();

    // Keyword path: query text matches.
    let ctx = SkillContext::new("what is the weather today").with_signal("semantic_score", 0.1);
    assert!(engine.evaluate("kw", &ctx).unwrap());
    assert!(!engine.evaluate("sem", &ctx).unwrap()); // low score
    assert!(engine.evaluate("hybrid", &ctx).unwrap()); // keyword arm

    // Semantic path: high score, unrelated text.
    let ctx2 = SkillContext::new("tell me a joke").with_signal("semantic_score", 0.95);
    assert!(!engine.evaluate("kw", &ctx2).unwrap());
    assert!(engine.evaluate("sem", &ctx2).unwrap());
    assert!(engine.evaluate("hybrid", &ctx2).unwrap()); // semantic arm

    // Array keyword path.
    let ctx3 = SkillContext::new("x").with_keywords(["forecast", "rain"]);
    assert!(engine.evaluate("arr", &ctx3).unwrap());
    let ctx4 = SkillContext::new("x").with_keywords(["sunshine"]);
    assert!(!engine.evaluate("arr", &ctx4).unwrap());
}

#[test]
fn matches_returns_only_fired_skills_sorted() {
    let mut engine = SkillEngine::new();
    engine
        .register(skill("zeta", r#"query.contains("a")"#, &[]))
        .unwrap();
    engine
        .register(skill("alpha", r#"query.contains("a")"#, &[]))
        .unwrap();
    engine
        .register(skill("never", "false", &[]))
        .unwrap();

    let ctx = SkillContext::new("banana");
    // Both "a"-matching skills fire; the always-false one does not; sorted.
    assert_eq!(engine.matches(&ctx).unwrap(), vec!["alpha", "zeta"]);

    let ctx_none = SkillContext::new("xyz");
    assert!(engine.matches(&ctx_none).unwrap().is_empty());
}

#[test]
fn run_composes_registered_tools_in_declared_order() {
    let registry = HotPlugRegistry::new();
    registry.register_tool(Arc::new(UpperTool));
    registry.register_tool(Arc::new(LenTool));

    let mut engine = SkillEngine::new();
    // A skill that fires on "shout" and composes upper -> len over the input.
    engine
        .register(skill("loud", r#"query.contains("shout")"#, &["upper", "len"]))
        .unwrap();

    let ctx = SkillContext::new("please shout this");
    let out = block_on(engine.run("loud", &ctx, &registry, r#"{"text":"hi"}"#)).unwrap();

    // Steps appear in declared order with each tool's structured output.
    let v: serde_json::Value = serde_json::from_str(&out).unwrap();
    assert_eq!(v["skill"], "loud");
    assert_eq!(v["fired"], true);
    let steps = v["steps"].as_array().unwrap();
    assert_eq!(steps.len(), 2);
    assert_eq!(steps[0]["tool"], "upper");
    assert_eq!(steps[0]["output"]["upper"], "HI");
    assert_eq!(steps[1]["tool"], "len");
    assert_eq!(steps[1]["output"]["len"], 2);
}

#[test]
fn run_errors_when_trigger_does_not_fire() {
    let registry = HotPlugRegistry::new();
    registry.register_tool(Arc::new(LenTool));
    let mut engine = SkillEngine::new();
    engine
        .register(skill("guarded", r#"query.contains("magic-word")"#, &["len"]))
        .unwrap();

    let ctx = SkillContext::new("no trigger here");
    let err = block_on(engine.run("guarded", &ctx, &registry, r#"{"text":"x"}"#));
    assert!(err.is_err(), "skill should not have fired");
}

#[test]
fn run_errors_on_unknown_step_tool() {
    let registry = HotPlugRegistry::new(); // empty registry
    let mut engine = SkillEngine::new();
    engine
        .register(skill("broken", "true", &["does_not_exist"]))
        .unwrap();
    let ctx = SkillContext::new("anything");
    let err = block_on(engine.run("broken", &ctx, &registry, "{}"));
    assert!(err.is_err(), "missing step tool must error");
}

#[test]
fn malformed_trigger_is_rejected_at_register_time() {
    let mut engine = SkillEngine::new();
    // Unbalanced parens -> Rhai parse error -> register fails fast.
    let err = engine.register(skill("bad", r#"query.contains("x""#, &[]));
    assert!(err.is_err(), "malformed trigger should fail to compile");
    assert!(engine.names().is_empty());
}

#[test]
fn sandbox_traps_runaway_trigger_without_hanging() {
    let mut engine = SkillEngine::new();
    // An infinite loop: the instruction budget must trap it deterministically
    // (no std::time, no hang) and surface an error rather than spinning forever.
    engine
        .register(skill("runaway", "let x = 0; loop { x += 1; } x > 0", &[]))
        .unwrap();
    let ctx = SkillContext::new("go");
    let err = engine.evaluate("runaway", &ctx);
    assert!(err.is_err(), "runaway trigger must be trapped by the op budget");
}

#[test]
fn sample_skill_file_loads_and_runs_end_to_end() {
    // The shipped sample skill (`skills/weather-skill.json`), embedded at compile
    // time so the load path is FS-free and works on every target incl. wasm.
    let json = include_str!("../skills/weather-skill.json");
    let s = Skill::from_json(json).unwrap();
    assert_eq!(s.name, "weather-skill");
    assert_eq!(s.steps, vec!["upper", "len"]);

    let registry = HotPlugRegistry::new();
    registry.register_tool(Arc::new(UpperTool));
    registry.register_tool(Arc::new(LenTool));
    let mut engine = SkillEngine::new();
    engine.register(s).unwrap();

    // Keyword arm fires and composes the registered tools.
    let ctx = SkillContext::new("what's the weather forecast");
    assert!(engine.evaluate("weather-skill", &ctx).unwrap());
    let out =
        block_on(engine.run("weather-skill", &ctx, &registry, r#"{"text":"sun"}"#)).unwrap();
    let v: serde_json::Value = serde_json::from_str(&out).unwrap();
    assert_eq!(v["steps"][0]["output"]["upper"], "SUN");
    assert_eq!(v["steps"][1]["output"]["len"], 3);

    // Unrelated, low-score query: skill stays dormant.
    let cold = SkillContext::new("play some music").with_signal("semantic_score", 0.1);
    assert!(!engine.evaluate("weather-skill", &cold).unwrap());
}

#[test]
fn skill_is_serde_portable_roundtrip() {
    // The whole skill — including its Rhai source — is data, so it ships to the
    // edge as JSON and compiles there.
    let json = r#"{
        "name": "weather-pack",
        "version": "0.2.0",
        "description": "answer weather questions",
        "trigger": "query.contains(\"weather\") || semantic_score > 0.85",
        "steps": ["upper", "len"]
    }"#;
    let s = Skill::from_json(json).unwrap();
    let reser = serde_json::to_string(&s).unwrap();
    let s2: Skill = serde_json::from_str(&reser).unwrap();
    assert_eq!(s, s2);
    assert_eq!(s.steps, vec!["upper", "len"]);

    // And it actually registers + compiles from that portable form.
    let mut engine = SkillEngine::new();
    engine.register(s).unwrap();
    assert_eq!(engine.names(), vec!["weather-pack"]);
    let ctx = SkillContext::new("the weather is nice");
    assert!(engine.evaluate("weather-pack", &ctx).unwrap());
}
