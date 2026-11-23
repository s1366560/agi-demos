//! One local turn on `LocalToolHost`. The model decides the tools; the cloud does not.

use std::collections::BTreeSet;
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use agistack_adapters_mem::checkpoint::InMemoryCheckpointStore;
use agistack_adapters_mem::clock::SystemClock;
use agistack_core::agent::react::{ReActControl, ReActEngine, ReActObserver, RunDirective};
use agistack_core::agent::types::SessionStatus;
use agistack_core::ports::{CoreError, CoreResult, LlmPort, ToolHost};
use async_trait::async_trait;
use base64::Engine;
use serde_json::{json, Value};

use crate::redact::contains_secret_like_text;

pub struct LocalTurn {
    pub events: Vec<Value>,
    pub status: String,
    pub error: Option<String>,
}

pub async fn execute_local_turn(
    llm: Arc<dyn LlmPort>,
    tools: Arc<dyn ToolHost>,
    local_root: &Path,
    permission_profile: &str,
    message: &str,
    session_id: &str,
    cancel: Arc<AtomicBool>,
) -> LocalTurn {
    let allowed = allowed_tools(permission_profile, &tools.list_tools());
    let host: Arc<dyn ToolHost> = Arc::new(ProfiledHost {
        inner: tools,
        allowed,
    });
    let events = Arc::new(Mutex::new(Vec::new()));
    events.lock().expect("events").push(json!({
        "kind": "user_message",
        "payload": {"text": message}
    }));
    let observer = Arc::new(RecordingObserver {
        events: Arc::clone(&events),
        root: local_root.to_path_buf(),
    });
    let control = Arc::new(CancelControl {
        cancel: Arc::clone(&cancel),
    });
    let engine = ReActEngine::new(
        llm,
        host,
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(SystemClock),
    )
    .with_max_rounds(4);
    if cancel.load(Ordering::Acquire) {
        return cancelled(events);
    }
    let result = engine
        .run_observed_controlled(session_id, message, None, observer, control)
        .await;
    let mut recorded = events.lock().expect("events").clone();
    match result {
        Ok(state) if state.status == SessionStatus::Cancelled => LocalTurn {
            events: recorded,
            status: "cancelled".to_string(),
            error: None,
        },
        Ok(state) if state.status == SessionStatus::Finished => LocalTurn {
            events: recorded,
            status: "completed".to_string(),
            error: None,
        },
        Ok(state) => LocalTurn {
            events: recorded,
            status: "failed".to_string(),
            error: Some(format!("local execution ended as {:?}", state.status)),
        },
        Err(error) => {
            recorded.push(json!({"kind": "error", "payload": {"message": error.to_string()}}));
            LocalTurn {
                events: recorded,
                status: "failed".to_string(),
                error: Some(error.to_string()),
            }
        }
    }
}

fn cancelled(events: Arc<Mutex<Vec<Value>>>) -> LocalTurn {
    LocalTurn {
        events: events.lock().expect("events").clone(),
        status: "cancelled".to_string(),
        error: None,
    }
}

fn allowed_tools(profile: &str, names: &[String]) -> BTreeSet<String> {
    const READ: &[&str] = &[
        "list",
        "read",
        "batch_read",
        "glob",
        "grep",
        "list_artifacts",
    ];
    const WRITE: &[&str] = &[
        "write",
        "edit",
        "patch",
        "preview_edit",
        "export_artifact",
        "batch_export_artifacts",
    ];
    names
        .iter()
        .filter(|name| match profile {
            "full_access" => true,
            "workspace_write" => READ.contains(&name.as_str()) || WRITE.contains(&name.as_str()),
            _ => READ.contains(&name.as_str()),
        })
        .cloned()
        .collect()
}

struct ProfiledHost {
    inner: Arc<dyn ToolHost>,
    allowed: BTreeSet<String>,
}

#[async_trait]
impl ToolHost for ProfiledHost {
    fn list_tools(&self) -> Vec<String> {
        self.allowed.iter().cloned().collect()
    }

    fn can_dispatch(&self, tool: &str) -> bool {
        self.allowed.contains(tool)
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        if !self.allowed.contains(tool) {
            return Err(CoreError::Tool(format!(
                "tool '{tool}' exceeds the frozen local permission profile"
            )));
        }
        self.inner.call(tool, input_json).await
    }
}

struct CancelControl {
    cancel: Arc<AtomicBool>,
}

#[async_trait]
impl ReActControl for CancelControl {
    async fn directive(&self, _session_id: &str, _round: u64) -> CoreResult<RunDirective> {
        if self.cancel.load(Ordering::Acquire) {
            Ok(RunDirective::Cancel)
        } else {
            Ok(RunDirective::Continue)
        }
    }

    async fn wait_for_interrupt(&self, _session_id: &str, _round: u64) -> CoreResult<()> {
        while !self.cancel.load(Ordering::Acquire) {
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        Ok(())
    }
}

struct RecordingObserver {
    events: Arc<Mutex<Vec<Value>>>,
    root: PathBuf,
}

#[async_trait]
impl ReActObserver for RecordingObserver {
    async fn on_tool_call(
        &self,
        _session_id: &str,
        _round: u64,
        tool: &str,
        input_json: &str,
    ) -> CoreResult<()> {
        self.push(json!({"kind": "tool_call", "payload": {"tool": tool, "input": input_json}}));
        Ok(())
    }

    async fn on_tool_result(
        &self,
        _session_id: &str,
        _round: u64,
        tool: &str,
        input_json: &str,
        output_json: &str,
    ) -> CoreResult<()> {
        self.push(json!({"kind": "tool_result", "payload": {"tool": tool, "output": output_json}}));
        if tool == "write" {
            self.record_write_artifact(input_json);
        }
        Ok(())
    }

    async fn on_tool_error(
        &self,
        _session_id: &str,
        _round: u64,
        tool: &str,
        _input_json: &str,
        error: &CoreError,
    ) -> CoreResult<()> {
        self.push(
            json!({"kind": "error", "payload": {"tool": tool, "message": error.to_string()}}),
        );
        Ok(())
    }

    async fn on_finish(&self, _session_id: &str, _round: u64, answer: &str) -> CoreResult<()> {
        self.push(json!({"kind": "assistant_message", "payload": {"text": answer}}));
        Ok(())
    }
}

impl RecordingObserver {
    fn push(&self, event: Value) {
        self.events.lock().expect("events").push(event);
    }

    fn record_write_artifact(&self, input_json: &str) {
        let Ok(input) = serde_json::from_str::<Value>(input_json) else {
            return;
        };
        let Some(path) = input.get("path").and_then(Value::as_str) else {
            return;
        };
        if !safe_relative(path) {
            self.push(json!({"kind": "artifact", "payload": {"artifact_rejected": "unsafe_path", "filename": "rejected"}}));
            return;
        }
        let content = std::fs::read(self.root.join(path)).unwrap_or_default();
        let filename = Path::new(path)
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("artifact.bin");
        if content.len() > 256 * 1024 {
            self.push(json!({"kind": "artifact", "payload": {"artifact_rejected": "too_large", "filename": filename}}));
            return;
        }
        if std::str::from_utf8(&content).is_ok_and(contains_secret_like_text) {
            self.push(json!({"kind": "artifact", "payload": {"artifact_rejected": "secret_like", "filename": filename}}));
            return;
        }
        self.push(json!({
            "kind": "artifact",
            "payload": {
                "filename": filename,
                "content_base64": base64::engine::general_purpose::STANDARD.encode(content),
                "source_tool": "write",
                "source_path": path
            }
        }));
    }
}

fn safe_relative(path: &str) -> bool {
    let path = Path::new(path);
    !path.is_absolute()
        && path
            .components()
            .all(|component| matches!(component, Component::Normal(_)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_adapters_local_tools::LocalToolHost;
    use agistack_adapters_mem::llm::ScriptedLlm;
    use agistack_core::agent::types::AgentAction;
    use std::sync::atomic::AtomicBool;

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn local_tool_host_result_is_recorded_without_repeating_after_cancel() {
        let root = std::env::temp_dir().join(format!("local-run-exec-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).expect("root");
        let host = Arc::new(LocalToolHost::new(&root).expect("host"));
        let llm = Arc::new(ScriptedLlm::new(vec![
            AgentAction::CallTool {
                tool: "list".to_string(),
                input_json: "{}".to_string(),
            },
            AgentAction::Finish {
                answer: "listed the workspace".to_string(),
            },
        ]));
        let cancel = Arc::new(AtomicBool::new(false));
        let turn = execute_local_turn(
            llm,
            host,
            &root,
            "read_only",
            "list this workspace",
            "session-1",
            Arc::clone(&cancel),
        )
        .await;
        assert_eq!(turn.status, "completed");
        assert!(turn
            .events
            .iter()
            .any(|event| event["kind"] == "tool_result"));
        assert!(turn
            .events
            .iter()
            .any(|event| event["payload"]["text"] == "listed the workspace"));
        cancel.store(true, Ordering::Release);
        let llm = Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "should not run".to_string(),
        }]));
        let host = Arc::new(LocalToolHost::new(&root).expect("host"));
        let stopped =
            execute_local_turn(llm, host, &root, "read_only", "again", "session-2", cancel).await;
        assert_eq!(stopped.status, "cancelled");
        assert!(!stopped
            .events
            .iter()
            .any(|event| event["payload"]["text"] == "should not run"));
        let _ = std::fs::remove_dir_all(root);
    }
}
