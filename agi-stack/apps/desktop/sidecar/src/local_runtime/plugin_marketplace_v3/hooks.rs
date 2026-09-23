//! Each agent operation captures immutable hook versions before creating its engine.
use super::{load, package::Package, root, LocalRuntimeState};
use agistack_core::{
    agent::types::{AgentAction, TranscriptEntry},
    model::{Episode, Memory},
    ports::{
        CoreError, CoreResult, LlmPort, MemoryDraft, RelationshipDraft, ToolDefinition, ToolHost,
    },
};
use async_trait::async_trait;
use serde_json::json;
use std::{process::Stdio, sync::Arc, time::Duration};
use tokio::io::AsyncWriteExt;

#[derive(Clone)]
pub(in crate::local_runtime) struct Hooks {
    packages: Vec<(String, Package)>,
    audit_path: Option<std::path::PathBuf>,
    _leases: Arc<Vec<super::cache::Lease>>,
}
impl Hooks {
    pub(in crate::local_runtime) fn capture(
        state: &LocalRuntimeState,
        tenant: &str,
        project: &str,
    ) -> Result<Self, String> {
        if state.app_data_dir.is_none() {
            return Ok(Self {
                packages: vec![],
                audit_path: None,
                _leases: Arc::new(vec![]),
            });
        }
        let scope_root = root(state, tenant, project)?;
        let packages: Vec<(String, Package)> = load(&scope_root)?
            .installations
            .into_iter()
            .filter(|i| i.status == "enabled")
            .map(|i| (i.id, i.package))
            .collect();
        let leases = packages
            .iter()
            .map(|(_, package)| super::cache::lease(&package.root))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Self {
            packages,
            audit_path: Some(scope_root.join("hooks-audit.jsonl")),
            _leases: Arc::new(leases),
        })
    }

    pub(in crate::local_runtime) async fn run(&self, event: &str) -> CoreResult<()> {
        for (installation_id, package) in &self.packages {
            for hook in package.hooks.get(event).into_iter().flatten() {
                let root = package.root.to_string_lossy();
                // Expansion is shell-quoted because the manifest declares a shell command.
                let quoted = format!("'{}'", root.replace('\'', "'\\''"));
                let command = hook
                    .command
                    .replace("${PLUGIN_ROOT}", &quoted)
                    .replace("${CLAUDE_PLUGIN_ROOT}", &quoted);
                let started = std::time::Instant::now();
                let result: CoreResult<()> = async {
                #[cfg(unix)]
                let mut process = {
                    let mut p = tokio::process::Command::new("/bin/sh");
                    p.args(["-c", &command]);
                    p
                };
                #[cfg(windows)]
                let mut process = {
                    let mut p = tokio::process::Command::new("cmd.exe");
                    p.args(["/C", &command]);
                    p
                };
                process
                    .current_dir(&package.root)
                    .env_clear()
                    .env(
                        "PATH",
                        std::env::var("PATH").unwrap_or_else(|_| "/usr/bin:/bin".into()),
                    )
                    .env("PLUGIN_ROOT", &package.root)
                    .stdin(Stdio::piped())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .kill_on_drop(true);
                #[cfg(unix)]
                process.process_group(0);
                let mut child = process
                    .spawn()
                    .map_err(|_| CoreError::Tool("plugin hook process could not start".into()))?;
                #[cfg(unix)]
                let mut process_group = ProcessGroup(child.id());
                let payload=json!({"event":event,"plugin_id":package.descriptor.id,"version":package.descriptor.version}).to_string();
                let operation = async {
                    if let Some(mut stdin) = child.stdin.take() {
                        stdin
                            .write_all(payload.as_bytes())
                            .await
                            .map_err(|_| CoreError::Tool("plugin hook input failed".into()))?;
                    }
                    let status = child
                        .wait()
                        .await
                        .map_err(|_| CoreError::Tool("plugin hook process failed".into()))?;
                    if !status.success() {
                        return Err(CoreError::Tool(format!(
                            "plugin {} hook {event} failed; disable the plugin before retrying",
                            package.descriptor.id
                        )));
                    }
                    Ok(())
                };
                tokio::time::timeout(Duration::from_secs(hook.timeout_seconds), operation)
                    .await
                    .map_err(|_| {
                        CoreError::Tool(format!(
                            "plugin {} hook {event} exceeded its time limit",
                            package.descriptor.id
                        ))
                    })??;
                #[cfg(unix)]
                {
                    process_group.0 = None;
                }
                Ok(())
                }.await;
                tracing::info!(
                    installation_id = %installation_id,
                    plugin_id = %package.descriptor.id,
                    version = %package.descriptor.version,
                    event,
                    success = result.is_ok(),
                    latency_ms = started.elapsed().as_millis() as u64,
                    "Marketplace hook executed"
                );
                if let Some(path) = &self.audit_path {
                    let record = super::hook_audit::Record {
                        timestamp_ms: chrono::Utc::now().timestamp_millis(),
                        installation_id: installation_id.clone(),
                        plugin_id: package.descriptor.id.clone(),
                        version: package.descriptor.version.clone(),
                        event: event.into(),
                        success: result.is_ok(),
                        latency_ms: started.elapsed().as_millis() as u64,
                    };
                    let path = path.clone();
                    let written = tokio::task::spawn_blocking(move || {
                        super::hook_audit::append(&path, &record)
                    })
                    .await;
                    if !matches!(written, Ok(Ok(()))) {
                        tracing::warn!("Marketplace hook audit persistence failed");
                    }
                }
                result?;
            }
        }
        Ok(())
    }
    pub(in crate::local_runtime) fn wrap_llm(&self, inner: Arc<dyn LlmPort>) -> Arc<dyn LlmPort> {
        Arc::new(HookLlm {
            inner,
            hooks: self.clone(),
        })
    }
    pub(in crate::local_runtime) fn wrap_tools(
        &self,
        inner: Arc<dyn ToolHost>,
    ) -> Arc<dyn ToolHost> {
        Arc::new(HookTools {
            inner,
            hooks: self.clone(),
        })
    }
}
#[cfg(unix)]
struct ProcessGroup(Option<u32>);
#[cfg(unix)]
impl Drop for ProcessGroup {
    fn drop(&mut self) {
        if let Some(id) = self.0 {
            // SAFETY: this PID was just created in a dedicated process group; a negative
            // PID terminates only that owned group, including its descendants.
            unsafe {
                libc::kill(-(id as i32), libc::SIGKILL);
            }
        }
    }
}
struct HookLlm {
    inner: Arc<dyn LlmPort>,
    hooks: Hooks,
}
#[async_trait]
impl LlmPort for HookLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        self.inner.extract_memory(episode).await
    }
    async fn extract_relationships(&self, memory: &Memory) -> CoreResult<Vec<RelationshipDraft>> {
        self.inner.extract_relationships(memory).await
    }
    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[String],
    ) -> CoreResult<AgentAction> {
        self.hooks.run("before_request").await?;
        self.inner.decide(goal, round, transcript, tools).await
    }
    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[ToolDefinition],
    ) -> CoreResult<AgentAction> {
        self.hooks.run("before_request").await?;
        self.inner
            .decide_with_tools(goal, round, transcript, tools)
            .await
    }
}
struct HookTools {
    inner: Arc<dyn ToolHost>,
    hooks: Hooks,
}
#[async_trait]
impl ToolHost for HookTools {
    fn list_tools(&self) -> Vec<String> {
        self.inner.list_tools()
    }
    fn tool_definition(&self, name: &str) -> Option<ToolDefinition> {
        self.inner.tool_definition(name)
    }
    fn tool_definitions(&self) -> CoreResult<Vec<ToolDefinition>> {
        self.inner.tool_definitions()
    }
    fn can_dispatch(&self, name: &str) -> bool {
        self.inner.can_dispatch(name)
    }
    async fn call(&self, name: &str, input: &str) -> CoreResult<String> {
        let result = self.inner.call(name, input).await?;
        self.hooks.run("after_tool_execute").await?;
        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct Model(Arc<AtomicUsize>);
    #[async_trait]
    impl LlmPort for Model {
        async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
            Err(CoreError::Tool("unused".into()))
        }
        async fn decide(
            &self,
            _: &str,
            _: u64,
            _: &[TranscriptEntry],
            _: &[String],
        ) -> CoreResult<AgentAction> {
            self.0.fetch_add(1, Ordering::SeqCst);
            Err(CoreError::Tool("model reached".into()))
        }
    }
    struct Tools(Arc<AtomicUsize>);
    #[async_trait]
    impl ToolHost for Tools {
        fn list_tools(&self) -> Vec<String> {
            vec!["echo".into()]
        }
        fn tool_definitions(&self) -> CoreResult<Vec<ToolDefinition>> {
            Err(CoreError::Tool("custom contract result".into()))
        }
        fn can_dispatch(&self, name: &str) -> bool {
            name == "echo" || name == "hidden_alias"
        }
        async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
            self.0.fetch_add(1, Ordering::SeqCst);
            Ok("tool-result".into())
        }
    }
    fn hooks(event: &str, command: &str, timeout_seconds: u64) -> Hooks {
        let mut package = super::super::package::parse(
            &super::super::tests::example().join("plugins/marketplace-demo"),
            "test",
        )
        .unwrap();
        package.hooks.clear();
        package.hooks.insert(
            event.into(),
            vec![super::super::package::Hook {
                command: command.into(),
                timeout_seconds,
            }],
        );
        Hooks {
            packages: vec![("test-installation".into(), package)],
            audit_path: None,
            _leases: Arc::new(vec![]),
        }
    }
    #[tokio::test]
    async fn hooks_stop_failed_requests_and_preserve_exact_tool_contracts() {
        let model_calls = Arc::new(AtomicUsize::new(0));
        let llm = hooks("before_request", "/usr/bin/false", 30)
            .wrap_llm(Arc::new(Model(model_calls.clone())));
        assert!(llm
            .decide("goal", 0, &[], &[])
            .await
            .unwrap_err()
            .to_string()
            .contains("hook before_request failed"));
        assert_eq!(model_calls.load(Ordering::SeqCst), 0);
        let tool_calls = Arc::new(AtomicUsize::new(0));
        let tools = hooks("after_tool_execute", "/usr/bin/false", 30)
            .wrap_tools(Arc::new(Tools(tool_calls.clone())));
        assert!(tools.can_dispatch("hidden_alias"));
        assert!(tools
            .tool_definitions()
            .unwrap_err()
            .to_string()
            .contains("custom contract result"));
        assert!(tools
            .call("echo", "{}")
            .await
            .unwrap_err()
            .to_string()
            .contains("hook after_tool_execute failed"));
        assert_eq!(tool_calls.load(Ordering::SeqCst), 1);
    }
    #[cfg(unix)]
    #[tokio::test]
    async fn timeout_terminates_owned_hook_descendants() {
        let marker =
            std::env::temp_dir().join(format!("market-hook-timeout-{}", uuid::Uuid::new_v4()));
        let command = format!("(sleep 2; touch '{}') & wait", marker.to_string_lossy());
        let result = hooks("session_start", &command, 1)
            .run("session_start")
            .await;
        assert!(result.unwrap_err().to_string().contains("time limit"));
        tokio::time::sleep(Duration::from_millis(1200)).await;
        assert!(
            !marker.exists(),
            "timed out hook descendant must not survive"
        );
    }
}

#[cfg(test)]
mod audit_tests {
    use super::*;
    #[tokio::test]
    async fn audit_records_all_events_and_failures_without_command_or_payload() {
        let directory = super::super::sources::Scratch::new(&std::env::temp_dir()).unwrap();
        let audit_path = directory.0.join("hooks-audit.jsonl");
        let mut package = super::super::package::parse(
            &super::super::tests::example().join("plugins/marketplace-demo"),
            "test",
        )
        .unwrap();
        for event in ["session_start", "before_request", "after_tool_execute"] {
            package.hooks.insert(
                event.into(),
                vec![super::super::package::Hook {
                    command: "/usr/bin/true diagnostic-secret-canary".into(),
                    timeout_seconds: 30,
                }],
            );
        }
        let mut hooks = Hooks {
            packages: vec![("audit-installation".into(), package)],
            audit_path: Some(audit_path.clone()),
            _leases: Arc::new(vec![]),
        };
        for event in ["session_start", "before_request", "after_tool_execute"] {
            hooks.run(event).await.unwrap();
        }
        hooks.packages[0]
            .1
            .hooks
            .get_mut("after_tool_execute")
            .unwrap()[0]
            .command = "/usr/bin/false diagnostic-secret-canary".into();
        assert!(hooks.run("after_tool_execute").await.is_err());

        let persisted = std::fs::read_to_string(&audit_path).unwrap();
        let records: Vec<serde_json::Value> = persisted
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect();
        assert_eq!(records.len(), 4);
        assert!(records[..3].iter().all(|record| record["success"] == true));
        assert_eq!(records[3]["success"], false);
        for record in &records {
            assert_eq!(record.as_object().unwrap().len(), 7);
            assert_eq!(record["installation_id"], "audit-installation");
            assert!(record["timestamp_ms"].as_i64().unwrap() > 0);
        }
        assert!(!persisted.contains("diagnostic-secret-canary"));
        assert!(!persisted.contains("/usr/bin/"));
        for event in ["session_start", "before_request", "after_tool_execute"] {
            assert!(records.iter().any(|record| record["event"] == event));
        }
        assert!(!persisted.contains("PLUGIN_ROOT"));
    }
}
