//! Explicit HTTP run authority. Background recovery never fabricates a session.
use super::*;
use crate::local_runtime::{DesktopRun, LocalConversation, LocalRuntimeState};
use agistack_core::ports::ToolHost;
use std::future::Future;

mod host;

pub(in crate::local_runtime) struct RunAuthorization {
    auth: AuthenticatedContext,
    lease: Arc<ActivePlatformPluginGenerationLeaseV2>,
    conversation_id: String,
    workspace_id: Option<String>,
    message_id: String,
    run_id: Option<String>,
}

tokio::task_local! {
    static CURRENT: Option<Arc<RunAuthorization>>;
}

#[cfg(test)]
tokio::task_local! {
    static BEFORE_DELIVERY_TEST_HOOK: std::cell::RefCell<Option<Box<dyn FnOnce() + Send>>>;
}

#[cfg(test)]
pub(in crate::local_runtime) async fn with_before_delivery_test_hook<F: Future>(
    hook: impl FnOnce() + Send + 'static,
    future: F,
) -> F::Output {
    BEFORE_DELIVERY_TEST_HOOK
        .scope(std::cell::RefCell::new(Some(Box::new(hook))), future)
        .await
}

#[cfg(test)]
fn before_delivery_test_hook() {
    let hook = BEFORE_DELIVERY_TEST_HOOK
        .try_with(|value| value.borrow_mut().take())
        .ok()
        .flatten();
    if let Some(hook) = hook {
        hook();
    }
}

impl RunAuthorization {
    pub(in crate::local_runtime) fn capture(
        auth: AuthenticatedContext,
        lease: Option<Arc<ActivePlatformPluginGenerationLeaseV2>>,
        conversation: &LocalConversation,
        message_id: &str,
        run_id: Option<&str>,
    ) -> Option<Arc<Self>> {
        let lease = lease?;
        if conversation.tenant_id != auth.workspace.tenant_id
            || conversation.project_id != auth.workspace.project_id
        {
            return None;
        }
        Some(Arc::new(Self {
            auth,
            lease,
            conversation_id: conversation.id.clone(),
            workspace_id: conversation.workspace_id.clone(),
            message_id: message_id.to_owned(),
            run_id: run_id.map(str::to_owned),
        }))
    }

    fn operation(&self) -> Result<KnowledgeOperationV2, KnowledgeAuthorityErrorV2> {
        let d = self.lease.descriptor();
        KnowledgeOperationV2::admit(
            self.lease.clone(),
            &self.auth,
            &KnowledgeOperationScopeV2 {
                tenant_id: self.auth.workspace.tenant_id.clone(),
                project_id: self.auth.workspace.project_id.clone(),
                context_revision: self.auth.workspace.revision,
                profile_id: d.profile_id.clone(),
                generation: d.generation,
                digest: d.digest.clone(),
            },
        )
    }

    fn matches(&self, conversation: &LocalConversation, run: Option<&DesktopRun>) -> bool {
        conversation.id == self.conversation_id
            && conversation.workspace_id == self.workspace_id
            && conversation.tenant_id == self.auth.workspace.tenant_id
            && conversation.project_id == self.auth.workspace.project_id
            && run.map(|r| r.id.as_str()) == self.run_id.as_deref()
            && run.map_or(true, |r| {
                r.message_id == self.message_id
                    && r.conversation_id == self.conversation_id
                    && r.project_id == self.auth.workspace.project_id
                    && r.status == crate::local_runtime::DesktopRunStatus::Running
            })
    }

    fn ensure_current(
        self: &Arc<Self>,
        state: &LocalRuntimeState,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        if !CURRENT
            .try_with(|current| current.as_ref().is_some_and(|a| Arc::ptr_eq(a, self)))
            .unwrap_or(false)
        {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        let conversation = state
            .session_store
            .conversation(&self.conversation_id)
            .map_err(|_| KnowledgeAuthorityErrorV2::Forbidden)?
            .ok_or(KnowledgeAuthorityErrorV2::Forbidden)?;
        let run = self
            .run_id
            .as_ref()
            .map(|id| state.session_store.run(id))
            .transpose()
            .map_err(|_| KnowledgeAuthorityErrorV2::Forbidden)?
            .flatten();
        if !self.matches(&conversation, run.as_ref()) {
            return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
        }
        Ok(())
    }
}

pub(in crate::local_runtime) async fn scope<F: Future>(
    authorization: Option<Arc<RunAuthorization>>,
    future: F,
) -> F::Output {
    CURRENT.scope(authorization, future).await
}

pub(in crate::local_runtime) fn tool_host(
    state: &Arc<LocalRuntimeState>,
    conversation: &LocalConversation,
    run: Option<&DesktopRun>,
    agent_id: &str,
) -> Option<Arc<dyn ToolHost>> {
    let authorization = CURRENT.try_with(Clone::clone).ok().flatten()?;
    if !authorization.matches(conversation, run) {
        return None;
    }
    authorization.ensure_current(state).ok()?;
    // Release gate and current actor capabilities decide actual exposure.
    authorization
        .operation()
        .ok()?
        .admit_capability(state, &authorization.auth, "text")
        .ok()?;
    Some(Arc::new(host::KnowledgeToolHost::new(
        state.clone(),
        authorization,
        agent_id.to_owned(),
        run.map(|r| r.revision),
    )))
}
