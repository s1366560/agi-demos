//! Live conformance test for the F9/P5 MCP tool-host adapter.
//!
//! Drives the production [`WsMcpToolHost`] against a **real** MCP server — the
//! same `sandbox-mcp-server` the Python backend uses — exercising the full
//! protocol path through the runtime-agnostic [`ToolHost`] port: handshake +
//! `tools/list` caching, an end-to-end `tools/call` round-trip **with arguments
//! and result parsing** (write a file, read it back, assert the bytes), and the
//! two error surfaces (unknown tool, malformed input).
//!
//! It is *gated*: set `MCP_TEST_URI` (default `ws://localhost:18765`). If the
//! server is unreachable the test prints a skip notice and passes, so offline /
//! CI-without-sandbox runs stay green. The round-trip is hermetic: it writes a
//! unique workspace-relative file and deletes it via `bash` at the end.

use std::time::{SystemTime, UNIX_EPOCH};

use agistack_adapters_mcp::{connect, WsMcpToolHost};
use agistack_core::ports::{CoreError, ToolHost};

fn mcp_uri() -> String {
    std::env::var("MCP_TEST_URI").unwrap_or_else(|_| "ws://localhost:18765".to_string())
}

fn unique_name() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    format!("agistack-it-{nanos}.txt")
}

/// Connect or return `None` (with a printed skip notice) if the server is down.
async fn mcp_or_skip() -> Option<WsMcpToolHost> {
    let uri = mcp_uri();
    match connect(&uri).await {
        Ok(host) => Some(host),
        Err(e) => {
            eprintln!("[skip] MCP server unreachable at {uri}: {e} — skipping F9 conformance test");
            None
        }
    }
}

/// Pull the concatenated `content[].text` out of a `tools/call` result JSON
/// string (what [`ToolHost::call`] returns on success).
fn result_text(result_json: &str) -> String {
    let v: serde_json::Value = serde_json::from_str(result_json).expect("result is json");
    v.get("content")
        .and_then(|c| c.as_array())
        .map(|items| {
            items
                .iter()
                .filter_map(|c| c.get("text").and_then(|t| t.as_str()))
                .collect::<Vec<_>>()
                .join("\n")
        })
        .unwrap_or_default()
}

/// Exercise the port through a trait object, proving the remote MCP backend is
/// usable anywhere the core expects a `dyn ToolHost` (same surface as the native
/// registry / wasm sandbox backends).
async fn tool_count(host: &dyn ToolHost) -> usize {
    host.list_tools().len()
}

#[tokio::test]
async fn mcp_toolhost_lists_and_round_trips_against_live_sandbox() {
    let Some(host) = mcp_or_skip().await else {
        return;
    };

    // Handshake captured a server identity.
    assert!(
        !host.server_name().is_empty(),
        "server_name populated from initialize"
    );

    // tools/list cached at connect: non-empty and includes the core sandbox tools.
    let tools = host.list_tools();
    assert!(!tools.is_empty(), "sandbox advertises tools");
    for expected in ["read", "write", "bash", "list"] {
        assert!(
            tools.iter().any(|t| t == expected),
            "sandbox advertises `{expected}` (got {tools:?})"
        );
    }
    // Same surface via a trait object (remote backend behind the one port).
    assert_eq!(tool_count(&host).await, tools.len());

    // End-to-end tools/call round-trip with arguments + result parsing:
    // write a unique workspace-relative file, then read it back verbatim.
    let name = unique_name();
    let body = "hello-mcp-roundtrip";
    let write_res = host
        .call(
            "write",
            &serde_json::json!({ "file_path": name, "content": body }).to_string(),
        )
        .await
        .expect("write succeeds");
    assert!(
        result_text(&write_res).to_lowercase().contains("success"),
        "write reported success: {write_res}"
    );

    let read_res = host
        .call(
            "read",
            &serde_json::json!({ "file_path": name, "raw": true }).to_string(),
        )
        .await
        .expect("read succeeds");
    assert_eq!(
        result_text(&read_res),
        body,
        "read returns exactly what write stored"
    );

    // Tool-level error surfaces as CoreError::Tool (not a panic / silent Ok).
    let unknown = host.call("does_not_exist", "{}").await;
    assert!(
        matches!(unknown, Err(CoreError::Tool(_))),
        "unknown tool -> CoreError::Tool, got {unknown:?}"
    );

    // Malformed tool input is rejected client-side before hitting the wire.
    let bad = host.call("read", "not-json").await;
    assert!(
        matches!(bad, Err(CoreError::Tool(_))),
        "invalid input json -> CoreError::Tool, got {bad:?}"
    );

    // Hermetic cleanup.
    let _ = host
        .call(
            "bash",
            &serde_json::json!({ "command": format!("rm -f {name}") }).to_string(),
        )
        .await;
}
