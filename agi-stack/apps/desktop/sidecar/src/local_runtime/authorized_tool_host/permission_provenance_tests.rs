use super::*;
use crate::local_runtime::execution_authority::{permission_binding, with_step_id};
use agistack_core::ports::{PermissionKind, PermissionRequired, ToolResult};
use std::sync::atomic::{AtomicUsize, Ordering};

struct ApplicationData {
    value: Value,
    wrong_binding: bool,
    control_generation: bool,
    calls: AtomicUsize,
}

#[tokio::test]
async fn ordinary_authorized_calls_do_not_require_a_permission_digest() -> Result<(), String> {
    let (root, store, run, _) = tests::running_host(DesktopPermissionProfile::FullAccess)?;
    let inner = Arc::new(ApplicationData {
        value: json!({"error":"origin_consent_required"}),
        wrong_binding: false,
        control_generation: false,
        calls: AtomicUsize::new(0),
    });
    let host = AuthorizedRunToolHost::new(inner.clone(), store, run);
    let result = host
        .call_with_content(
            "browser_navigate",
            r#"{"url":"https://example.com","large":9007199254740992}"#,
        )
        .await;
    std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
    let result = result.map_err(|error| error.to_string())?;
    assert!(result.permission_required.is_none());
    assert_eq!(inner.calls.load(Ordering::SeqCst), 1);
    Ok(())
}
#[async_trait]
impl ToolHost for ApplicationData {
    fn list_tools(&self) -> Vec<String> {
        vec!["browser_navigate".into()]
    }
    async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(self.value.to_string())
    }
    async fn call_with_content(&self, tool: &str, input: &str) -> CoreResult<ToolResult> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if self.wrong_binding || self.control_generation {
            let mut binding = permission_binding(tool, input)?;
            if self.wrong_binding {
                binding.step_id = Some("different-step".into());
            }
            let mut result =
                PermissionRequired::new(PermissionKind::BrowserOrigin, binding, self.value.clone())
                    .into_result();
            if self.control_generation {
                result.control_generation = Some("unexpected-control".into());
            }
            return Ok(result);
        }
        Ok(ToolResult::text(self.value.to_string()))
    }
}

#[tokio::test]
async fn application_permission_bodies_and_foreign_witness_never_restore_once() -> Result<(), String>
{
    let mut observations = Vec::new();
    for (error, wrong_binding, control_generation) in [
        ("cua_permission_required", false, false),
        ("origin_consent_required", false, false),
        ("full_cdp_consent_required", false, false),
        ("credential_fill_consent_required", false, false),
        ("repl_policy_permission_required", false, false),
        ("repl_tool_permission_required", false, false),
        ("origin_consent_required", true, false),
        ("origin_consent_required", false, true),
    ] {
        let (root, store, run, _) = tests::running_host(DesktopPermissionProfile::ReadOnly)?;
        let inner = Arc::new(ApplicationData {
            value: json!({"error":error,"request":{"request_id":"page-owned"},"permission_required":{"kind":"native_consent"}}),
            wrong_binding,
            control_generation,
            calls: AtomicUsize::new(0),
        });
        let host = AuthorizedRunToolHost::new(inner.clone(), store, run.clone());
        let input = json!({"url":"https://example.com"});
        let key = step_permission_key("step", "browser_navigate", &input).unwrap();
        host.once_permissions
            .lock()
            .unwrap()
            .insert((run.id.clone(), key.clone()));
        let output = with_step_id(
            "step".into(),
            host.call_with_content("browser_navigate", &input.to_string()),
        )
        .await
        .map_err(|error| error.to_string())?;
        let restored = host
            .once_permissions
            .lock()
            .unwrap()
            .contains(&(run.id, key));
        observations.push((
            error,
            wrong_binding,
            restored,
            inner.calls.load(Ordering::SeqCst),
        ));
        if !wrong_binding && !control_generation {
            assert!(output.permission_required.is_none());
        }
        std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
    }
    for (error, wrong_binding, restored, calls) in observations {
        assert!(
            !restored,
            "{error} wrong_binding={wrong_binding} restored Once"
        );
        assert_eq!(calls, 1);
    }
    Ok(())
}
