//! The assembled native engine must advertise scoped MCP tools before approval.

use super::*;
use crate::local_runtime::{self as local, execution_selection::ExecutionSelection};
use agistack_core::{agent::types::SessionStatus, tool_definition::ToolDefinition};
use axum::{body::Body, http::Request, routing::post, Json, Router};
use serde_json::Value;
use std::{collections::VecDeque, sync::atomic::Ordering};
use tokio::{net::TcpListener, sync::Mutex};
use tower::ServiceExt;

const TOKEN: &str = "mcp-catalog-test-session";
const CONTRACTS: &str =
    "Available tool definitions (input_schema constrains each tool's input_json):\n";
const SERVER: &str = r#"import json,sys
audit=sys.argv[1]
def tool(name,app=None):
 value={'name':name,'inputSchema':{'type':'object'},'annotations':{'readOnlyHint':True}}
 if app is not None:
  value['_meta']={'ui':{'resourceUri':'ui://catalog/main.html','visibility':['app'] if app else ['model','app']}}
 return value
tools=[tool('render_main',False),tool('increment_main',True),tool('render_sibling',False),
       tool('increment_sibling',True),tool('inspect_counts'),tool('hidden_probe')]
for line in sys.stdin:
 request=json.loads(line)
 if 'id' not in request: continue
 method=request['method']
 if method=='initialize':
  result={'protocolVersion':'2024-11-05','capabilities':{'tools':{},'resources':{}},'serverInfo':{'name':'catalog','version':'1'}}
 elif method=='tools/list': result={'tools':tools}
 elif method=='tools/call':
  with open(audit,'a') as output: output.write(request['params']['name']+'\n')
  result={'content':[{'type':'text','text':'fixture result'}]}
 elif method=='resources/read':
  result={'contents':[{'uri':'ui://catalog/main.html','mimeType':'text/html','text':'<main>catalog</main>'}]}
 else: result={}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
"#;

struct Fixture {
    root: PathBuf,
    state: Arc<local::LocalRuntimeState>,
    conversation: LocalConversation,
    run: DesktopRun,
    server_id: String,
    definition: McpServerDefinitionInput,
    requests: Arc<Mutex<Vec<Value>>>,
    actions: Arc<Mutex<VecDeque<AgentAction>>>,
    shutdown: Option<tokio::sync::oneshot::Sender<()>>,
}

impl Fixture {
    async fn new(profile: DesktopPermissionProfile) -> Self {
        let state = local::tests::test_state(TOKEN);
        let root = state.workspace_root.lock().unwrap().clone();
        let script = root.join("server.py");
        fs::write(&script, SERVER).unwrap();
        state.mock_llm_enabled.store(0, Ordering::Release);
        let definition = McpServerDefinitionInput {
            name: "native-catalog-fixture".into(),
            description: None,
            transport: McpTransport::Stdio,
            command: vec![
                python_executable().to_string_lossy().into_owned(),
                script.to_string_lossy().into_owned(),
                root.join("calls.txt").to_string_lossy().into_owned(),
            ],
            cwd: Some(".".into()),
            vault_env_refs: BTreeMap::new(),
            enabled: true,
        };
        let server = state
            .mcp_supervisor
            .create_server(
                &scope("local-project"),
                definition.clone(),
                "catalog-create",
            )
            .unwrap();
        state
            .mcp_supervisor
            .list_tools(&scope("local-project"), &server.id)
            .await
            .unwrap();
        let server = state
            .mcp_supervisor
            .server(&scope("local-project"), &server.id)
            .unwrap()
            .unwrap();
        assert_eq!(server.runtime_status, "healthy");
        assert_eq!(server.discovered_tools.len(), 6);
        let run = running_run(&state.session_store, &root, "catalog", profile).unwrap();
        let mut conversation = state
            .session_store
            .conversation(&run.conversation_id)
            .unwrap()
            .unwrap();
        conversation.workspace_id = None;
        state
            .session_store
            .update_conversation(&conversation)
            .unwrap();

        let requests = Arc::new(Mutex::new(Vec::new()));
        let actions = Arc::new(Mutex::new(VecDeque::<AgentAction>::new()));
        let app = Router::new().route(
            "/v1/chat/completions",
            post({
                let requests = requests.clone();
                let actions = actions.clone();
                move |Json(body): Json<Value>| {
                    let requests = requests.clone();
                    let actions = actions.clone();
                    async move {
                        requests.lock().await.push(body);
                        let action = actions.lock().await.pop_front().unwrap_or(AgentAction::Finish {
                            answer: "catalog observed".into(),
                        });
                        Json(json!({"choices":[{"message":{"content":serde_json::to_string(&action).unwrap()}}]}))
                    }
                }
            }),
        );
        let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
        let address = listener.local_addr().unwrap();
        let (shutdown, receiver) = tokio::sync::oneshot::channel();
        tokio::spawn(async move {
            axum::serve(listener, app)
                .with_graceful_shutdown(async move {
                    let _ = receiver.await;
                })
                .await
                .unwrap();
        });
        let configured = local::local_router(state.clone())
            .oneshot(Request::builder().method("PUT")
                .uri("/api/v1/llm-providers/local-runtime")
                .header("authorization", format!("Bearer {TOKEN}"))
                .header("x-agistack-launch", TOKEN)
                .header("content-type", "application/json")
                .body(Body::from(json!({
                    "provider_type":"openai_compatible", "base_url":format!("http://{address}/v1"),
                    "auth_method":"none", "llm_model":"catalog-model", "allowed_models":["catalog-model"],
                    "is_active":true, "expected_revision":0
                }).to_string())).unwrap())
            .await.unwrap();
        assert_eq!(configured.status(), axum::http::StatusCode::OK);
        Self {
            root,
            state,
            conversation,
            run,
            server_id: server.id,
            definition,
            requests,
            actions,
            shutdown: Some(shutdown),
        }
    }

    async fn model_catalog(&self) -> Vec<ToolDefinition> {
        self.requests.lock().await.clear();
        let engine = self
            .state
            .agent_engine_for_role(&self.conversation, Some(&self.run), None)
            .await
            .unwrap();
        let result = engine
            .run(
                &Uuid::new_v4().to_string(),
                "Inspect the available tools",
                Some("local-project"),
            )
            .await
            .unwrap();
        assert_eq!(result.status, SessionStatus::Finished);
        let requests = self.requests.lock().await;
        let content = requests[0]["messages"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|message| message["content"].as_str())
            .find_map(|content| content.split_once(CONTRACTS).map(|(_, value)| value))
            .expect("actual HTTP request includes tool contracts");
        serde_json::from_str(content.lines().next().unwrap()).unwrap()
    }

    fn select_agent(&self, servers: &[&str], tools: &[&str]) {
        let id = format!("catalog-agent-{}", Uuid::new_v4());
        self.state
            .session_store
            .put_managed_resource(
                local::resource_registry::ManagedResourceKind::Agent,
                "project",
                "local-project",
                &id,
                "active",
                None,
                json!({
                    "id":id,"name":id,"status":"active","enabled":true,"allowed_tools":tools,
                    "allowed_mcp_servers":servers,"allowed_skills":[],"can_spawn":false
                }),
                chrono::Utc::now().timestamp_millis(),
            )
            .unwrap();
        self.state
            .session_store
            .save_execution_selection(
                &self.conversation.id,
                &self.run.message_id,
                &ExecutionSelection {
                    agent_id: Some(id),
                    ..Default::default()
                },
                &local::now_iso(),
            )
            .unwrap();
    }

    fn no_calls(&self) {
        assert!(
            !self.root.join("calls.txt").exists(),
            "listing or denied dispatch must not invoke MCP"
        );
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[tokio::test]
async fn assembled_model_catalog_exposes_requestable_mcp_without_dispatching() {
    for profile in [
        DesktopPermissionProfile::ReadOnly,
        DesktopPermissionProfile::WorkspaceWrite,
    ] {
        let fixture = Fixture::new(profile).await;
        let catalog = fixture.model_catalog().await;
        let mcp = catalog
            .iter()
            .filter(|tool| tool.name.starts_with("mcp__"))
            .collect::<Vec<_>>();
        assert_eq!(
            mcp.len(),
            4,
            "healthy model-visible MCP tools must be discoverable before approval"
        );
        let render = mcp
            .iter()
            .find(|tool| tool.name.contains("render_main"))
            .unwrap();
        assert!(
            mcp.iter().all(|tool| !tool.name.contains("increment_")),
            "App-only tools must stay hidden"
        );
        fixture.no_calls();
        fixture
            .actions
            .lock()
            .await
            .push_back(AgentAction::CallTool {
                tool: render.name.clone(),
                input_json: "{}".into(),
            });
        fixture.model_catalog().await;
        fixture.no_calls();
        let requests = fixture.requests.lock().await;
        assert_eq!(requests.len(), 2);
        assert!(requests[1]
            .to_string()
            .contains("outside the approved permission profile"));
    }
}

#[tokio::test]
async fn assembled_mcp_catalog_respects_agent_roster_and_server_revocation() {
    let fixture = Fixture::new(DesktopPermissionProfile::WorkspaceWrite).await;
    for (servers, tools) in [
        (vec![], vec!["*"]),
        (vec!["other-server"], vec!["*"]),
        (vec!["*"], vec!["read"]),
    ] {
        fixture.select_agent(&servers, &tools);
        assert!(fixture
            .model_catalog()
            .await
            .iter()
            .all(|tool| !tool.name.starts_with("mcp__")));
        fixture.no_calls();
    }
    fixture.select_agent(&[&fixture.server_id], &["*"]);
    assert_eq!(
        fixture
            .model_catalog()
            .await
            .iter()
            .filter(|tool| tool.name.starts_with("mcp__"))
            .count(),
        4
    );
    let previous = McpAgentToolHost::new(
        fixture.state.mcp_supervisor.clone(),
        scope("local-project"),
        fixture.run.id.clone(),
        Some(&[fixture.server_id.clone()]),
    )
    .unwrap();
    let canonical = previous
        .list_tools()
        .into_iter()
        .find(|tool| tool.contains("render_main"))
        .unwrap();
    let mut disabled = fixture.definition.clone();
    disabled.enabled = false;
    fixture
        .state
        .mcp_supervisor
        .update_server(
            &scope("local-project"),
            &fixture.server_id,
            disabled,
            1,
            "catalog-disable",
        )
        .unwrap();
    assert!(fixture
        .model_catalog()
        .await
        .iter()
        .all(|tool| !tool.name.starts_with("mcp__")));
    let error = previous.call(&canonical, "{}").await.unwrap_err();
    assert!(error.to_string().contains("local_mcp_server_disabled"));
    fixture.no_calls();
}
