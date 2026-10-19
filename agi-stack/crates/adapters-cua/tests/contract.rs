//! Private-pipe protocol regressions. The mock never controls the desktop.
use agistack_adapters_cua::{
    CuaCallContext, CuaClient, CuaDispatchSignal, CuaError, CuaToolHost, scope_dispatch_signal,
    tool_effects, tool_names,
};
use agistack_core::ports::ToolHost;
use serde_json::{Value, json};
use std::{
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
    time::Duration,
};

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Helper {
    root: PathBuf,
    script: PathBuf,
}
impl Helper {
    fn new(mode: &str) -> Self {
        let root = std::env::temp_dir().join(format!(
            "memstack-cua-contract-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&root).unwrap();
        let script = root.join("helper.py");
        let prefix = format!(
            "MODE={}\nROOT={}\n",
            json!(mode),
            json!(root.to_string_lossy())
        );
        std::fs::write(&script,prefix.to_owned()+r#"
import sys, json, struct, os, hmac, hashlib, time, zlib
OBS=0
def png(width,height):
    def chunk(kind,data): return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\0'*width*4)*height))+chunk(b'IEND',b'')
with open(os.path.join(ROOT,'pids'),'a') as f: f.write(str(os.getpid())+'\n')
def send(value):
    data=json.dumps(value).encode()
    sys.stdout.buffer.write(struct.pack('<I',len(data))+data)
    sys.stdout.buffer.flush()
while True:
    header=sys.stdin.buffer.read(4)
    if len(header)!=4: break
    request=json.loads(sys.stdin.buffer.read(struct.unpack('<I',header)[0]))
    method=request['method']; params=request['params']; rid=request['id']
    if method=='initialize':
        if MODE=='stale':
            send({'jsonrpc':'2.0','id':0,'error':{'code':-32001,'message':'stale helper','data':{'kind':'incompatible_client_version','server_api_version':'old'}}})
            continue
        proof=hmac.new(params['secret'].encode(),params['nonce'].encode(),hashlib.sha256).hexdigest()
        if MODE=='invalid_proof': proof='é'*32
        result={'server_api_version':params['client_api_version'],'nonce':params['nonce'],'proof':proof}
    elif method=='begin_session':
        artifact_root=os.path.join(ROOT,'artifacts')
        os.makedirs(artifact_root,exist_ok=True)
        result={'session_id':params['session_id'],'artifact_root':artifact_root}
    elif method=='perform_action':
        with open(os.path.join(ROOT,'actions'),'a') as f: f.write('executed\n')
        if MODE=='lost_action': os._exit(0)
        result={'ok':True,'echo':params['action'],'session_id':params['session_id']}
    elif method=='slow':
        with open(os.path.join(ROOT,'slow_started'),'w') as f: f.write('yes')
        time.sleep(2); result={'old':True}
    elif method=='list_apps': result={'apps':[{'id':'com.example.app','display_name':'Example','is_running':True}]}
    elif method=='get_app_state':
        OBS+=1
        result={'app':params['app'],'snapshot_id':'observation-1','window_id':'window-1','text':'[0] Button'}
        if MODE in ('ax_tree','invalid_ax_tree'):
            nodes=[{'element_index':0,'parent_index':None,'role':'frame','name':'Native fixture','description':None,'value':None,'value_redacted':False,'states':['active'],'actions':[],'supports_editable_text':False,'bounds':None},
                   {'element_index':1,'parent_index':0,'role':'password text','name':'Native label','description':None,'value':None,'value_redacted':True,'states':[],'actions':[],'supports_editable_text':True,'bounds':None}]
            if MODE=='invalid_ax_tree':nodes[1]['backend_ref']='private-native-reference'
            result['ax_tree']={'version':1,'source':'at_spi','snapshot_id':result['snapshot_id'],'window_id':result['window_id'],'nodes':nodes,'truncated':False}
        if MODE=='retina':
            result.update(snapshot_id='observation-'+str(OBS),window_bounds={'x':100,'y':200,'width':500 if OBS==1 else 250,'height':400 if OBS==1 else 200})
        if MODE in ('owned_image','escaped_image','symlink_image','retina','icon_image'):
            owned=os.path.join(ROOT,'artifacts','image.png')
            path=os.path.join(ROOT,'outside.png') if MODE=='escaped_image' else owned
            with open(path,'wb') as f: f.write(png(1000,800) if MODE=='retina' else png(1,1))
            if MODE=='symlink_image':
                link=os.path.join(ROOT,'artifacts','link.png');os.symlink(path,link);path=link
            result['icon']='data:image/png;base64,decorative-only'
            result['screenshot']={'url':'file://'+path,'mime_type':'image/png','data_url':'data:image/png;base64,never-in-transcript'}
            if MODE=='icon_image':
                icon=os.path.join(ROOT,'artifacts','icon.png')
                with open(icon,'wb') as f:f.write(png(64,64))
                result['app_icon']={'url':'file://'+icon,'mime_type':'image/png','width':64,'height':64,'kind':'app_icon'}
    elif method=='resolve_app': result={'app':'com.example.app','identity_digest':'fixed-code-identity','display_name':'Example'}
    elif method=='error':
        send({'jsonrpc':'2.0','id':rid,'error':{'code':-32000,'message':'denied','data':{'kind':'permission_required'}}}); continue
    elif method=='notify':
        context={key:params[key] for key in ('user_id','tenant_id','project_id','device_id','conversation_id','run_id','session_id')}
        if MODE=='foreign_status':context['device_id']='foreign-device'
        send({'jsonrpc':'2.0','method':'native_status' if MODE!='unknown_status' else 'arbitrary_event','params':{'context':context,'phase':'paused','updated_at':1,'user_initiated':True,'user_action':'pause'}})
        result={'ok':True}
    else: result={'ok':True,'pid':os.getpid()}
    send({'jsonrpc':'2.0','id':rid,'result':result})
with open(os.path.join(ROOT,'closed'),'a') as f: f.write('released\n')
"#).unwrap();
        Self { root, script }
    }
    fn client(&self, timeout: Duration) -> CuaClient {
        CuaClient::builder()
            .helper_path("python3")
            .helper_args([self.script.as_os_str()])
            .request_timeout(timeout)
            .build()
    }
    fn count(&self, name: &str) -> usize {
        std::fs::read_to_string(self.root.join(name))
            .unwrap_or_default()
            .lines()
            .count()
    }
}
impl Drop for Helper {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}
fn context() -> CuaCallContext {
    CuaCallContext {
        user_id: "user".into(),
        tenant_id: "tenant".into(),
        project_id: "project".into(),
        device_id: "device".into(),
        conversation_id: "conversation".into(),
        run_id: "run".into(),
        session_id: "session".into(),
    }
}

#[tokio::test]
async fn native_dispatch_signal_marks_exact_call_before_write_and_not_preflight() {
    let helper = Helper::new("normal");
    let client = Arc::new(helper.client(Duration::from_secs(2)));
    let host = CuaToolHost::new(client.clone()).with_context(context());
    let signal = CuaDispatchSignal::new("trusted-call");
    scope_dispatch_signal(
        signal.clone(),
        client.request_in_session(&context(), "list_apps", json!({})),
    )
    .await
    .unwrap();
    assert!(
        !signal.was_sent(),
        "initialize, begin_session and untagged probe are not this call"
    );
    assert!(scope_dispatch_signal(signal.clone(), host.call("computer_click", r#"{"app":"com.example.app","snapshot_id":"missing","x":1,"y":2,"_cua_call_id":"trusted-call"}"#)).await.is_err());
    assert!(!signal.was_sent());
    scope_dispatch_signal(
        signal.clone(),
        host.call(
            "computer_get_app_state",
            r#"{"app":"com.example.app","_cua_call_id":"trusted-call"}"#,
        ),
    )
    .await
    .unwrap();
    assert!(signal.was_sent());
    assert_eq!(helper.count("actions"), 0);
    client.shutdown().await;
}

#[tokio::test]
async fn existing_session_cannot_change_owner_or_device() {
    let helper = Helper::new("normal");
    let client = helper.client(Duration::from_secs(2));
    client
        .request_in_session(&context(), "list_apps", json!({}))
        .await
        .unwrap();
    let mut other = context();
    other.device_id = "other-device".into();
    assert!(
        client
            .request_in_session(&other, "perform_action", json!({"action":{"kind":"click"}}))
            .await
            .unwrap_err()
            .to_string()
            .contains("session_owner_mismatch")
    );
    assert_eq!(helper.count("actions"), 0);
    client.shutdown().await;
}

#[tokio::test]
async fn shutdown_closes_owned_pipe_and_waits_for_native_cleanup() {
    let helper = Helper::new("normal");
    let client = helper.client(Duration::from_secs(2));
    client.request("list_apps", json!({})).await.unwrap();
    client.shutdown().await;
    assert_eq!(helper.count("closed"), 1);
}

#[tokio::test]
async fn owned_screenshot_is_typed_media_and_base64_never_enters_text() {
    let helper = Helper::new("owned_image");
    let client = Arc::new(helper.client(Duration::from_secs(2)));
    let host = CuaToolHost::new(client.clone()).with_context(context());
    let result = host
        .call_with_content("computer_get_app_state", r#"{"app":"com.example.app"}"#)
        .await
        .unwrap();
    assert_eq!(result.media.len(), 1);
    assert_eq!(result.media[0].mime_type, "image/png");
    assert!(!result.output_json.contains("base64"));
    assert!(
        PathBuf::from(&result.media[0].artifact_path)
            .starts_with(helper.root.join("artifacts").canonicalize().unwrap())
    );
    client.shutdown().await;
}

#[tokio::test]
async fn escaped_and_symlink_screenshots_fail_closed() {
    for mode in ["escaped_image", "symlink_image"] {
        let helper = Helper::new(mode);
        let client = Arc::new(helper.client(Duration::from_secs(2)));
        let host = CuaToolHost::new(client.clone()).with_context(context());
        assert!(
            host.call_with_content("computer_get_app_state", r#"{"app":"com.example.app"}"#)
                .await
                .unwrap_err()
                .to_string()
                .contains("artifact_not_owned")
        );
        client.shutdown().await;
    }
}

#[tokio::test]
async fn scoped_handshake_and_action_round_trip() {
    let helper = Helper::new("normal");
    let client = Arc::new(helper.client(Duration::from_secs(2)));
    let host = CuaToolHost::new(client.clone()).with_context(context());
    for tool in host.list_tools() {
        assert!(host.tool_definition(&tool).unwrap().input_schema.is_some());
        assert!(tool_effects().contains_key(tool.as_str()));
    }
    assert_eq!(tool_names().len(), 26);
    let apps: Value =
        serde_json::from_str(&host.call("computer_list_apps", "{}").await.unwrap()).unwrap();
    assert_eq!(apps.pointer("/apps/0/id"), Some(&json!("com.example.app")));
    for _ in 0..2 {
        let value = host
            .call("computer_get_app_state", r#"{"app":"com.example.app"}"#)
            .await
            .unwrap();
        assert!(value.contains("observation-1"));
    }
    let value = host
        .call(
            "computer_click",
            r#"{"app":"com.example.app","snapshot_id":"observation-1","element_index":0}"#,
        )
        .await
        .unwrap();
    assert!(value.contains("click"));
    assert_eq!(helper.count("actions"), 1);
    client.shutdown().await;
}
#[tokio::test]
async fn lost_action_response_is_unknown_and_never_replayed() {
    let helper = Helper::new("lost_action");
    let client = helper.client(Duration::from_secs(2));
    let signal = CuaDispatchSignal::new("trusted-action");
    let result = scope_dispatch_signal(
        signal.clone(),
        client.request_in_session(
            &context(),
            "perform_action",
            json!({"app":"test","action":{"kind":"click"},"request_id":"trusted-action"}),
        ),
    )
    .await;
    assert!(matches!(result, Err(CuaError::OutcomeUnknown(_))));
    assert!(signal.was_sent());
    assert_eq!(helper.count("actions"), 1);
    assert_eq!(helper.count("pids"), 1);
    client
        .request_in_session(&context(), "list_apps", json!({}))
        .await
        .unwrap();
    assert_eq!(helper.count("actions"), 1);
    assert_eq!(helper.count("pids"), 2);
    client.shutdown().await;
}
#[tokio::test]
async fn timeout_discards_old_response_and_next_request_reconnects() {
    let helper = Helper::new("normal");
    let client = helper.client(Duration::from_millis(100));
    assert!(client.request("slow", json!({})).await.is_err());
    let value = client.request("list_apps", json!({})).await.unwrap();
    assert!(value.get("apps").is_some());
    assert_eq!(helper.count("pids"), 2);
    client.shutdown().await;
}
#[tokio::test]
async fn cancellation_discards_partial_exchange() {
    let helper = Helper::new("normal");
    let client = Arc::new(helper.client(Duration::from_secs(3)));
    let task = {
        let client = client.clone();
        tokio::spawn(async move { client.request("slow", json!({})).await })
    };
    for _ in 0..100 {
        if helper.root.join("slow_started").exists() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert!(helper.root.join("slow_started").exists());
    task.abort();
    let _ = task.await;
    assert!(
        client
            .request("list_apps", json!({}))
            .await
            .unwrap()
            .get("apps")
            .is_some()
    );
    assert_eq!(helper.count("pids"), 2);
    client.shutdown().await;
}
#[tokio::test]
async fn parallel_bootstrap_starts_exactly_one_owned_helper() {
    let helper = Helper::new("normal");
    let client = Arc::new(helper.client(Duration::from_secs(2)));
    let mut tasks = Vec::new();
    for _ in 0..8 {
        let client = client.clone();
        tasks.push(tokio::spawn(async move {
            client.request("list_apps", json!({})).await
        }));
    }
    for task in tasks {
        assert!(task.await.unwrap().unwrap().get("apps").is_some());
    }
    assert_eq!(helper.count("pids"), 1);
    client.shutdown().await;
}
#[tokio::test]
async fn stale_helper_and_invalid_proof_have_explicit_errors() {
    let helper = Helper::new("stale");
    let client = helper.client(Duration::from_secs(2));
    assert!(matches!(
        client.request("list_apps", json!({})).await,
        Err(CuaError::IncompatibleClientVersion { .. })
    ));
    client.shutdown().await;
    let helper = Helper::new("invalid_proof");
    let client = helper.client(Duration::from_secs(2));
    assert!(matches!(
        client.request("list_apps", json!({})).await,
        Err(CuaError::InvalidResponse(_))
    ));
    client.shutdown().await;
}
#[tokio::test]
async fn invalid_arguments_fail_before_spawning_or_mutating() {
    let helper = Helper::new("normal");
    let client = Arc::new(helper.client(Duration::from_secs(2)));
    let host = CuaToolHost::new(client.clone()).with_context(context());
    for input in [
        json!({"app":"test","snapshot_id":"s"}),
        json!({"app":"test","snapshot_id":"s","x":1}),
        json!({"app":"test","snapshot_id":"s","element_index":-1}),
        json!({"app":"test","snapshot_id":"s","x":1,"y":2,"mouse_button":"bogus"}),
    ] {
        assert!(
            host.call("computer_click", &input.to_string())
                .await
                .is_err()
        );
    }
    assert!(
        host.call(
            "computer_scroll",
            &json!({"app":"test","snapshot_id":"s","x":1,"y":2,"pages":1e100}).to_string()
        )
        .await
        .is_err()
    );
    assert!(
        host.call("computer_get_app_state", r#"{"app":"com.apple.passwords"}"#)
            .await
            .unwrap_err()
            .to_string()
            .contains("target_forbidden")
    );
    assert_eq!(helper.count("pids"), 0);
    assert_eq!(helper.count("actions"), 0);
    client.shutdown().await;
}

#[tokio::test]
async fn screenshot_coordinates_survive_rebuilt_hosts_and_resized_snapshots() {
    let helper = Helper::new("retina");
    let client = Arc::new(helper.client(Duration::from_secs(2)));
    let first = CuaToolHost::new(client.clone()).with_context(context());
    let state: Value = serde_json::from_str(
        &first
            .call("computer_get_app_state", r#"{"app":"com.example.app"}"#)
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(state["coordinate_spaces"]["screenshot"]["width"], 1000);
    let fresh = CuaToolHost::new(client.clone()).with_context(context());
    let input = json!({"app":"com.example.app","window_id":"window-1","snapshot_id":state["snapshot_id"],"x":400,"y":200,"coordinate_space":"screenshot"});
    for _ in 0..2 {
        fresh
            .validate_observed_action("computer_click", &input)
            .await
            .unwrap();
    }
    assert_eq!(helper.count("actions"), 0);
    let result: Value = serde_json::from_str(
        &fresh
            .call("computer_click", &input.to_string())
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(result["echo"]["x"], 200.0);
    assert_eq!(result["echo"]["y"], 100.0);
    assert!(result["echo"].get("coordinate_space").is_none());
    assert!(
        fresh
            .call("computer_click", &input.to_string())
            .await
            .unwrap_err()
            .to_string()
            .contains("snapshot_missing")
    );
    let error = fresh
        .validate_observed_action("computer_click", &input)
        .await
        .unwrap_err()
        .to_string();
    assert!(error.contains("computer_get_app_state"));
    let resized: Value = serde_json::from_str(
        &fresh
            .call("computer_get_app_state", r#"{"app":"com.example.app"}"#)
            .await
            .unwrap(),
    )
    .unwrap();
    assert!(
        fresh
            .call("computer_click", &input.to_string())
            .await
            .unwrap_err()
            .to_string()
            .contains("snapshot_stale")
    );
    let input = json!({"app":"com.example.app","snapshot_id":resized["snapshot_id"],"from_x":400,"from_y":200,"to_x":800,"to_y":600,"coordinate_space":"screenshot"});
    let result: Value = serde_json::from_str(
        &fresh
            .call("computer_drag", &input.to_string())
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(result["echo"]["from_x"], 100.0);
    assert_eq!(result["echo"]["to_y"], 150.0);
    assert_eq!(helper.count("actions"), 2);
    client.shutdown().await;
}
#[tokio::test]
async fn coordinate_window_scope_and_stop_invalidate_before_native_input() {
    let helper = Helper::new("retina");
    let client = Arc::new(helper.client(Duration::from_secs(2)));
    let host = CuaToolHost::new(client.clone()).with_context(context());
    let state: Value = serde_json::from_str(
        &host
            .call("computer_get_app_state", r#"{"app":"com.example.app"}"#)
            .await
            .unwrap(),
    )
    .unwrap();
    let mut input = json!({"app":"com.example.app","snapshot_id":state["snapshot_id"],"window_id":"other-window","x":1,"y":2});
    assert!(
        host.call("computer_click", &input.to_string())
            .await
            .unwrap_err()
            .to_string()
            .contains("snapshot_window_mismatch")
    );
    let mut other = context();
    other.device_id = "other-device".into();
    input["window_id"] = json!("window-1");
    assert!(
        CuaToolHost::new(client.clone())
            .with_context(other)
            .call("computer_click", &input.to_string())
            .await
            .unwrap_err()
            .to_string()
            .contains("snapshot_scope_mismatch")
    );
    client.stop_session(&context().session_id).await.unwrap();
    assert!(
        host.call("computer_click", &input.to_string())
            .await
            .unwrap_err()
            .to_string()
            .contains("snapshot_missing")
    );
    assert_eq!(helper.count("actions"), 0);
    client.shutdown().await;
}

#[tokio::test]
async fn native_notifications_require_exact_initialized_owner_and_known_method() {
    for mode in ["valid_status", "foreign_status", "unknown_status"] {
        let helper = Helper::new(mode);
        let client = helper.client(Duration::from_secs(3));
        let mut receiver = client.subscribe_native_status();
        let context = context();
        let result = client
            .request_in_session(&context, "notify", json!({}))
            .await;
        if mode == "valid_status" {
            result.unwrap();
            let event = receiver.recv().await.unwrap();
            assert_eq!(event.context, context);
            assert_eq!(event.user_action.as_deref(), Some("pause"));
            assert_eq!(event.presentation()["can_resume"], false);
        } else {
            assert!(
                result.is_err(),
                "foreign or unknown notification must close the private channel"
            );
            assert!(receiver.try_recv().is_err());
        }
        client.shutdown().await;
    }
}

#[tokio::test]
async fn decorative_application_icon_is_owned_but_not_model_image_media() {
    let helper = Helper::new("icon_image");
    let client = Arc::new(helper.client(Duration::from_secs(3)));
    let host = CuaToolHost::new(client.clone()).with_context(context());
    let result = host
        .call_with_content("computer_get_app_state", r#"{"app":"fixture"}"#)
        .await
        .unwrap();
    let output: Value = serde_json::from_str(&result.output_json).unwrap();
    assert_eq!(output["app_icon"]["kind"], "app_icon");
    assert_eq!(result.media.len(), 1, "only the screenshot is model media");
    assert!(!result.output_json.contains("base64"));
    client.shutdown().await;
}

#[tokio::test]
async fn native_public_ax_tree_survives_scoped_tool_serialization_without_private_references() {
    let helper = Helper::new("ax_tree");
    let client = Arc::new(helper.client(Duration::from_secs(2)));
    let host = CuaToolHost::new(client.clone()).with_context(context());
    let result = host
        .call_with_content("computer_get_app_state", r#"{"app":"com.example.app"}"#)
        .await
        .unwrap();
    let value: Value = serde_json::from_str(&result.output_json).unwrap();
    let tree: agistack_adapters_cua::CuaAxTree =
        serde_json::from_value(value["ax_tree"].clone()).unwrap();
    assert_eq!(tree.snapshot_id, value["snapshot_id"].as_str().unwrap());
    assert_eq!(tree.window_id, value["window_id"].as_str().unwrap());
    assert_eq!(tree.nodes[1].parent_index, Some(0));
    assert!(tree.nodes[1].value_redacted);
    assert!(tree.nodes[1].value.is_none());
    assert!(result.media.is_empty());
    assert!(!result.output_json.contains("backend_ref"));
    client.shutdown().await;
}
#[tokio::test]
async fn native_public_ax_tree_private_fields_are_rejected_before_observation_cache() {
    let helper = Helper::new("invalid_ax_tree");
    let client = Arc::new(helper.client(Duration::from_secs(2)));
    let host = CuaToolHost::new(client.clone()).with_context(context());
    assert!(
        host.call_with_content("computer_get_app_state", r#"{"app":"com.example.app"}"#)
            .await
            .unwrap_err()
            .to_string()
            .contains("cua_ax_tree_invalid")
    );
    assert!(
        host.call(
            "computer_click",
            r#"{"app":"com.example.app","snapshot_id":"observation-1","x":1,"y":1}"#
        )
        .await
        .is_err()
    );
    assert_eq!(helper.count("actions"), 0);
    client.shutdown().await;
}
