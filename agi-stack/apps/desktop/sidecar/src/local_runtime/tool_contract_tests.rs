use super::*;
use agistack_core::ports::ToolDefinition;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

struct DeclaredHost;
#[async_trait]
impl ToolHost for DeclaredHost {
    fn list_tools(&self) -> Vec<String> {
        vec!["read".into(), "write".into()]
    }
    fn tool_definition(&self, name: &str) -> Option<ToolDefinition> {
        Some(ToolDefinition::new(
            name,
            format!("contract for {name}"),
            json!({"type":"object","required":["path"]}),
        ))
    }
    async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
        Ok("read result".into())
    }
}

fn profile(tools: &[&str]) -> execution_profile::ExecutionProfile {
    execution_profile::ExecutionProfile {
        agent: execution_profile::SelectedResource {
            id: "fixture".into(),
            name: "fixture".into(),
        },
        skill: None,
        subagent: None,
        allowed_tools: tools.iter().map(|name| (*name).into()).collect(),
        allowed_mcp_servers: vec![],
        instructions: "Inspect only approved resources.".into(),
    }
}

fn plan_host(store: DesktopSessionStore) -> Arc<dyn ToolHost> {
    let combined = Arc::new(fan_out_tool_host::FanOutToolHost::new(vec![Arc::new(
        DeclaredHost,
    )]));
    let profiled = Arc::new(execution_profile::ProfiledToolHost::new(
        combined,
        &profile(&["read"]),
    ));
    Arc::new(PlanModeToolHost::new(
        profiled,
        store,
        "contract-plan".into(),
    ))
}

async fn endpoint(anthropic: bool) -> (String, tokio::task::JoinHandle<serde_json::Value>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut bytes = Vec::new();
        let offset;
        loop {
            let mut buffer = [0; 4096];
            let n = socket.read(&mut buffer).await.unwrap();
            assert!(n > 0);
            bytes.extend_from_slice(&buffer[..n]);
            if let Some(i) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
                let header = String::from_utf8_lossy(&bytes[..i]);
                let size: usize = header
                    .lines()
                    .find_map(|line| {
                        let (name, value) = line.split_once(':')?;
                        name.eq_ignore_ascii_case("content-length")
                            .then(|| value.trim().parse().unwrap())
                    })
                    .unwrap();
                if bytes.len() >= i + 4 + size {
                    offset = i + 4;
                    break;
                }
            }
        }
        let input = json!({"tasks":[{"content":"Read README","priority":"high"}]});
        let action = if anthropic {
            json!({"kind":"call_tool","tool":"submit_plan","input_json":input.to_string()})
        } else {
            json!({"kind":"call_tool","tool":"submit_plan","input_json":input})
        };
        let (kind, body) = if anthropic {
            ("text/event-stream",format!("event: content_block_delta\ndata: {}\n\nevent: message_stop\ndata: {{\"type\":\"message_stop\"}}\n\n",json!({"type":"content_block_delta","delta":{"type":"text_delta","text":action.to_string()}})))
        } else {
            (
                "application/json",
                json!({"choices":[{"message":{"content":action.to_string()}}]}).to_string(),
            )
        };
        socket.write_all(format!("HTTP/1.1 200 OK\r\ncontent-type: {kind}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        serde_json::from_slice(&bytes[offset..]).unwrap()
    });
    (format!("http://{address}"), server)
}

struct FailedTypedLlm {
    stall: bool,
}
#[async_trait]
impl LlmPort for FailedTypedLlm {
    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        unreachable!()
    }
    async fn decide(
        &self,
        _: &str,
        _: u64,
        _: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        panic!("typed failover must not fall back to name-only decide")
    }
    async fn decide_with_tools(
        &self,
        _: &str,
        _: u64,
        _: &[TranscriptEntry],
        tools: &[ToolDefinition],
    ) -> CoreResult<AgentAction> {
        assert_eq!(
            tools.last().unwrap(),
            &plan_tool_contract::submit_plan_definition()
        );
        if self.stall {
            return std::future::pending().await;
        }
        Err(CoreError::Llm("fixture candidate failed".into()))
    }
}

#[tokio::test]
async fn declared_contract_survives_native_engine_metering_failover_and_http() {
    for anthropic in [false, true] {
        let store = DesktopSessionStore::in_memory().unwrap();
        let tools = plan_host(store.clone());
        let (url, server) = endpoint(anthropic).await;
        let provider: Arc<dyn LlmPort> = if anthropic {
            Arc::new(AnthropicAgentLlm {
                inner: AnthropicLlm::new(url, "fixture"),
            })
        } else {
            Arc::new(HttpLlm::new(url, "fixture"))
        };
        let metered = Arc::new(MeteredLlm {
            inner: Arc::new(FailoverLlm {
                candidates: vec![
                    Arc::new(FailedTypedLlm { stall: true }),
                    Arc::new(FailedTypedLlm { stall: false }),
                    provider,
                ],
                candidate_timeout: std::time::Duration::from_millis(200),
            }),
            session_store: store.clone(),
            provider_id: "fixture".into(),
            tenant_id: "fixture".into(),
            model_name: "fixture".into(),
        });
        let llm = Arc::new(execution_profile::ProfiledLlm::new(
            metered,
            &profile(&["read"]),
        ));
        let engine = ReActEngine::new(
            llm,
            tools,
            Arc::new(agistack_adapters_mem::InMemoryCheckpointStore::new()),
            Arc::new(SystemClock),
        )
        .with_terminal_tools([SUBMIT_PLAN_TOOL_NAME]);
        let result = engine
            .run("contract-plan", "Prepare a plan", None)
            .await
            .unwrap();
        assert_eq!(result.status, SessionStatus::Finished);
        let request = server.await.unwrap();
        let prompt = request["messages"][if anthropic { 0 } else { 1 }]["content"]
            .as_str()
            .unwrap();
        let definition =
            serde_json::to_string(&plan_tool_contract::submit_plan_definition()).unwrap();
        // Anthropic's legacy user envelope is itself JSON, so inspect its goal.
        let goal = if anthropic {
            serde_json::from_str::<serde_json::Value>(prompt).unwrap()["goal"]
                .as_str()
                .unwrap()
                .to_owned()
        } else {
            prompt.to_owned()
        };
        assert!(goal.contains(&definition));
        assert!(goal.contains("contract for read"));
        assert!(!goal.contains("contract for write"));
        let tasks = store.list_agent_plan_tasks("contract-plan").unwrap();
        assert_eq!(tasks.len(), 1);
        assert_eq!(tasks[0]["content"], "Read README");
    }
}

#[tokio::test]
async fn plan_schema_matches_strict_content_validation_and_legacy_steps_remain_supported() {
    let store = DesktopSessionStore::in_memory().unwrap();
    let host = plan_host(store.clone());
    let definition = host.tool_definition("submit_plan").unwrap();
    let schema = definition.input_schema.unwrap();
    assert_eq!(schema["properties"]["tasks"]["minItems"], 1);
    assert_eq!(schema["properties"]["tasks"]["maxItems"], 50);
    assert_eq!(
        schema["properties"]["tasks"]["items"]["required"],
        json!(["content"])
    );
    assert_eq!(
        schema["properties"]["tasks"]["items"]["properties"]["content"]["pattern"],
        "\\S"
    );
    for input in [
        json!({"tasks":[{"description":"wrong field"}]}),
        json!({"tasks":[]}),
        json!({"tasks":[{"content":"  "}]}),
        json!({"tasks":[{"content":"Read","priority":"urgent"}]}),
        json!({"tasks":vec![json!({"content":"Read"});51]}),
    ] {
        assert!(host.call("submit_plan", &input.to_string()).await.is_err());
        assert!(store
            .list_agent_plan_tasks("contract-plan")
            .unwrap()
            .is_empty());
    }
    host.call(
        "submit_plan",
        r#"{"steps":[{"description":"Read existing file"}]}"#,
    )
    .await
    .unwrap();
    assert_eq!(
        store.list_agent_plan_tasks("contract-plan").unwrap()[0]["content"],
        "Read existing file"
    );
    assert!(host.tool_definition("write").is_none());
    assert!(host
        .tool_definitions()
        .unwrap()
        .iter()
        .all(|tool| tool.name != "write"));
}

#[test]
fn declared_identity_mismatch_fails_closed_instead_of_name_only_fallback() {
    struct Misbound;
    #[async_trait]
    impl ToolHost for Misbound {
        fn list_tools(&self) -> Vec<String> {
            vec!["submit_plan".into()]
        }
        fn tool_definition(&self, _: &str) -> Option<ToolDefinition> {
            Some(ToolDefinition::new(
                "other_tool",
                "Wrong identity",
                json!({"type":"object"}),
            ))
        }
        async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
            unreachable!()
        }
    }
    let error = Misbound.tool_definitions().unwrap_err();
    assert!(error
        .to_string()
        .contains("tool_definition_identity_mismatch"));
}
