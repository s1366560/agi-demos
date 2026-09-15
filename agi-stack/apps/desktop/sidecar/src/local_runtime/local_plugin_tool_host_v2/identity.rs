//! Actual native operation bindings, independent of model-supplied arguments.
use super::super::{DesktopRun, LocalRunControl, LocalRuntimeState};
use std::{
    future::Future,
    sync::{atomic::Ordering, Arc},
};

#[derive(Clone)]
pub(in crate::local_runtime) struct ChildIdentityV2 {
    pub execution_id: String,
    pub subagent_id: String,
    pub run_id: String,
    pub revision: u64,
}
tokio::task_local! { static CHILD: ChildIdentityV2; }
pub(in crate::local_runtime) fn current_child() -> Option<ChildIdentityV2> {
    CHILD.try_with(Clone::clone).ok()
}
pub(in crate::local_runtime) async fn child_scope<F: Future>(
    identity: ChildIdentityV2,
    future: F,
) -> F::Output {
    CHILD.scope(identity, future).await
}

pub(super) enum Binding {
    Build {
        run_id: String,
        revision: u64,
    },
    Plan {
        message_id: String,
        control: Arc<LocalRunControl>,
    },
    Child {
        run_id: String,
        revision: u64,
        subagent_id: String,
    },
}
impl Binding {
    pub(super) fn operation_id(&self) -> Option<String> {
        match self {
            Self::Build { run_id, .. } => Some(run_id.clone()),
            Self::Plan { message_id, .. } => Some(message_id.clone()),
            Self::Child {
                run_id,
                revision,
                subagent_id,
            } => CHILD
                .try_with(|child| {
                    (child.run_id == *run_id
                        && child.revision == *revision
                        && child.subagent_id == *subagent_id)
                        .then(|| child.execution_id.clone())
                })
                .ok()
                .flatten(),
        }
    }
    pub(super) fn current(&self, state: &LocalRuntimeState, conversation_id: &str) -> bool {
        match self {
            Self::Plan { control, .. } => {
                state
                    .session_store
                    .conversation(conversation_id)
                    .is_ok_and(|conversation| {
                        conversation.is_some_and(|value| {
                            value.current_mode == super::super::ConversationRunMode::Plan
                        })
                    })
                    && CHILD.try_with(|_| ()).is_err()
                    && control.directive.load(Ordering::Acquire) == LocalRunControl::CONTINUE
                    && state.agent_runs.lock().is_ok_and(|runs| {
                        runs.get(conversation_id).is_some_and(|active| {
                            active.run_id.is_none() && Arc::ptr_eq(&active.control, control)
                        })
                    })
            }
            Self::Build { run_id, revision }
            | Self::Child {
                run_id, revision, ..
            } => {
                let Ok(Some(run)) = state.session_store.run(run_id) else {
                    return false;
                };
                if run.revision != *revision
                    || run.status != super::super::DesktopRunStatus::Running
                    || run.conversation_id != conversation_id
                {
                    return false;
                }
                match self {
                    Self::Child { subagent_id, .. } => self.operation_id().is_some_and(|id| {
                        state.subagent_controls.plugin_execution_current(
                            &id,
                            conversation_id,
                            &run,
                            subagent_id,
                            state.control_for_run(&run).as_ref(),
                        )
                    }),
                    _ => CHILD.try_with(|_| ()).is_err(),
                }
            }
        }
    }
    pub(super) fn invocation_current(&self) -> bool {
        match self {
            Self::Plan { .. } => true,
            Self::Build { run_id, revision }
            | Self::Child {
                run_id, revision, ..
            } => super::super::authorized_tool_host::current_authorized_invocation_context()
                .is_some_and(|context| {
                    context.run_id == *run_id && context.run_revision == *revision
                }),
        }
    }
    pub(super) fn build(run: &DesktopRun) -> Self {
        Self::Build {
            run_id: run.id.clone(),
            revision: run.revision,
        }
    }
}
