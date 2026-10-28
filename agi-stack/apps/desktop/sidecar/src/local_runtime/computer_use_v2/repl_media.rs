//! Local REPL media uses the authenticated run's existing artifact ownership.
use super::{artifacts, Owner};
use crate::local_runtime::{
    execution_authority::ExecutionScope,
    knowledge_authority_v2::agent_access::PluginNativeIdentityV2, LocalRuntimeState,
};
use agistack_adapters_cua::CuaCallContext;
use agistack_core::ports::{CoreError, CoreResult, ToolResult};
use serde_json::{json, Value};

pub(in crate::local_runtime) async fn persist_local(
    state: &LocalRuntimeState,
    identity: &PluginNativeIdentityV2,
    scope: &ExecutionScope,
    result: &mut ToolResult,
) -> CoreResult<()> {
    let auth = identity.auth();
    let conversation = state
        .session_store
        .conversation(&scope.conversation_id)
        .map_err(CoreError::Tool)?
        .ok_or_else(|| CoreError::Tool("repl_artifact_conversation_missing".into()))?;
    let run = state
        .session_store
        .run(&scope.run_id)
        .map_err(CoreError::Tool)?
        .ok_or_else(|| CoreError::Tool("repl_artifact_run_missing".into()))?;
    if !identity.current(state)
        || PluginNativeIdentityV2::capture(state, &conversation, Some(&run)).is_none()
        || run.revision != scope.run_revision
        || auth.workspace.tenant_id != scope.tenant_id
        || auth.workspace.project_id != scope.project_id
    {
        return Err(CoreError::Tool("repl_artifact_authority_revoked".into()));
    }
    let owner = Owner {
        user_id: auth.user.user_id.clone(),
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
        device_id: state.session_store.installation_id().into(),
    };
    let context = CuaCallContext {
        user_id: owner.user_id.clone(),
        tenant_id: owner.tenant_id.clone(),
        project_id: owner.project_id.clone(),
        device_id: owner.device_id.clone(),
        conversation_id: scope.conversation_id.clone(),
        run_id: scope.run_id.clone(),
        session_id: scope.engine_session_id.clone(),
        input_mode: Default::default(),
    };
    artifacts::persist(state, &owner, &context, result).await?;
    let descriptors = artifacts::media_descriptors(state, &owner, &result.media)
        .map_err(CoreError::Tool)?
        .into_iter()
        .map(|mut descriptor| {
            descriptor["store"] = json!("device");
            descriptor["kind"] = json!(if descriptor["mime_type"]
                .as_str()
                .is_some_and(|mime| mime.starts_with("audio/"))
            {
                "audio"
            } else {
                "image"
            });
            descriptor["url"] = json!(format!(
                "cua-artifact:{}",
                descriptor["artifact_id"].as_str().unwrap_or_default()
            ));
            descriptor
        })
        .collect::<Vec<_>>();
    let mut output: Value = serde_json::from_str(&result.output_json)
        .map_err(|_| CoreError::Tool("repl_output_invalid".into()))?;
    output["artifacts"] = json!(descriptors);
    result.output_json = output.to_string();
    Ok(())
}

#[cfg(all(test, target_os = "macos"))]
#[path = "repl_media_vision_tests.rs"]
mod vision_tests;

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::*;
    use crate::local_runtime::{
        computer_use_v2::{call_identity, cloud_tests},
        cua_repl,
        knowledge_authority_v2::agent_access::{self, RunAuthorization},
    };
    use agistack_core::{agent::tool_policy::ToolPolicyContext, ports::ToolHost};
    use base64::{engine::general_purpose::STANDARD, Engine};
    use std::sync::Arc;

    #[tokio::test]
    async fn local_repl_emitted_media_is_scoped_persistent_and_previewable() {
        let token = "local-repl-media";
        let (state, conversation, run, root) = cua_repl::test_support::state(token);
        cloud_tests::publish_factory(&state, true).await;
        let auth = state
            .session_store
            .validate_session_credential(token, chrono::Utc::now().timestamp_millis())
            .unwrap()
            .unwrap();
        let owner = Owner {
            user_id: auth.user.user_id.clone(),
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: auth.workspace.project_id.clone(),
            device_id: state.session_store.installation_id().into(),
        };
        let authorization = RunAuthorization::capture(
            auth,
            Some(
                state
                    .platform_plugin_authority_v2
                    .acquire_generation()
                    .unwrap()
                    .into(),
            ),
            &conversation,
            &run.message_id,
            Some(&run.id),
        )
        .unwrap();
        let _control = state
            .claim_agent_run(&conversation.id, Some(&run.id))
            .unwrap();
        let profile = state.execution_profile(&conversation).unwrap();
        let inner: Arc<dyn ToolHost> =
            Arc::new(agistack_adapters_local_tools::LocalToolHost::new(&root).unwrap());
        let mut png = std::io::Cursor::new(Vec::new());
        image::DynamicImage::new_rgba8(2, 2)
            .write_to(&mut png, image::ImageFormat::Png)
            .unwrap();
        let image = json!(STANDARD.encode(png.into_inner()));
        let code = format!("nodeRepl.write('before'); nodeRepl.emitImage({{bytes:Buffer.from({image},'base64'),mimeType:'image/png'}}); nodeRepl.write('between'); nodeRepl.emitAudio({{bytes:Buffer.from('RIFF-test-audio'),mimeType:'audio/wav'}}); nodeRepl.emitImage({{bytes:Buffer.from({image},'base64'),mimeType:'image/png'}}); nodeRepl.write('after');");
        let result = agent_access::scope(Some(authorization), async {
            let host = cua_repl::wrap_tools(&state, inner, &conversation, &run, &profile, None);
            let context = ToolPolicyContext {
                session_id: "media-engine",
                round: 1,
                tool: "cua_repl_js",
            };
            call_identity::scope(
                &context,
                host.call_with_content("cua_repl_js", &json!({"code":code}).to_string()),
            )
            .await
            .unwrap()
        })
        .await;
        let output: Value = serde_json::from_str(&result.output_json).unwrap();
        assert_eq!(output["ok"], true, "{output}");
        let descriptors = output["artifacts"].as_array().unwrap();
        assert_eq!(descriptors.len(), 3);
        assert_eq!(output["outputs"], json!([
            {"type":"text","text":"before"},
            {"type":"text","text":"between"},
            {"type":"text","text":"after"},
        ]));
        assert_eq!(output["output_order"], json!([
            {"source":"text","index":0},
            {"source":"media","index":0},
            {"source":"text","index":1},
            {"source":"media","index":1},
            {"source":"media","index":2},
            {"source":"text","index":2},
        ]));
        let image_id = descriptors[0]["artifact_id"].as_str().unwrap();
        let audio_id = descriptors[1]["artifact_id"].as_str().unwrap();
        assert_eq!(descriptors[0]["kind"], "image");
        assert_eq!(descriptors[1]["kind"], "audio");
        assert!(
            artifacts::preview(&state, &owner, image_id).unwrap()["data_url"]
                .as_str()
                .unwrap()
                .starts_with("data:image/png;base64,")
        );
        assert_eq!(
            artifacts::audio_chunk(&state, &owner, audio_id, 0).unwrap()["data_base64"],
            STANDARD.encode(b"RIFF-test-audio")
        );
        assert!(artifacts::attachment(&state, &owner, "other-conversation", audio_id).is_err());
        let mut foreign = owner.clone();
        foreign.user_id = "another-user".into();
        assert!(artifacts::audio_chunk(&state, &foreign, audio_id, 0).is_err());
        state.cua_repl.shutdown();
        assert!(artifacts::preview(&state, &owner, image_id).is_ok());
        assert!(artifacts::audio_chunk(&state, &owner, audio_id, 0).is_ok());
        drop(state);
        std::fs::remove_dir_all(root).unwrap();
    }
}
