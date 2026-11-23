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
    pub(super) packages: Vec<(String, Package)>,
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
                self.run_one(installation_id, package, hook, event, None)
                    .await?;
            }
        }
        Ok(())
    }

    pub(super) async fn run_one(
        &self,
        installation_id: &str,
        package: &Package,
        hook: &super::package::Hook,
        event: &str,
        delivery: Option<&super::hook_deliveries::Delivery>,
    ) -> CoreResult<()> {
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
            let mut payload = json!({"event":event,"plugin_id":package.descriptor.id,"version":package.descriptor.version});
            if let Some(delivery) = delivery {
                payload["delivery_id"] = json!(delivery.id);
                payload["invocation_id"] = json!(delivery.invocation_id);
            }
            let payload = payload.to_string();
            let operation = async {
                if let Some(mut stdin) = child.stdin.take() {
                    match stdin.write_all(payload.as_bytes()).await {
                        Ok(()) => {}
                        // A hook that exits before reading stdin closes the pipe.
                        // The process status below is the success signal.
                        Err(error) if error.kind() == std::io::ErrorKind::BrokenPipe => {}
                        Err(_) => {
                            return Err(CoreError::Tool("plugin hook input failed".into()));
                        }
                    }
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
            }
        .await;
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
                installation_id: installation_id.to_owned(),
                plugin_id: package.descriptor.id.clone(),
                version: package.descriptor.version.clone(),
                event: event.into(),
                delivery_id: delivery.map(|delivery| delivery.id.clone()),
                invocation_id: delivery.map(|delivery| delivery.invocation_id.clone()),
                success: result.is_ok(),
                latency_ms: started.elapsed().as_millis() as u64,
            };
            let path = path.clone();
            let written =
                tokio::task::spawn_blocking(move || super::hook_audit::append(&path, &record))
                    .await;
            if !matches!(written, Ok(Ok(()))) {
                tracing::warn!("Marketplace hook audit persistence failed");
            }
        }
        result
    }

    async fn notify_tool_completed(&self) {
        if !self.packages.iter().any(|(_, p)| {
            p.hooks
                .get("after_tool_execute")
                .is_some_and(|hooks| !hooks.is_empty())
        }) {
            return;
        }
        let Some(root) = self.audit_path.as_deref().and_then(std::path::Path::parent) else {
            return;
        };
        let hooks = self.clone();
        let root = root.to_owned();
        // Once the tool has succeeded this task owns delivery independently of the caller.
        // Only wait for the durable enqueue. Slow or failed hooks cannot change the tool result.
        let queued = tokio::spawn(async move {
            let ids = super::hook_deliveries::enqueue(&root, &hooks.packages).await?;
            tokio::spawn(async move {
                for id in ids {
                    if super::hook_deliveries::deliver(&root, &id, &hooks).await.is_err() {
                        tracing::warn!(delivery_id = %id, "Marketplace post-tool hook remains pending");
                    }
                }
            });
            Ok::<_,String>(())
        }).await;
        if !matches!(queued, Ok(Ok(()))) {
            tracing::error!("Failed to enqueue marketplace post-tool notifications");
        }
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
    async fn decide_with_tools_stream(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[agistack_core::ports::ToolDefinition],
        on_text: &(dyn for<'text> Fn(&'text str) + Send + Sync),
    ) -> CoreResult<AgentAction> {
        self.hooks.run("before_request").await?;
        self.inner
            .decide_with_tools_stream(goal, round, transcript, tools, on_text)
            .await
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
        self.hooks.notify_tool_completed().await;
        Ok(result)
    }
    async fn call_with_content(
        &self,
        name: &str,
        input: &str,
    ) -> CoreResult<agistack_core::ports::ToolResult> {
        let result = self.inner.call_with_content(name, input).await?;
        self.hooks.notify_tool_completed().await;
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
        assert_eq!(tools.call("echo", "{}").await.unwrap(), "tool-result");
        assert_eq!(tool_calls.load(Ordering::SeqCst), 1);
    }
    #[cfg(unix)]
    #[tokio::test]
    async fn retries_one_persisted_delivery_without_reexecuting_the_tool_or_siblings() {
        use super::super::{
            auth_root, load, package, save,
            tests::{example, fixture, request},
            Installation,
        };
        use axum::http::{Method, StatusCode};
        let (state, auth, directory) = fixture();
        let root = auth_root(&state, &auth).unwrap();
        let snapshot = root
            .join("snapshots")
            .join(uuid::Uuid::new_v4().to_string());
        package::snapshot(&example().join("plugins/marketplace-demo"), &snapshot).unwrap();
        let mut package = package::parse(&snapshot, "test").unwrap();
        let ready = directory.join("hook-available");
        let good = directory.join("good-deliveries");
        let attempts = directory.join("retry-deliveries");
        package.hooks.insert(
            "after_tool_execute".into(),
            vec![
                package::Hook {
                    command: format!(
                        "cat >> '{}' && echo >> '{}'",
                        good.display(),
                        good.display()
                    ),
                    timeout_seconds: 10,
                },
                package::Hook {
                    command: format!(
                        "cat >> '{}' && echo >> '{}' && test -f '{}'",
                        attempts.display(),
                        attempts.display(),
                        ready.display()
                    ),
                    timeout_seconds: 10,
                },
            ],
        );
        let mut data = load(&root).unwrap();
        let install: Installation = serde_json::from_value(json!({
            "id":"install", "plugin_id":package.descriptor.id, "source_id":"test", "name":"Test",
            "version":package.descriptor.version, "status":"enabled", "capabilities":["hooks"],
            "error":null, "package":package, "permissions":["hooks"]
        }))
        .unwrap();
        data.installations.push(install);
        save(&root, &data).unwrap();
        let calls = Arc::new(AtomicUsize::new(0));
        let tools = Hooks::capture(
            &state,
            &auth.workspace.tenant_id,
            &auth.workspace.project_id,
        )
        .unwrap()
        .wrap_tools(Arc::new(Tools(calls.clone())));
        assert_eq!(
            tools
                .call_with_content("echo", "{}")
                .await
                .unwrap()
                .output_json,
            "tool-result"
        );
        tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                let items = load(&root).unwrap().hook_deliveries;
                if items.len() == 1
                    && items
                        .values()
                        .all(|d| d.public()["attempts"] == 1 && d.public()["status"] == "pending")
                {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        drop(tools);
        let pending_path = "/api/v1/plugin-marketplace/v3/hook-deliveries";
        let (status, pending) =
            request(state.clone(), &auth, Method::GET, pending_path, json!({})).await;
        assert_eq!(status, StatusCode::OK);
        let item = &pending["items"][0];
        let delivery_id = item["id"].as_str().unwrap();
        std::fs::write(ready, []).unwrap();
        let (status, receipt) = request(
            state.clone(),
            &auth,
            Method::POST,
            &format!("{pending_path}/{delivery_id}/retry"),
            json!({}),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{receipt}");
        assert_eq!(receipt["status"], "delivered");
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(std::fs::read_to_string(good).unwrap().lines().count(), 1);
        let payloads = std::fs::read_to_string(attempts)
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str::<serde_json::Value>(line).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(payloads.len(), 2);
        assert_eq!(payloads[0], payloads[1]);
        assert_eq!(payloads[0]["invocation_id"], item["invocation_id"]);
        assert_eq!(payloads[0]["delivery_id"], delivery_id);
        assert!(load(&root).unwrap().hook_deliveries.is_empty());
        std::fs::remove_dir_all(directory).unwrap();
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
