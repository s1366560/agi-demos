//! Authenticated private IPC fixtures; these tests never request operating-system access.
use super::*;
use std::time::Duration;

pub(super) struct Helper {
    pub(super) root: PathBuf,
    pub(super) client: Arc<CuaClient>,
}
impl Helper {
    pub(super) fn new(fail: bool) -> Self {
        let root = std::env::temp_dir().join(format!("memstack-cua-permission-{}", Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        let script = root.join("mock.py");
        let code = format!(
            "ROOT={}\nFAIL={}\n",
            json!(root.to_string_lossy()),
            if fail { "True" } else { "False" }
        ) + r#"
import sys,json,struct,hmac,hashlib,os,time
def send(value):
    raw=json.dumps(value).encode();sys.stdout.buffer.write(struct.pack('<I',len(raw))+raw);sys.stdout.buffer.flush()
while True:
    header=sys.stdin.buffer.read(4)
    if len(header)!=4: break
    request=json.loads(sys.stdin.buffer.read(struct.unpack('<I',header)[0]));method=request['method'];params=request['params'];rid=request['id']
    if method=='initialize':
        result={'server_api_version':params['client_api_version'],'nonce':params['nonce'],'proof':hmac.new(params['secret'].encode(),params['nonce'].encode(),hashlib.sha256).hexdigest()}
    else:
        with open(os.path.join(ROOT,'requests'),'a') as file:file.write(json.dumps({'method':method,'params':params})+'\n')
        audio_path=os.path.join(ROOT,'audio_receipts.json')
        if method in ('pause_session','stop_session','end_session') and os.path.exists(audio_path):
            receipts=json.load(open(audio_path))
            for item in receipts:
                if item['status']=='recording':
                    item['status']='pending_export';item['ended_at']='2026-10-19T00:00:10Z';item['elapsed_ms']=10000
                    item['end_reason']='user_paused' if method=='pause_session' else params.get('end_reason','session_ended')
            with open(audio_path,'w') as file:json.dump(receipts,file)
        hold=os.path.join(ROOT,'hold_method')
        if os.path.exists(hold) and open(hold).read()==method:
            with open(os.path.join(ROOT,'entered_method'),'w') as file:file.write(method)
            while not os.path.exists(os.path.join(ROOT,'release_method')):time.sleep(0.01)
            os.remove(hold);os.remove(os.path.join(ROOT,'release_method'))
        error_kind=os.path.join(ROOT,'error_kind')
        if method=='begin_session' and params['input_mode']=='background' and os.path.exists(os.path.join(ROOT,'reject_background')):
            send({'jsonrpc':'2.0','id':rid,'error':{'code':-32000,'message':'fixture background input unavailable','data':{'kind':'background_input_unavailable'}}});continue
        if method=='get_app_state' and os.path.exists(error_kind):
            send({'jsonrpc':'2.0','id':rid,'error':{'code':-32000,'message':'fixture native failure','data':{'kind':open(error_kind).read()}}});continue
        if method=='permission_request' and FAIL:
            send({'jsonrpc':'2.0','id':rid,'error':{'code':-32000,'message':'fixture denial','data':{'kind':'permission_denied'}}});continue
        locked_use_error=os.path.join(ROOT,'locked_use_error')
        if method in ('locked_use_install','locked_use_uninstall') and os.path.exists(locked_use_error):
            failure=json.load(open(locked_use_error))
            send({'jsonrpc':'2.0','id':rid,'error':{'code':-32000,'message':failure['message'],'data':{'kind':failure['kind']}}});continue
        if method=='begin_session':result={'session_id':params['session_id'],'artifact_root':ROOT,'input_mode':params['input_mode'],'input_generation':'fixture-generation'}
        elif method=='capabilities':
            support_path=os.path.join(ROOT,'input_support.json')
            result={'input_support':json.load(open(support_path)) if os.path.exists(support_path) else {'background':{'supported':True,'reason':None},'foreground':{'supported':True,'reason':None}}}
        elif method=='permissions_status':result={'accessibility':{'state':'denied'},'locked_use':{'state':'unverified'}}
        elif method in ('locked_use_probe','locked_use_install','locked_use_uninstall'):
            path=os.path.join(ROOT,'locked_use_installed')
            if method=='locked_use_install':open(path,'w').write('installed')
            if method=='locked_use_uninstall' and os.path.exists(path):os.remove(path)
            result={'installed':os.path.exists(path),'state':'available' if os.path.exists(path) else 'permission_required','enabled':False,'phase':'idle'}
        elif method in ('locked_use_enable','locked_use_renew','locked_use_disable'):
            result={'enabled':method!='locked_use_disable','generation':params.get('generation'),'phase':'idle' if method=='locked_use_disable' else 'guarded'}
            reply_path=os.path.join(ROOT,'locked_use_disable_result')
            if method=='locked_use_disable' and os.path.exists(reply_path):result=json.load(open(reply_path))
        elif method=='get_app_state':
            snapshot_path=os.path.join(ROOT,'snapshot_id')
            result={'app':'Fixture','snapshot_id':open(snapshot_path).read() if os.path.exists(snapshot_path) else 'snapshot-round1','window_id':'window-1','window_bounds':{'x':0,'y':0,'width':300,'height':200},'text':'[0] Window','screenshot':None,'input_mode':params['input_mode'],'input_generation':params['input_generation']}
        elif method=='resolve_app':result={'app':'fixture-app','display_name':'Fixture','identity_digest':'fixture-identity','process_id':10}
        elif method in ('audio_start','audio_stop','audio_status','audio_ack'):
            path=os.path.join(ROOT,'audio_receipts.json')
            receipts=json.load(open(path)) if os.path.exists(path) else []
            if method=='audio_stop' and params.get('recording_id') and not any(item['recording_id']==params['recording_id'] for item in receipts):
                send({'jsonrpc':'2.0','id':rid,'error':{'code':-32000,'message':'fixture recording missing','data':{'kind':'recording_not_found'}}});continue
            if method=='audio_stop':
                for item in receipts:
                    if item['status']=='recording' and params.get('recording_id',item['recording_id'])==item['recording_id']:
                        item['status']='pending_export';item['ended_at']='2026-10-19T00:00:10Z';item['elapsed_ms']=10000
                        item['end_reason']=params.get('end_reason','user_stopped')
            if method=='audio_ack':
                for item in receipts:
                    if item['recording_id']==params['recording_id']:item['status']='saved';item['artifacts']=[]
            if os.path.exists(path):
                with open(path,'w') as file:json.dump(receipts,file)
            result={'recordings':[item for item in receipts if params.get('recording_id',item['recording_id'])==item['recording_id']]}
        elif method=='fixture_native_status':
            send({'jsonrpc':'2.0','method':'native_status','params':params});result={'ok':True}
        elif method=='stop_session' and os.path.exists(os.path.join(ROOT,'emit_stop_status')):
            send({'jsonrpc':'2.0','method':'native_status','params':{'context':{key:params[key] for key in ('user_id','tenant_id','project_id','device_id','conversation_id','run_id','session_id','input_mode')},'phase':'stopped','updated_at':time.time(),'user_initiated':False}});result={'ok':True}
        else:result={'ok':True}
    send({'jsonrpc':'2.0','id':rid,'result':result})
with open(os.path.join(ROOT,'closed'),'a') as file:file.write('released\n')
"#;
        std::fs::write(&script, code).unwrap();
        let client = Arc::new(
            CuaClient::builder()
                .helper_path("python3")
                .helper_args([script.as_os_str()])
                .request_timeout(Duration::from_secs(3))
                .build(),
        );
        Self { root, client }
    }
    pub(super) fn requests(&self) -> Vec<Value> {
        std::fs::read_to_string(self.root.join("requests"))
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect()
    }
}

#[tokio::test]
async fn rebuilt_host_preserves_scoped_observation_across_rounds_and_end_invalidates_it() {
    let helper = Helper::new(false);
    let context = CuaCallContext {
        user_id: "user".into(),
        tenant_id: "tenant".into(),
        project_id: "project".into(),
        device_id: "device".into(),
        conversation_id: "conversation".into(),
        run_id: "run".into(),
        session_id: "reused-native-session".into(),
        input_mode: agistack_adapters_cua::CuaInputMode::default(),
    };
    let original = CuaToolHost::new(helper.client.clone()).with_context(context.clone());
    original
        .call_with_content(
            "computer_get_app_state",
            r#"{"app":"pid:10","window_id":"window-1"}"#,
        )
        .await
        .unwrap();
    drop(original);
    let rebuilt = CuaToolHost::new(helper.client.clone()).with_context(context.clone());
    let input = r#"{"app":"pid:10","snapshot_id":"snapshot-round1","x":10,"y":20}"#;
    rebuilt
        .call_with_content("computer_click", input)
        .await
        .unwrap();
    let requests = helper.requests();
    assert_eq!(
        requests
            .iter()
            .filter(|request| request["method"] == "begin_session")
            .count(),
        1
    );
    let action = requests
        .iter()
        .find(|request| request["method"] == "perform_action")
        .unwrap();
    assert_eq!(action["params"]["session_id"], context.session_id);
    assert_eq!(action["params"]["window_id"], "window-1");
    let mut foreign = context.clone();
    foreign.run_id = "different-run".into();
    foreign.session_id = "different-session".into();
    assert!(CuaToolHost::new(helper.client.clone())
        .with_context(foreign)
        .call("computer_click", input)
        .await
        .is_err());
    helper
        .client
        .stop_session(&context.session_id)
        .await
        .unwrap();
    helper
        .client
        .end_session(&context.session_id)
        .await
        .unwrap();
    assert!(rebuilt.call("computer_click", input).await.is_err());
    helper.client.shutdown().await;
}
impl Drop for Helper {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

#[tokio::test]
async fn permission_requests_are_owned_short_sessions_and_cleanup_on_denial() {
    for denied in [false, true] {
        let helper = Helper::new(denied);
        let state = crate::local_runtime::tests::test_state("cua-permission-fixture");
        let owner = super::tests::owner(&state);
        assert!(state.computer_use.client.set(helper.client.clone()).is_ok());
        let request: api::ManagementRequest = serde_json::from_value(
            json!({"action":"permission_request","capability":"accessibility"}),
        )
        .unwrap();
        let result = api::operation(&state, &owner, request).await;
        assert_eq!(result.is_err(), denied);
        let requests = helper.requests();
        let permission = requests
            .iter()
            .find(|request| request["method"] == "permission_request")
            .unwrap();
        let context = &permission["params"];
        for (key, expected) in [
            ("user_id", owner.user_id.as_str()),
            ("tenant_id", owner.tenant_id.as_str()),
            ("project_id", owner.project_id.as_str()),
            ("device_id", owner.device_id.as_str()),
        ] {
            assert_eq!(context[key], expected);
        }
        assert!(context["session_id"]
            .as_str()
            .unwrap()
            .starts_with("cua-settings-"));
        assert!(requests
            .iter()
            .any(|request| request["method"] == "stop_session"
                && request["params"]["session_id"] == context["session_id"]));
        assert!(requests
            .iter()
            .any(|request| request["method"] == "end_session"
                && request["params"]["session_id"] == context["session_id"]));
        assert!(helper
            .client
            .session_artifact_root(context["session_id"].as_str().unwrap())
            .await
            .is_none());
        assert!(helper.root.join("closed").is_file());
        assert!(state.computer_use.sessions_for(&owner).is_empty());
    }
}

#[test]
fn child_session_grants_cannot_authorize_parent_or_sibling_execution() {
    let state = crate::local_runtime::tests::test_state("cua-child-grants");
    let owner = super::tests::owner(&state);
    let parent = Arc::new(Session {
        resources: Default::default(),
        dispatch: tokio::sync::Mutex::new(()),
        owner: owner.clone(),
        revision: 0,
        stopped: AtomicBool::new(false),
        paused: AtomicBool::new(false),
        user_control: Default::default(),
        presentation: Mutex::new(json!({"phase":"idle","can_resume":false})),
        child: None,
        cloud: None,
        context: CuaCallContext {
            user_id: owner.user_id.clone(),
            tenant_id: owner.tenant_id.clone(),
            project_id: owner.project_id.clone(),
            device_id: owner.device_id.clone(),
            conversation_id: "conversation".into(),
            run_id: "run".into(),
            session_id: "parent".into(),
            input_mode: agistack_adapters_cua::CuaInputMode::default(),
        },
    });
    state
        .computer_use
        .sessions
        .lock()
        .unwrap()
        .insert("parent".into(), parent.clone());
    let child = super::super::local_plugin_tool_host_v2::identity::ChildIdentityV2 {
        execution_id: "child-a".into(),
        subagent_id: "subagent".into(),
        run_id: "run".into(),
        revision: 1,
    };
    let first = state
        .computer_use
        .child_session(&parent, child.clone())
        .unwrap();
    let second = state
        .computer_use
        .child_session(
            &parent,
            super::super::local_plugin_tool_host_v2::identity::ChildIdentityV2 {
                execution_id: "child-b".into(),
                ..child.clone()
            },
        )
        .unwrap();
    assert_eq!(
        state
            .computer_use
            .child_session(&parent, child)
            .unwrap()
            .context
            .session_id,
        first.context.session_id
    );
    assert_ne!(first.context.session_id, second.context.session_id);
    let db = state.session_store.connection().unwrap();
    store::update(&db, &owner, 0, "enable", None).unwrap();
    store::grant(
        &db,
        &owner,
        store::Grant {
            id: String::new(),
            app: "app".into(),
            identity_digest: "identity".into(),
            capability: "observe".into(),
            scope: store::GrantScope::Session,
            session_id: Some(first.context.session_id.clone()),
            request_id: Some("request".into()),
        },
    )
    .unwrap();
    assert!(store::authorize(
        &db,
        &owner,
        "app",
        "identity",
        "observe",
        &first.context.session_id,
        "request"
    )
    .unwrap());
    assert!(!store::authorize(
        &db,
        &owner,
        "app",
        "identity",
        "observe",
        &second.context.session_id,
        "request"
    )
    .unwrap());
    assert!(!store::authorize(
        &db,
        &owner,
        "app",
        "identity",
        "observe",
        &parent.context.session_id,
        "request"
    )
    .unwrap());
    parent.stopped.store(true, Ordering::SeqCst);
    assert!(state
        .computer_use
        .child_session(
            &parent,
            super::super::local_plugin_tool_host_v2::identity::ChildIdentityV2 {
                execution_id: "new-child".into(),
                subagent_id: "subagent".into(),
                run_id: "run".into(),
                revision: 1
            }
        )
        .is_err());
}

#[tokio::test]
async fn selecting_input_mode_revokes_bound_sessions_and_persists_only_this_owner() {
    let state = crate::local_runtime::tests::test_state("cua-input-mode");
    let owner = super::tests::owner(&state);
    let helper = Helper::new(false);
    state
        .computer_use
        .client
        .set(helper.client.clone())
        .ok()
        .unwrap();
    {
        let db = state.session_store.connection().unwrap();
        store::update(&db, &owner, 0, "enable", None).unwrap();
    }
    let context = CuaCallContext {
        user_id: owner.user_id.clone(),
        tenant_id: owner.tenant_id.clone(),
        project_id: owner.project_id.clone(),
        device_id: owner.device_id.clone(),
        conversation_id: "conversation".into(),
        run_id: "run".into(),
        session_id: "mode-session".into(),
        input_mode: agistack_adapters_cua::CuaInputMode::Background,
    };
    helper
        .client
        .request_in_session(&context, "list_apps", json!({}))
        .await
        .unwrap();
    let session = Arc::new(Session {
        resources: Default::default(),
        dispatch: tokio::sync::Mutex::new(()),
        owner: owner.clone(),
        context,
        revision: 1,
        stopped: AtomicBool::new(false),
        paused: AtomicBool::new(false),
        user_control: Default::default(),
        presentation: Mutex::new(json!({"phase":"idle"})),
        child: None,
        cloud: None,
    });
    state
        .computer_use
        .sessions
        .lock()
        .unwrap()
        .insert("mode-session".into(), session.clone());
    let input = serde_json::from_value(
        json!({"action":"set_input_mode","input_mode":"foreground","expected_revision":1}),
    )
    .unwrap();
    let snapshot = api::operation(&state, &owner, input).await.unwrap();
    assert_eq!(snapshot["instance"]["input_mode"], "foreground");
    assert_eq!(snapshot["instance"]["revision"], 2);
    assert!(session.stopped.load(Ordering::SeqCst));
    assert!(snapshot["sessions"].as_array().unwrap().is_empty());
    for method in ["stop_session", "end_session"] {
        assert!(helper
            .requests()
            .iter()
            .any(|request| request["method"] == method
                && request["params"]["input_generation"] == "fixture-generation"));
    }
    let mut other = owner.clone();
    other.project_id = "other-project".into();
    assert_eq!(
        api::snapshot(&state, &other).unwrap()["instance"]["input_mode"],
        "background"
    );
    let stale = serde_json::from_value(
        json!({"action":"set_input_mode","input_mode":"background","expected_revision":1}),
    )
    .unwrap();
    assert_eq!(
        api::operation(&state, &owner, stale).await.unwrap_err(),
        "cua_instance_revision_conflict"
    );
}

#[tokio::test]
async fn enabled_cold_status_probes_modes_without_admitting_a_session() {
    let helper = Helper::new(false);
    let state = crate::local_runtime::tests::test_state("cua-cold-capabilities");
    let owner = super::tests::owner(&state);
    assert!(state.computer_use.client.set(helper.client.clone()).is_ok());
    std::fs::write(
        helper.root.join("input_support.json"),
        json!({
            "background":{"supported":false,"reason":"background_input_unsupported"},
            "foreground":{"supported":true,"reason":null}
        })
        .to_string(),
    )
    .unwrap();
    {
        let db = state.session_store.connection().unwrap();
        store::update(&db, &owner, 0, "enable", None).unwrap();
    }
    let status = api::operation(
        &state,
        &owner,
        serde_json::from_value(json!({"action":"status"})).unwrap(),
    )
    .await
    .unwrap();
    assert_eq!(status["input_support"]["foreground"]["supported"], true);
    assert_eq!(status["input_support"]["background"]["supported"], false);
    assert_eq!(helper.requests().len(), 1);
    assert_eq!(helper.requests()[0]["method"], "capabilities");
    assert!(!helper.root.join("closed").exists());
    let selected = api::operation(
        &state,
        &owner,
        serde_json::from_value(
            json!({"action":"set_input_mode","input_mode":"foreground","expected_revision":1}),
        )
        .unwrap(),
    )
    .await
    .unwrap();
    assert_eq!(selected["instance"]["input_mode"], "foreground");
    helper.client.shutdown().await;
}

#[tokio::test]
async fn disabled_status_does_not_start_a_helper() {
    let helper = Helper::new(false);
    let state = crate::local_runtime::tests::test_state("cua-disabled-capabilities");
    let owner = super::tests::owner(&state);
    assert!(state.computer_use.client.set(helper.client.clone()).is_ok());
    api::operation(
        &state,
        &owner,
        serde_json::from_value(json!({"action":"status"})).unwrap(),
    )
    .await
    .unwrap();
    assert!(!helper.root.join("requests").exists());
    assert!(!state
        .computer_use
        .input_support_probe
        .load(Ordering::SeqCst));
}

#[tokio::test]
async fn slow_capability_probe_has_one_settings_budget_and_keeps_helper_alive() {
    let helper = Helper::new(false);
    let state = crate::local_runtime::tests::test_state("cua-slow-capabilities");
    let owner = super::tests::owner(&state);
    assert!(state.computer_use.client.set(helper.client.clone()).is_ok());
    {
        let db = state.session_store.connection().unwrap();
        store::update(&db, &owner, 0, "enable", None).unwrap();
    }
    std::fs::write(helper.root.join("hold_method"), "capabilities").unwrap();
    tokio::time::timeout(
        Duration::from_millis(2500),
        input::refresh_status(&state, &owner),
    )
    .await
    .unwrap()
    .unwrap();
    assert!(state
        .computer_use
        .input_support_probe
        .load(Ordering::SeqCst));
    tokio::time::timeout(
        Duration::from_millis(200),
        input::refresh_status(&state, &owner),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(helper.requests().len(), 1);
    assert!(!helper.root.join("closed").exists());
    std::fs::write(helper.root.join("release_method"), "yes").unwrap();
    tokio::time::timeout(Duration::from_millis(500), async {
        while state
            .computer_use
            .input_support_probe
            .load(Ordering::SeqCst)
        {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(input::support(&state)["foreground"]["supported"], true);
    assert!(!helper.root.join("closed").exists());
    helper.client.shutdown().await;
}

#[tokio::test]
async fn permission_settings_session_uses_only_its_owners_selected_input_mode() {
    let helper = Helper::new(false);
    let state = crate::local_runtime::tests::test_state("cua-settings-input-mode");
    let owner = super::tests::owner(&state);
    assert!(state.computer_use.client.set(helper.client.clone()).is_ok());
    std::fs::write(helper.root.join("reject_background"), "yes").unwrap();
    {
        let db = state.session_store.connection().unwrap();
        store::set_input_mode(
            &db,
            &owner,
            0,
            agistack_adapters_cua::CuaInputMode::Foreground,
        )
        .unwrap();
    }
    let request = || {
        serde_json::from_value(json!({"action":"permission_request","capability":"accessibility"}))
            .unwrap()
    };
    api::operation(&state, &owner, request()).await.unwrap();
    let first = helper.requests();
    for method in [
        "begin_session",
        "permission_request",
        "stop_session",
        "end_session",
    ] {
        let sent = first
            .iter()
            .find(|request| request["method"] == method)
            .unwrap();
        assert_eq!(sent["params"]["input_mode"], "foreground");
        assert_eq!(sent["params"]["project_id"], owner.project_id);
    }
    let mut other = owner.clone();
    other.project_id = "another-project".into();
    assert_eq!(
        api::operation(&state, &other, request()).await.unwrap_err(),
        "cua_permission_request_unavailable"
    );
    let requests = helper.requests();
    let other_begin = requests
        .iter()
        .find(|request| {
            request["method"] == "begin_session"
                && request["params"]["project_id"] == other.project_id
        })
        .unwrap();
    assert_eq!(other_begin["params"]["input_mode"], "background");
    assert_eq!(
        requests
            .iter()
            .filter(|request| request["method"] == "permission_request")
            .count(),
        1
    );
    helper.client.shutdown().await;
}

#[tokio::test]
async fn runtime_shutdown_releases_native_input_before_waiting_for_other_services() {
    let helper = Helper::new(false);
    let state = crate::local_runtime::tests::test_state("cua-shutdown-priority");
    let owner = super::tests::owner(&state);
    assert!(state.computer_use.client.set(helper.client.clone()).is_ok());
    let context = CuaCallContext {
        user_id: owner.user_id.clone(),
        tenant_id: owner.tenant_id.clone(),
        project_id: owner.project_id.clone(),
        device_id: owner.device_id.clone(),
        conversation_id: "conversation".into(),
        run_id: "run".into(),
        session_id: "shutdown-priority".into(),
        input_mode: agistack_adapters_cua::CuaInputMode::Background,
    };
    helper
        .client
        .request_in_session(&context, "list_apps", json!({}))
        .await
        .unwrap();
    let worker_release = Arc::new(tokio::sync::Notify::new());
    *state.automation_worker.lock().unwrap() = Some(
        crate::local_runtime::automation_worker::AutomationWorkerHandle::blocked_shutdown_fixture(
            worker_release.clone(),
        ),
    );
    let service = crate::local_runtime::LocalRuntimeService {
        state: state.clone(),
        api_base_url: "http://unused.invalid".into(),
    };
    let task = tokio::spawn(async move { service.shutdown().await });
    tokio::time::timeout(Duration::from_millis(750), async {
        while !helper
            .requests()
            .iter()
            .any(|request| request["method"] == "stop_session")
        {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("native stop must precede a blocked automation shutdown");
    let requests = helper.requests();
    let stop = requests
        .iter()
        .find(|request| request["method"] == "stop_session")
        .unwrap();
    assert_eq!(stop["params"]["input_mode"], "background");
    assert_eq!(stop["params"]["input_generation"], "fixture-generation");
    assert_eq!(stop["params"]["session_id"], "shutdown-priority");
    assert!(!task.is_finished());
    assert!(state.computer_use.client().is_err());
    let mut fresh = context;
    fresh.session_id = "forbidden-new-session".into();
    assert!(helper
        .client
        .request_in_session(&fresh, "list_apps", json!({}))
        .await
        .is_err());
    worker_release.notify_one();
    tokio::time::timeout(Duration::from_secs(2), task)
        .await
        .unwrap()
        .unwrap();
    assert!(state.computer_use.client().is_err());
    assert!(helper
        .client
        .request_in_session(&fresh, "list_apps", json!({}))
        .await
        .is_err());
    assert_eq!(
        helper
            .requests()
            .iter()
            .filter(|request| request["method"] == "begin_session")
            .count(),
        1
    );
    assert!(helper.root.join("closed").exists());
}
