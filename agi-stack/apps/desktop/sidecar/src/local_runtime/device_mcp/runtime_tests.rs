//! Real stdio discovery through the native configuration and revocation boundaries.
use super::*;
use std::{path::PathBuf, time::Duration};

struct Script {
    root: PathBuf,
    transport: Value,
}

impl Script {
    fn new(blocked: bool, credential: bool) -> Self {
        let root =
            std::env::temp_dir().join(format!("memstack-device-mcp-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        let script = root.join("server.py");
        std::fs::write(&script, r#"import json,os,pathlib,sys,time
root=pathlib.Path(__file__).parent
for line in sys.stdin:
 r=json.loads(line)
 if 'id' not in r: continue
 m=r['method']
 if m=='initialize': result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'device-test','version':'1'}}
 elif m=='tools/list':
  (root/'entered').write_text('entered')
  while (root/'blocked').exists(): time.sleep(.01)
  name='credential_ok' if os.getenv('DEVICE_TEST_SECRET')=='fixture-secret' else 'no_credential'
  result={'tools':[{'name':name,'inputSchema':{'type':'object'}}]}
 else: result={}
 print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}),flush=True)
"#).unwrap();
        if blocked {
            std::fs::write(root.join("blocked"), "blocked").unwrap();
        }
        let python = std::env::split_paths(&std::env::var_os("PATH").unwrap())
            .map(|entry| entry.join("python3"))
            .find(|path| path.is_file())
            .unwrap()
            .canonicalize()
            .unwrap();
        Self {
            root,
            transport: json!({"command":python.to_string_lossy(),"args":[script.to_string_lossy()],
                "credential_env_names":if credential {vec!["DEVICE_TEST_SECRET"]} else {vec![]}}),
        }
    }

    async fn entered(&self) {
        tokio::time::timeout(Duration::from_secs(5), async {
            while !self.root.join("entered").exists() {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
    }
}

impl Drop for Script {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

async fn create_enabled(fixture: &Fixture, script: &Script, token: &str) -> String {
    let created = fixture.call(json!({"action":"create","body":{
        "project_id":"cloud-project","name":"device-test","server_type":"stdio",
        "transport_config":script.transport,"idempotency_key":"create-device-test","enabled":false
    }}), Some(token)).await.unwrap();
    let id = created["result"]["id"].as_str().unwrap().to_owned();
    let enabled = fixture
        .call(
            json!({"action":"update","server_id":id,"body":{
                "project_id":"cloud-project","enabled":true,"idempotency_key":"enable-device-test",
                "expected_revision":created["result"]["runtime_metadata"]["revision"]
            }}),
            Some(token),
        )
        .await
        .unwrap();
    assert_eq!(enabled["context"]["token"], token);
    id
}

#[tokio::test]
async fn native_credentials_reach_only_their_cloud_owner_process_and_are_not_returned() {
    let fixture = Fixture::new().await;
    let script = Script::new(false, true);
    let vault = crate::application_vault::ApplicationCredentialVault::open(&script.root).unwrap();
    fixture
        .state
        .mcp_supervisor
        .install_credential_vault(vault)
        .unwrap();
    let token = fixture.token().await;
    let mut credential_transport = script.transport.clone();
    credential_transport["credential_env_names"] = json!([]);
    let stored = fixture.call(json!({"action":"provision_credential","body":{
        "project_id":"cloud-project","server_name":"device-test","server_type":"stdio",
        "transport_config":credential_transport,"credential_kind":"env","credential_name":"DEVICE_TEST_SECRET",
        "secret":"fixture-secret","idempotency_key":"provision-device-test"
    }}), Some(&token)).await.unwrap();
    assert_eq!(stored["result"]["stored"], true);
    assert_eq!(stored["context"]["token"], token);
    assert!(!stored.to_string().contains("fixture-secret"));
    let id = create_enabled(&fixture, &script, &token).await;
    let tested = fixture
        .call(json!({"action":"test","server_id":id}), Some(&token))
        .await
        .unwrap();
    assert_eq!(tested["result"]["tools_discovered"], 1);
    let listed = fixture.call(json!({"action":"list"}), None).await.unwrap();
    assert!(!listed.to_string().contains("fixture-secret"));
    assert!(listed.to_string().contains("credential_ok"));
    fixture.state.mcp_supervisor.evict_runtime(&id).unwrap();
    *fixture.remote.user.lock().unwrap() = "other-user".into();
    let other_token = fixture.token().await;
    let other_id = create_enabled(&fixture, &script, &other_token).await;
    assert_ne!(id, other_id);
    assert!(fixture
        .call(
            json!({"action":"test","server_id":other_id}),
            Some(&other_token)
        )
        .await
        .is_err());
    fixture
        .state
        .mcp_supervisor
        .evict_runtime(&other_id)
        .unwrap();
}

#[tokio::test]
async fn blocked_discovery_is_cancelled_on_logout_or_remote_context_switch() {
    for logout in [true, false] {
        let fixture = Fixture::new().await;
        let script = Script::new(true, false);
        let token = fixture.token().await;
        let id = create_enabled(&fixture, &script, &token).await;
        let input = fixture.input(json!({"action":"test","server_id":id}), Some(&token));
        let state = fixture.state.clone();
        let broker = fixture.broker.clone();
        let running = tokio::spawn(async move { native_operation(&state, &broker, input).await });
        script.entered().await;
        if logout {
            fixture.broker.clear().unwrap();
        } else {
            *fixture.remote.project.lock().unwrap() = "different-project".into();
        }
        let error = tokio::time::timeout(Duration::from_secs(3), running)
            .await
            .unwrap()
            .unwrap()
            .unwrap_err();
        assert!(matches!(
            error.as_str(),
            "device_mcp_context_changed" | "device_mcp_scope_mismatch"
        ));
        fixture.state.mcp_supervisor.evict_runtime(&id).unwrap();
    }
}
