//! Accessibility-snapshot CDP sequence builder.
//!
//! The snapshot JavaScript lives in `assets/snapshot.js` and is embedded at
//! compile time. This crate treats the asset as **opaque**: it never parses
//! or inspects the script, it only wraps it into the fixed CDP call sequence
//! `Page.getFrameTree` → `Page.createIsolatedWorld` → `Runtime.evaluate`
//! (returnByValue) as plain data, so the host can execute it step by step and
//! thread the intermediate results (frame id, execution context id) through.
//!
//! Truncation is authoritative on the Rust side via [`truncate_snapshot`];
//! the evaluate expression additionally caps the wire payload at 4× the char
//! budget so a pathological page cannot push megabytes across the bridge
//! before the budget is enforced.

use serde_json::{json, Value};

/// The embedded snapshot script (placeholder until the extension workstream
/// lands the validated mini-aria build — see the asset's own header).
const SNAPSHOT_JS: &str = include_str!("../assets/snapshot.js");

/// Params placeholder the host replaces with the main frame id (from
/// `Page.getFrameTree`).
pub const PLACEHOLDER_FRAME_ID: &str = "__AGISTACK_FRAME_ID__";
/// Params placeholder the host replaces with the isolated world's execution
/// context id (from `Page.createIsolatedWorld`).
pub const PLACEHOLDER_CONTEXT_ID: &str = "__AGISTACK_CONTEXT_ID__";

/// Name of the isolated world the snapshot runs in.
pub const SNAPSHOT_WORLD_NAME: &str = "agistack_snapshot";

/// One CDP call in the snapshot sequence: `(method, params)`.
pub type SnapshotStep = (String, Value);

/// Build the snapshot CDP call sequence. `max_chars` is the caller's snapshot
/// budget; the evaluate step caps the wire payload at 4× that budget (the
/// authoritative truncation still happens in [`truncate_snapshot`]).
pub fn build_snapshot_request(max_chars: u32) -> Vec<SnapshotStep> {
    let wire_cap = max_chars.saturating_mul(4).max(1024);
    let expression = format!(
        "(function () {{\n  var __r = ({asset});\n  var __s = typeof __r === 'string' ? __r : String(__r);\n  return __s.length > {cap} ? __s.slice(0, {cap}) : __s;\n}})();",
        asset = snapshot_expression(),
        cap = wire_cap,
    );
    vec![
        ("Page.getFrameTree".to_string(), json!({})),
        (
            "Page.createIsolatedWorld".to_string(),
            json!({
                "frameId": PLACEHOLDER_FRAME_ID,
                "worldName": SNAPSHOT_WORLD_NAME,
                "grantUniveralAccess": true,
            }),
        ),
        (
            "Runtime.evaluate".to_string(),
            json!({
                "expression": expression,
                "returnByValue": true,
                "awaitPromise": true,
                "contextId": PLACEHOLDER_CONTEXT_ID,
            }),
        ),
    ]
}

/// The asset as an embeddable expression: the asset contract is "an IIFE
/// expression evaluating to the snapshot string", so we only strip trailing
/// whitespace/semicolons to make `(<asset>)` a valid sub-expression.
fn snapshot_expression() -> &'static str {
    let mut expr = SNAPSHOT_JS.trim();
    while let Some(stripped) = expr.strip_suffix(';') {
        expr = stripped.trim_end();
    }
    expr
}

/// Truncate `text` to `budget` **chars** (not bytes). Returns the (possibly
/// truncated) text plus whether truncation happened; truncated text gets a
/// `\n… [truncated at N chars]` marker appended.
pub fn truncate_snapshot(text: &str, budget: usize) -> (String, bool) {
    if text.chars().count() <= budget {
        return (text.to_string(), false);
    }
    let head: String = text.chars().take(budget).collect();
    (format!("{head}\n… [truncated at {budget} chars]"), true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plan_is_the_fixed_three_step_sequence() {
        let plan = build_snapshot_request(20_000);
        let methods: Vec<&str> = plan.iter().map(|(m, _)| m.as_str()).collect();
        assert_eq!(
            methods,
            [
                "Page.getFrameTree",
                "Page.createIsolatedWorld",
                "Runtime.evaluate"
            ]
        );
        assert_eq!(
            plan[1].1["frameId"],
            Value::String(PLACEHOLDER_FRAME_ID.into())
        );
        assert_eq!(plan[1].1["worldName"], SNAPSHOT_WORLD_NAME);
        assert_eq!(plan[2].1["returnByValue"], true);
        assert_eq!(
            plan[2].1["contextId"],
            Value::String(PLACEHOLDER_CONTEXT_ID.into())
        );
        let expression = plan[2].1["expression"].as_str().unwrap();
        assert!(
            expression.contains("80000"),
            "wire cap is 4x the char budget: {expression}"
        );
    }

    #[test]
    fn plan_treats_the_asset_as_opaque() {
        // Whatever the asset contains, it must appear verbatim (minus a
        // trailing semicolon) inside the evaluate expression.
        let plan = build_snapshot_request(100);
        let expression = plan[2].1["expression"].as_str().unwrap();
        assert!(expression.contains(snapshot_expression()));
    }

    #[test]
    fn truncate_under_budget_is_a_passthrough() {
        let (out, truncated) = truncate_snapshot("hello", 5);
        assert_eq!((out.as_str(), truncated), ("hello", false));
        let (out, truncated) = truncate_snapshot("hello", 10);
        assert_eq!((out.as_str(), truncated), ("hello", false));
    }

    #[test]
    fn truncate_over_budget_appends_marker() {
        let (out, truncated) = truncate_snapshot("hello world", 5);
        assert!(truncated);
        assert_eq!(out, "hello\n… [truncated at 5 chars]");
    }

    #[test]
    fn truncate_counts_chars_not_bytes() {
        let text = "é".repeat(10); // 10 chars, 20 bytes
        let (out, truncated) = truncate_snapshot(&text, 4);
        assert!(truncated);
        assert_eq!(out, "éééé\n… [truncated at 4 chars]");
    }
}
