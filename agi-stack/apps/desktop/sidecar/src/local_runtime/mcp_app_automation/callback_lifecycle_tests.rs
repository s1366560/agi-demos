//! Real stdio callbacks with App publication enabled; the execution grant is a fixture.
#[path = "callback_error_tests.rs"]
mod callback_error_tests;
#[path = "cloud_candidate_tests.rs"]
mod cloud_candidate_tests;
#[path = "continuation_tests.rs"]
mod continuation_tests;
#[cfg(target_os = "macos")]
#[path = "formal_resume_tests.rs"]
mod formal_resume_tests;
#[path = "renderer_callback_nonce_tests.rs"]
mod renderer_callback_nonce_tests;
use super::*;
use crate::local_runtime::{
    execution_authority::ScopedExecution,
    mcp_agent_tool_host::{legacy_exposed_tool_name, McpAgentToolHost},
    mcp_supervisor::{McpServerDefinitionInput, McpTransport},
};
use agistack_core::{
    agent::tool_policy::ToolPolicyContext,
    ports::{ToolHost, ToolResult},
};
use async_trait::async_trait;
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::atomic::{AtomicU64, AtomicUsize, Ordering},
};

const CONVERSATION: &str = "callback-lifecycle-conversation";
const SERVER: &str = r#"import json,sys
counts={'main':0,'sibling':0,'hidden':0}
dispatches={}
main='ui://callback/main.html'; sibling='ui://callback/sibling.html'
def tool(name,uri=None,app_only=False):
 value={'name':name,'inputSchema':{'type':'object'},'annotations':{'readOnlyHint':True}}
 if uri: value['_meta']={'ui/resourceUri':uri,'visibility':['app'] if app_only else ['model','app']}
 return value
tools=[tool('render_main',main),tool('increment_main',main,True),
       tool('render_sibling',sibling),tool('increment_sibling',sibling,True),
       tool('hidden_probe'),tool('inspect_counts')]
collections={
 'resources/list':('resources',[{'name':'Main','uri':main},{'name':'Sibling','uri':sibling}]),
 'resources/templates/list':('resourceTemplates',[{'name':'Item','uriTemplate':'fixture://item/{id}'},{'name':'Record','uriTemplate':'fixture://record/{id}'}]),
 'prompts/list':('prompts',[{'name':'describe'},{'name':'summarize'}])}
for line in sys.stdin:
 request=json.loads(line)
 if 'id' not in request: continue
 method=request['method']; params=request.get('params',{})
 if method!='tools/call' or params.get('name')!='inspect_counts': dispatches[method]=dispatches.get(method,0)+1
 if method=='initialize':
  result={'protocolVersion':'2024-11-05','capabilities':{'tools':{},'resources':{},'prompts':{}},'serverInfo':{'name':'callback-lifecycle','version':'1'}}
 elif method=='tools/list': result={'tools':tools}
 elif method=='tools/call':
  name=params['name']
  if name=='increment_main': counts['main']+=1
  elif name=='increment_sibling': counts['sibling']+=1
  elif name=='hidden_probe': counts['hidden']+=1
  result={'content':[{'type':'text','text':json.dumps({'name':name,'arguments':params.get('arguments',{}),'counts':counts,'dispatches':dispatches})}]}
 elif method in collections:
  field,values=collections[method]; cursor=params.get('cursor')
  if cursor not in (None,'opaque + / cursor =='): raise ValueError('changed cursor')
  result={field:[values[0 if cursor is None else 1]]}
  if cursor is None: result['nextCursor']='opaque + / cursor =='
 elif method=='resources/read':
  result={'contents':[{'uri':params['uri'],'mimeType':'text/html','text':'<main>callback fixture</main>'}]}
 elif method=='prompts/get':
  result={'messages':[{'role':'user','content':{'type':'text','text':'catalog prompt'}}]}
 else: result={}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
"#;

struct Execution {
    scope: ExecutionScope,
    server_id: String,
    permit: Mutex<Option<(String, Value)>>,
    calls: AtomicUsize,
    tools: McpAgentToolHost,
}

#[async_trait]
impl ScopedExecution for Execution {
    fn scope(&self) -> &ExecutionScope {
        &self.scope
    }
    fn current(&self) -> CoreResult<()> {
        Ok(())
    }
    fn allowed_mcp_servers(&self) -> Vec<String> {
        vec![self.server_id.clone()]
    }
    async fn call(&self, tool: &str, input: &str) -> CoreResult<ToolResult> {
        assert_eq!(
            call_identity::active()?.engine_session_id(),
            self.scope.engine_session_id
        );
        assert!(crate::local_runtime::execution_authority::current_step_id().is_some());
        let arguments: Value = serde_json::from_str(input).unwrap();
        {
            let mut permit = self.permit.lock().unwrap();
            if !permit
                .as_ref()
                .is_some_and(|(name, value)| name == tool && value == &arguments)
            {
                return Err(denied("exact_callback_approval_required"));
            }
            let _ = permit.take();
        }
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.tools.call_with_content(tool, input).await
    }
}

struct Fixture {
    root: PathBuf,
    state: Arc<LocalRuntimeState>,
    scope: McpScope,
    server_id: String,
    execution: Arc<Execution>,
    _authority: Arc<ExecutionAuthority>,
    round: AtomicU64,
}

fn execution(
    state: &Arc<LocalRuntimeState>,
    scope: ExecutionScope,
    server_id: &str,
) -> Arc<Execution> {
    let tools = McpAgentToolHost::new(
        state.mcp_supervisor.clone(),
        mcp_scope(&scope),
        scope.run_id.clone(),
        Some(&[server_id.into()]),
    )
    .unwrap()
    .with_app_events(
        state.clone(),
        scope.conversation_id.clone(),
        "callback-message".into(),
    );
    Arc::new(Execution {
        scope,
        server_id: server_id.into(),
        permit: Mutex::new(None),
        calls: AtomicUsize::new(0),
        tools,
    })
}

impl Fixture {
    async fn new() -> Self {
        let root =
            std::env::temp_dir().join(format!("mcp-callback-lifecycle-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).unwrap();
        let script = root.join("server.py");
        std::fs::write(&script, SERVER).unwrap();
        let python = std::env::split_paths(&std::env::var_os("PATH").unwrap())
            .map(|entry| entry.join("python3"))
            .find(|path| path.is_file())
            .unwrap()
            .canonicalize()
            .unwrap();
        let state = crate::local_runtime::tests::test_state("mcp-callback-lifecycle");
        crate::local_runtime::tests::seed_plan_conversation(&state, CONVERSATION);
        let scope = McpScope {
            tenant_id: "local".into(),
            project_id: "local-project".into(),
        };
        let server = state
            .mcp_supervisor
            .create_server(
                &scope,
                McpServerDefinitionInput {
                    name: "callback-lifecycle".into(),
                    description: None,
                    transport: McpTransport::Stdio,
                    command: vec![
                        python.to_string_lossy().into(),
                        script.to_string_lossy().into(),
                    ],
                    cwd: None,
                    vault_env_refs: BTreeMap::new(),
                    enabled: true,
                },
                "create-callback-fixture",
            )
            .unwrap();
        state
            .mcp_supervisor
            .list_tools(&scope, &server.id)
            .await
            .unwrap();
        let execution = execution(
            &state,
            ExecutionScope {
                tenant_id: scope.tenant_id.clone(),
                project_id: scope.project_id.clone(),
                conversation_id: CONVERSATION.into(),
                run_id: "callback-run".into(),
                run_revision: 1,
                engine_session_id: "callback-engine".into(),
                device_id: None,
                connection_epoch: None,
                generation: 1,
            },
            &server.id,
        );
        let authority = Arc::new(ExecutionAuthority::LocalRun(execution.clone()));
        state
            .mcp_app_automation
            .register_authority(authority.clone());
        Self {
            root,
            state,
            scope,
            server_id: server.id,
            execution,
            _authority: authority,
            round: AtomicU64::new(1),
        }
    }

    fn events(&self) -> Vec<Value> {
        self.state
            .session_store
            .timeline(CONVERSATION, 100)
            .unwrap()
            .into_iter()
            .filter(|event| event["type"] == "mcp_app_result")
            .collect()
    }

    async fn model_call(&self, name: &str) -> Value {
        let tool = legacy_exposed_tool_name(&self.server_id, name);
        let output = call_identity::scope(
            &ToolPolicyContext {
                session_id: &self.execution.scope.engine_session_id,
                round: self.round.fetch_add(1, Ordering::SeqCst),
                tool: &tool,
            },
            self.execution.tools.call(&tool, "{}"),
        )
        .await
        .unwrap();
        serde_json::from_str(&output).unwrap()
    }

    async fn render(&self, name: &str) -> String {
        let before = self.events().len();
        self.model_call(name).await;
        let events = self.events();
        assert_eq!(
            events.len(),
            before + 1,
            "ordinary model renders still publish App events"
        );
        events.last().unwrap()["payload"]["automation_tab_id"]
            .as_str()
            .unwrap()
            .into()
    }

    async fn attach(&self, tab: &str) -> String {
        let nonce = {
            let tabs = self.state.mcp_app_automation.tabs.lock().unwrap();
            let current = &tabs[tab];
            if current.mount_cancelled {
                format!("fixture-remount-{}", uuid::Uuid::new_v4())
            } else {
                current
                    .mount_nonce
                    .clone()
                    .unwrap_or_else(|| "fixture-mount".into())
            }
        };
        self.state
            .mcp_app_automation
            .renderer_operation(
                &self.state,
                json!({"tabId":tab,"operation":"attach","mountNonce":nonce}),
            )
            .await
            .unwrap();
        self.registration(tab)
    }

    fn registration(&self, tab: &str) -> String {
        let tabs = self.state.mcp_app_automation.tabs.lock().unwrap();
        let current = tabs.get(tab).unwrap();
        assert!(current.attached);
        current.registration.clone().unwrap()
    }

    fn grant(&self, name: &str, arguments: Value) {
        *self.execution.permit.lock().unwrap() =
            Some((legacy_exposed_tool_name(&self.server_id, name), arguments));
    }

    async fn callback(&self, tab: &str, name: &str, arguments: Value) -> CoreResult<Value> {
        let nonce = self.state.mcp_app_automation.tabs.lock().unwrap()[tab]
            .mount_nonce
            .clone();
        self.state.mcp_app_automation.renderer_operation(&self.state,
            json!({"tabId":tab,"mountNonce":nonce,"operation":"tools/call","arguments":{"name":name,"arguments":arguments}}),
        ).await
    }

    async fn counts(&self) -> Value {
        payload(&self.model_call("inspect_counts").await)["counts"].clone()
    }

    fn assert_surface(&self, tab: &str, registration: &str, events: usize) {
        assert_eq!(self.registration(tab), registration);
        let registry = &self.state.mcp_app_automation;
        let (renderer, current) = registry
            .require_browser(&self.state, registration, &self.execution.scope)
            .unwrap();
        assert_eq!(renderer, tab);
        assert_eq!(current.registration.as_deref(), Some(registration));
        assert_eq!(
            registry.list(&self.state, &self.execution.scope)[0]["id"],
            registration
        );
        assert_eq!(
            registry.tabs.lock().unwrap().len(),
            1,
            "callback must not create another automation tab"
        );
        assert_eq!(
            self.events().len(),
            events,
            "callback must not publish another mcp_app_result"
        );
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        if let Ok(Some(server)) = self
            .state
            .mcp_supervisor
            .server(&self.scope, &self.server_id)
        {
            let _ = self.state.mcp_supervisor.delete_server(
                &self.scope,
                &self.server_id,
                server.revision,
                "cleanup-callback-fixture",
            );
        }
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn payload(result: &Value) -> Value {
    serde_json::from_str(result["content"][0]["text"].as_str().unwrap()).unwrap()
}

#[tokio::test]
async fn callbacks_keep_the_attached_surface_and_do_not_republish_model_app_results() {
    let fixture = Fixture::new().await;
    let tab = fixture.render("render_main").await;
    let handle = fixture.attach(&tab).await;
    let first = json!({"label":"native-main-proof","operation_id":"first"});
    assert!(fixture
        .callback(&tab, "increment_main", first.clone())
        .await
        .unwrap_err()
        .to_string()
        .contains("exact_callback_approval_required"));
    assert_eq!(
        fixture.counts().await,
        json!({"main":0,"sibling":0,"hidden":0})
    );
    fixture.grant("increment_main", first.clone());
    assert!(fixture
        .callback(&tab, "increment_main", json!({"operation_id":"different"}))
        .await
        .is_err());
    assert_eq!(fixture.execution.calls.load(Ordering::SeqCst), 0);
    let result = fixture
        .callback(&tab, "increment_main", first)
        .await
        .unwrap();
    assert_eq!(payload(&result)["counts"]["main"], 1);
    fixture.assert_surface(&tab, &handle, 1);

    for (operation, field) in [
        ("resources/list", "resources"),
        ("resources/templates/list", "resourceTemplates"),
        ("prompts/list", "prompts"),
    ] {
        let result = fixture
            .state
            .mcp_app_automation
            .renderer_operation(
                &fixture.state,
                json!({"tabId":tab,"mountNonce":"fixture-mount","operation":operation,"arguments":{}}),
            )
            .await
            .unwrap();
        assert_eq!(
            result[field].as_array().unwrap().len(),
            2,
            "both opaque-cursor pages are read"
        );
        fixture.assert_surface(&tab, &handle, 1);
    }
    let second = json!({"label":"native-main-proof","operation_id":"second"});
    fixture.grant("increment_main", second.clone());
    let result = fixture
        .callback(&tab, "increment_main", second)
        .await
        .unwrap();
    assert_eq!(payload(&result)["counts"]["main"], 2);
    assert_eq!(fixture.execution.calls.load(Ordering::SeqCst), 2);
    fixture.assert_surface(&tab, &handle, 1);
    assert_eq!(
        fixture.counts().await,
        json!({"main":2,"sibling":0,"hidden":0})
    );

    // Callback provenance must not suppress a later ordinary model render.
    let rerendered = fixture.render("render_main").await;
    assert_ne!(rerendered, tab);
    let sibling = fixture.render("render_sibling").await;
    assert_ne!(sibling, rerendered);
    assert_ne!(sibling, tab);
    assert_eq!(
        fixture.events().last().unwrap()["payload"]["resource_uri"],
        "ui://callback/sibling.html"
    );
}

#[tokio::test]
async fn callback_visibility_detach_and_replaced_scope_do_not_dispatch_mutations() {
    let fixture = Fixture::new().await;
    let tab = fixture.render("render_main").await;
    let old_handle = fixture.attach(&tab).await;
    let arguments = json!({"operation_id":"never-dispatched"});
    fixture.grant("increment_main", arguments.clone());
    for name in ["increment_sibling", "hidden_probe"] {
        assert!(fixture
            .callback(&tab, name, arguments.clone())
            .await
            .unwrap_err()
            .to_string()
            .contains("mcp_app_tool_not_visible"));
    }
    fixture
        .state
        .mcp_app_automation
        .renderer_operation(
            &fixture.state,
            json!({"tabId":tab,"operation":"detach","mountNonce":"fixture-mount"}),
        )
        .await
        .unwrap();
    assert!(fixture
        .callback(&tab, "increment_main", arguments.clone())
        .await
        .is_err());
    assert!(fixture
        .state
        .mcp_app_automation
        .require_browser(&fixture.state, &old_handle, &fixture.execution.scope)
        .is_err());
    let new_handle = fixture.attach(&tab).await;
    assert_ne!(old_handle, new_handle);

    let mut changed_scope = fixture.execution.scope.clone();
    changed_scope.run_revision += 1;
    changed_scope.generation += 1;
    let changed = execution(&fixture.state, changed_scope, &fixture.server_id);
    let replacement = Arc::new(ExecutionAuthority::LocalRun(changed.clone()));
    fixture
        .state
        .mcp_app_automation
        .register_authority(replacement.clone());
    assert!(fixture
        .callback(&tab, "increment_main", arguments)
        .await
        .unwrap_err()
        .to_string()
        .contains("mcp_app_scope_mismatch"));
    assert!(fixture
        .state
        .mcp_app_automation
        .require_browser(&fixture.state, &new_handle, &fixture.execution.scope)
        .is_err());
    assert_eq!(fixture.execution.calls.load(Ordering::SeqCst), 0);
    assert_eq!(changed.calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        fixture.counts().await,
        json!({"main":0,"sibling":0,"hidden":0})
    );
    assert_eq!(fixture.events().len(), 1);
}
