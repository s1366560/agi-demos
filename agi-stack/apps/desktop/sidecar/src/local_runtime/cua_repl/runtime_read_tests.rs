//! Real Node covers cancellation and resource limits while App reads are suspended.
use super::*;

const READ: &str =
    "{browserId:'mcpapps',operation:'playwright.locator',wait:true,args:[[],'waitFor',[{}]]}";

async fn wait_calls(owner: &Fixture, expected: usize) {
    tokio::time::timeout(Duration::from_secs(3), async {
        while owner.calls.load(Ordering::SeqCst) < expected {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn cancelled_callback_settles_suspended_read_once_without_readmission() {
    let cfg = config(DesktopPermissionProfile::ReadOnly);
    let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
    let runtime = Arc::new(ReplRuntime::default());
    let owner = fixture();
    let code = format!("await nodeRepl.rpc('browser.operation',{READ})");
    let active = tokio::spawn({
        let runtime = runtime.clone();
        let owner = owner.clone();
        let cfg = cfg.clone();
        let code = code.clone();
        async move { execute(&runtime, owner, cfg, &code, 5000).await }
    });
    let context = wait_context(&runtime).await;
    wait_calls(&owner, 1).await;
    let dispatch: ExternalDispatch =
        Arc::new(|authority| Box::pin(async move { authority.call("computer_write", "{}").await }));
    let callback = tokio::spawn(async move { context.submit(dispatch).await });
    let pending = active.await.unwrap().unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&pending.output_json).unwrap()["error"],
        "cua_permission_required"
    );
    callback.abort();
    assert!(callback.await.unwrap_err().is_cancelled());
    owner.granted.store(true, Ordering::SeqCst);
    let result = tokio::time::timeout(
        Duration::from_secs(2),
        execute(&runtime, owner.clone(), cfg, &code, 5000),
    )
    .await
    .unwrap()
    .unwrap();
    let result: Value = serde_json::from_str(&result.output_json).unwrap();
    drop(runtime);
    std::fs::remove_dir_all(root).unwrap();
    assert_eq!(result["ok"], false, "{result}");
    assert_eq!(
        result["error"]["message"],
        "repl_callback_cancelled_before_dispatch"
    );
    assert_eq!(owner.calls.load(Ordering::SeqCst), 2);
    assert_eq!(owner.writes.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn suspended_app_reads_still_count_towards_the_concurrent_rpc_limit() {
    let cfg = config(DesktopPermissionProfile::WorkspaceWrite);
    let root = cfg.sandbox.workspace.parent().unwrap().to_owned();
    let runtime = Arc::new(ReplRuntime::default());
    let owner = fixture();
    let release = cfg.sandbox.workspace.join("resume");
    let queued = cfg.sandbox.workspace.join("queued");
    let code = format!("var reads=Array.from({{length:31}},()=>nodeRepl.rpc('browser.operation',{READ})); var fs=await import('node:fs/promises'); while(!(await fs.stat({}).catch(()=>null))) await new Promise(r=>setTimeout(r,5)); reads.push(nodeRepl.rpc('browser.operation',{READ})); await fs.writeFile({},'queued'); await Promise.all(reads)",json!(release),json!(queued));
    let active = tokio::spawn({
        let runtime = runtime.clone();
        let owner = owner.clone();
        let cfg = cfg.clone();
        let code = code.clone();
        async move { execute(&runtime, owner, cfg, &code, 5000).await }
    });
    let context = wait_context(&runtime).await;
    wait_calls(&owner, 31).await;
    let hold = Arc::new(tokio::sync::Notify::new());
    let dispatch: ExternalDispatch = Arc::new({
        let owner = owner.clone();
        let hold = hold.clone();
        move |authority| {
            let owner = owner.clone();
            let hold = hold.clone();
            Box::pin(async move {
                if owner.granted.load(Ordering::SeqCst) {
                    hold.notified().await;
                }
                authority.call("computer_write", "{}").await
            })
        }
    });
    let callback = tokio::spawn(async move { context.submit(dispatch).await });
    active.await.unwrap().unwrap();
    std::fs::write(release, "resume").unwrap();
    tokio::time::timeout(Duration::from_secs(2), async {
        while !queued.is_file() {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
    owner.granted.store(true, Ordering::SeqCst);
    let result = execute(&runtime, owner.clone(), cfg, &code, 5000).await;
    let callback = callback.await.unwrap();
    drop(runtime);
    std::fs::remove_dir_all(root).unwrap();
    assert!(result
        .unwrap_err()
        .to_string()
        .contains("repl_concurrent_operation_limit"));
    assert!(callback.is_err());
    assert_eq!(owner.calls.load(Ordering::SeqCst), 32);
    assert_eq!(owner.writes.load(Ordering::SeqCst), 0);
}
