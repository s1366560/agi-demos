//! Browser identities originate in the live execution context, never in REPL data.
use super::{
    authority_store::DesktopRun,
    local_plugin_tool_host_v2::identity::{current_child, ChildIdentityV2},
};
use agistack_adapters_browser::caller::BrowserCaller;
use agistack_core::ports::{CoreError, CoreResult};

pub(super) fn for_run(run: &DesktopRun) -> CoreResult<BrowserCaller> {
    from_identity(&run.id, run.revision, &run.conversation_id, current_child())
}

fn from_identity(
    run: &str,
    revision: u64,
    conversation: &str,
    child: Option<ChildIdentityV2>,
) -> CoreResult<BrowserCaller> {
    if child
        .as_ref()
        .is_some_and(|child| child.run_id != run || child.revision != revision)
    {
        return Err(CoreError::Tool("browser_child_run_changed".into()));
    }
    Ok(BrowserCaller {
        session_id: child
            .as_ref()
            .map(|child| child.execution_id.clone())
            .unwrap_or_else(|| conversation.into()),
        main_session_id: conversation.into(),
        caller_id: child
            .as_ref()
            .map(|child| child.execution_id.clone())
            .unwrap_or_else(|| run.into()),
        turn_id: run.into(),
        allow_dot: child.is_some(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn child() -> ChildIdentityV2 {
        ChildIdentityV2 {
            execution_id: "execution".into(),
            subagent_id: "child".into(),
            run_id: "run".into(),
            revision: 2,
        }
    }

    #[test]
    fn root_and_child_have_distinct_private_sessions_and_one_main_conversation() {
        let root = from_identity("run", 2, "conversation", None).unwrap();
        assert_eq!(root.session_id, "conversation");
        assert_eq!(root.caller_id, "run");
        assert!(!root.allow_dot);
        let child = from_identity("run", 2, "conversation", Some(child())).unwrap();
        assert_eq!(child.session_id, "execution");
        assert_eq!(child.caller_id, "execution");
        assert_eq!(child.main_session_id, "conversation");
        assert_eq!(child.turn_id, "run");
        assert!(child.allow_dot);
    }

    #[test]
    fn child_scope_cannot_be_reused_for_a_different_parent_or_revision() {
        assert!(from_identity("other", 2, "conversation", Some(child())).is_err());
        assert!(from_identity("run", 3, "conversation", Some(child())).is_err());
    }
}
