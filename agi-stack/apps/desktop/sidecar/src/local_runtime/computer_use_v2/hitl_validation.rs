//! Host-captured execution authority; the model supplies only its decision.
use super::{hitl, Owner};
use crate::local_runtime::{
    knowledge_authority_v2::agent_access::PluginNativeIdentityV2,
    local_plugin_tool_host_v2::identity::current_child, DesktopRun, LocalConversation,
    LocalRuntimeState,
};
use agistack_core::{
    agent::{
        hitl_validation::{HitlValidationContext, HitlValidationPort},
        types::HitlRequest,
    },
    ports::{CoreError, CoreResult},
};
use async_trait::async_trait;
use std::sync::{Arc, Weak};

pub(in crate::local_runtime) struct NativeHitlValidation {
    state: Weak<LocalRuntimeState>,
    identity: Option<PluginNativeIdentityV2>,
    tenant_id: String,
    project_id: String,
    conversation_id: String,
    has_run: bool,
    run_id: String,
    child_id: Option<String>,
}
impl NativeHitlValidation {
    pub(in crate::local_runtime) fn capture(
        state: &Arc<LocalRuntimeState>,
        conversation: &LocalConversation,
        run: Option<&DesktopRun>,
        message_id: &str,
        child_id: Option<String>,
    ) -> Arc<dyn HitlValidationPort> {
        Arc::new(Self {
            state: Arc::downgrade(state),
            identity: PluginNativeIdentityV2::capture(state, conversation, run),
            tenant_id: conversation.tenant_id.clone(),
            project_id: conversation.project_id.clone(),
            conversation_id: conversation.id.clone(),
            has_run: run.is_some(),
            run_id: run
                .map(|run| run.id.as_str())
                .unwrap_or(message_id)
                .to_owned(),
            child_id,
        })
    }
}
#[async_trait]
impl HitlValidationPort for NativeHitlValidation {
    fn bind_request_id(
        &self,
        context: &HitlValidationContext<'_>,
        model_request_id: &str,
    ) -> CoreResult<String> {
        // An encoded tuple prevents ambiguous delimiters. Even an agent-supplied
        // local-hitl prefix is an untrusted label, never an existing binding.
        let binding = serde_json::to_vec(&(
            "desktop-hitl-request-v1",
            &self.tenant_id,
            &self.project_id,
            &self.conversation_id,
            self.has_run,
            &self.run_id,
            &self.child_id,
            context.session_id,
            context.round,
            model_request_id,
        ))
        .map_err(|error| CoreError::Storage(error.to_string()))?;
        Ok(format!(
            "local-hitl-{}",
            uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_OID, &binding)
        ))
    }

    async fn validate(
        &self,
        context: &HitlValidationContext<'_>,
        request: &HitlRequest,
    ) -> CoreResult<()> {
        if request
            .decision
            .as_ref()
            .is_some_and(|decision| decision.target.kind == "repl_step")
        {
            let state = self
                .state
                .upgrade()
                .ok_or_else(|| CoreError::Tool("repl_runtime_stopped".into()))?;
            crate::local_runtime::cua_repl::permission_for_request(
                &state.cua_repl,
                &self.conversation_id,
                Some(&self.run_id),
                Some(context.session_id),
                request.kind,
                request.decision.as_deref(),
            )
            .map_err(CoreError::Tool)?;
            return Ok(());
        }
        if !request
            .decision
            .as_ref()
            .is_some_and(|decision| decision.target.kind == "computer_app")
        {
            return Ok(());
        }
        let state = self
            .state
            .upgrade()
            .ok_or_else(|| CoreError::Tool("cua_runtime_stopped".into()))?;
        let identity = self
            .identity
            .as_ref()
            .filter(|identity| identity.current(&state))
            .ok_or_else(|| CoreError::Tool("cua_native_authority_required".into()))?;
        let child = current_child();
        match (self.child_id.as_deref(), child.as_ref()) {
            (None, None) => {}
            (Some(expected), Some(child))
                if child.subagent_id == expected
                    && child.execution_id == context.session_id
                    && child.run_id == self.run_id => {}
            _ => return Err(CoreError::Tool("cua_child_scope_mismatch".into())),
        }
        let auth = identity.auth();
        let owner = Owner {
            user_id: auth.user.user_id.clone(),
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: auth.workspace.project_id.clone(),
            device_id: state.session_store.installation_id().into(),
        };
        super::cloud::factory_lease(&state, &owner).map_err(CoreError::Tool)?;
        let pending = hitl::resolve(
            &state,
            hitl::Binding {
                owner: &owner,
                conversation_id: &self.conversation_id,
                run_id: Some(&self.run_id),
                engine_session_id: Some(context.session_id),
            },
            request.kind,
            request.decision.as_deref(),
        )
        .map_err(CoreError::Tool)?
        .ok_or_else(|| CoreError::Tool("cua_decision_required".into()))?;
        let session = state
            .computer_use
            .sessions
            .lock()
            .map_err(|_| CoreError::Tool("cua_runtime_unavailable".into()))?
            .get(&pending.session_id)
            .cloned()
            .ok_or_else(|| CoreError::Tool("cua_session_expired".into()))?;
        match (
            self.child_id.as_deref(),
            session.child.as_ref(),
            child.as_ref(),
        ) {
            (None, None, None) => Ok(()),
            (Some(expected), Some(bound), Some(current))
                if bound.subagent_id == expected
                    && bound.execution_id == current.execution_id
                    && bound.run_id == current.run_id
                    && bound.revision == current.revision =>
            {
                Ok(())
            }
            _ => Err(CoreError::Tool("cua_child_scope_mismatch".into())),
        }
    }
}
