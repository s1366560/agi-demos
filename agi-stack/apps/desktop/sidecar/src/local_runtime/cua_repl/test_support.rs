use super::*;

pub(in crate::local_runtime) fn state(
    token: &str,
) -> (
    Arc<LocalRuntimeState>,
    LocalConversation,
    DesktopRun,
    std::path::PathBuf,
) {
    let (root, store, run, _) = crate::local_runtime::authorized_tool_host::tests::running_host(
        crate::local_runtime::DesktopPermissionProfile::ReadOnly,
    )
    .unwrap();
    store.seed_test_session(token).unwrap();
    let conversation = store.conversation(&run.conversation_id).unwrap().unwrap();
    let mut state = LocalRuntimeState::new(
        root.clone(),
        agistack_adapters_local_tools::LocalToolHost::new(&root).unwrap(),
        Arc::new(agistack_adapters_device::SqliteCheckpointStore::in_memory().unwrap()),
        token.into(),
        store,
    )
    .unwrap();
    state.app_data_dir = Some(root.join("private-app-data"));
    std::fs::create_dir_all(state.app_data_dir.as_ref().unwrap()).unwrap();
    (Arc::new(state), conversation, run, root)
}
