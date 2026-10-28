use super::*;
use crate::local_runtime::execution_authority::with_step_id;

#[tokio::test]
async fn repl_once_permission_binds_step_tool_and_arguments() -> Result<(), String> {
    let (root, _, run, host) = tests::running_host(DesktopPermissionProfile::ReadOnly)?;
    let first = json!({"path":"first.txt","content":"approved"});
    let other = json!({"path":"other.txt","content":"not approved"});
    let key = step_permission_key("first-step", "write", &first).unwrap();
    host.once_permissions.lock().unwrap().extend([
        (run.id.clone(), "write".into()),
        (run.id.clone(), key.clone()),
    ]);
    for (step, input) in [("other-step", &other), ("first-step", &other)] {
        let result = with_step_id(step.into(), host.call("write", &input.to_string()))
            .await
            .map_err(|error| error.to_string())?;
        let result: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(result["error"], "repl_tool_permission_required");
        assert_eq!(result["decision_target"]["id"], step);
        assert!(!root.join("other.txt").exists());
        assert!(host
            .once_permissions
            .lock()
            .unwrap()
            .contains(&(run.id.clone(), key.clone())));
    }
    with_step_id("first-step".into(), host.call("write", &first.to_string()))
        .await
        .map_err(|error| error.to_string())?;
    assert_eq!(
        std::fs::read_to_string(root.join("first.txt")).unwrap(),
        "approved"
    );
    assert!(!host
        .once_permissions
        .lock()
        .unwrap()
        .contains(&(run.id.clone(), key)));
    assert!(host
        .once_permissions
        .lock()
        .unwrap()
        .contains(&(run.id.clone(), "write".into())));
    let denied = with_step_id("first-step".into(), host.call("write", &other.to_string()))
        .await
        .map_err(|error| error.to_string())?;
    assert_eq!(
        serde_json::from_str::<Value>(&denied).unwrap()["error"],
        "repl_tool_permission_required"
    );
    std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
    Ok(())
}

struct UncertainBrowser;
#[async_trait]
impl ToolHost for UncertainBrowser {
    fn list_tools(&self) -> Vec<String> {
        vec!["browser_navigate".into()]
    }
    async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
        Err(CoreError::Tool("bridge disconnected after sending".into()))
    }
}

#[tokio::test]
async fn repl_once_permission_is_not_restored_after_uncertain_browser_dispatch(
) -> Result<(), String> {
    let (root, store, run, _) = tests::running_host(DesktopPermissionProfile::ReadOnly)?;
    let host = AuthorizedRunToolHost::new(Arc::new(UncertainBrowser), store, run.clone());
    let input = json!({"url":"https://example.com"});
    let key = step_permission_key("step", "browser_navigate", &input).unwrap();
    host.once_permissions
        .lock()
        .unwrap()
        .insert((run.id.clone(), key.clone()));
    let result = with_step_id(
        "step".into(),
        host.call("browser_navigate", &input.to_string()),
    )
    .await;
    assert!(result
        .unwrap_err()
        .to_string()
        .contains("bridge disconnected"));
    assert!(!host
        .once_permissions
        .lock()
        .unwrap()
        .contains(&(run.id, key)));
    std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
    Ok(())
}
