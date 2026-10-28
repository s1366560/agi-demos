use super::*;
use crate::local_runtime::{authority_store::DesktopRunStatus, execution_authority::with_step_id};
use std::sync::atomic::{AtomicUsize, Ordering};

#[derive(Default)]
struct OwnedRecordingHost {
    stops: AtomicUsize,
}

#[async_trait]
impl ToolHost for OwnedRecordingHost {
    fn list_tools(&self) -> Vec<String> {
        vec!["computer_audio_start".into(), "computer_audio_stop".into()]
    }

    async fn call(&self, tool: &str, input: &str) -> CoreResult<String> {
        let input: Value = serde_json::from_str(input).unwrap();
        agistack_adapters_cua::validate_tool_input(tool, &input)?;
        assert_eq!(tool, "computer_audio_stop", "start needs its own grant");
        if input["recording_id"] != "owned-recording" {
            return Err(CoreError::Tool("recording_not_found".into()));
        }
        self.stops.fetch_add(1, Ordering::SeqCst);
        Ok(json!({"recording_id":"owned-recording", "status":"stopped"}).to_string())
    }
}

#[tokio::test]
async fn owned_audio_release_needs_no_new_grant_but_preserves_inner_and_run_authority() {
    for profile in [
        DesktopPermissionProfile::ReadOnly,
        DesktopPermissionProfile::WorkspaceWrite,
    ] {
        let (root, store, run, _) = tests::running_host(profile).unwrap();
        let inner = Arc::new(OwnedRecordingHost::default());
        let host = AuthorizedRunToolHost::new(inner.clone(), store.clone(), run.clone());
        assert!(host.list_tools().contains(&"computer_audio_stop".into()));
        assert!(!host.list_tools().contains(&"computer_audio_start".into()));
        assert_eq!(tool_effect("computer_audio_stop"), Some(ToolEffect::Mutate));

        let receipt = with_step_id(
            "stop-step".into(),
            host.call_with_content(
                "computer_audio_stop",
                r#"{"recording_id":"owned-recording"}"#,
            ),
        )
        .await
        .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&receipt.output_json).unwrap()["status"],
            "stopped"
        );
        assert_eq!(inner.stops.load(Ordering::SeqCst), 1);
        assert!(host.once_permissions.lock().unwrap().is_empty());

        for invalid in [
            json!({"recording_id":"foreign-recording"}),
            json!({"recording_id":"owned-recording", "path":"/tmp/foreign.wav"}),
            json!({"recording_id":"owned-recording", "save":false}),
        ] {
            assert!(with_step_id(
                "invalid-stop".into(),
                host.call_with_content("computer_audio_stop", &invalid.to_string()),
            )
            .await
            .is_err());
        }
        let denied = with_step_id(
            "new-start".into(),
            host.call_with_content("computer_audio_start", r#"{"source":"microphone"}"#),
        )
        .await
        .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&denied.output_json).unwrap()["error"],
            "repl_tool_permission_required"
        );
        assert_eq!(inner.stops.load(Ordering::SeqCst), 1);

        store
            .transition_run(
                &run.id,
                run.revision,
                DesktopRunStatus::Cancelled,
                None,
                &crate::local_runtime::now_iso(),
            )
            .unwrap();
        assert!(with_step_id(
            "stale-stop".into(),
            host.call_with_content(
                "computer_audio_stop",
                r#"{"recording_id":"owned-recording"}"#
            ),
        )
        .await
        .is_err());
        assert_eq!(inner.stops.load(Ordering::SeqCst), 1);
        std::fs::remove_dir_all(root).unwrap();
    }
}
