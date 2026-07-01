//! A minimal CLI-backend *fixture* subprocess used by the integration tests. It
//! stands in for a real external agent CLI (`claude-cli` / `codex`): read one
//! JSON request from stdin, echo a deterministic reply on stdout.
//!
//! Contract (mirrors `CliBackendHarness`'s private `CliRequest`/`CliReply`):
//!   stdin  = {"session_id","goal","project_id","tools":[...]}
//!   stdout = {"answer":"echo: <goal> [tools: <joined>]","status":"finished"}
//!   exit 7 (non-zero) when goal == "__fail__", to exercise failure classification.

use std::io::Read;

fn main() {
    let mut buf = String::new();
    std::io::stdin()
        .read_to_string(&mut buf)
        .expect("read stdin");
    let req: serde_json::Value = serde_json::from_str(&buf).expect("parse request json");

    let goal = req.get("goal").and_then(|v| v.as_str()).unwrap_or("");
    if goal == "__fail__" {
        eprintln!("fixture: forced failure");
        std::process::exit(7);
    }

    let tools: Vec<String> = req
        .get("tools")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|t| t.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();

    let answer = format!("echo: {goal} [tools: {}]", tools.join(","));
    let reply = serde_json::json!({ "answer": answer, "status": "finished" });
    println!("{reply}");
}
