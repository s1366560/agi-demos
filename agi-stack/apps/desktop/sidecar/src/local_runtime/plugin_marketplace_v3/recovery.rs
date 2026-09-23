//! Recover publication journals before background MCP startup resumes any plugin.
use super::*;
pub(in crate::local_runtime) fn recover(state: &LocalRuntimeState) -> PackageResult<()> {
    let Some(base) = state
        .app_data_dir
        .as_ref()
        .map(|p| p.join("plugin-marketplace-v3"))
    else {
        return Ok(());
    };
    if !base.exists() {
        return Ok(());
    }
    let mut preserved = std::collections::BTreeSet::new();
    for entry in std::fs::read_dir(base).map_err(|e| e.to_string())? {
        let root = entry.map_err(|e| e.to_string())?.path();
        if !root.join("state.json").is_file() {
            continue;
        }
        let mut data = load(&root)?;
        let owned_skills = data
            .installations
            .iter()
            .chain(
                data.transition
                    .iter()
                    .map(|transition| &transition.replacement),
            )
            .flat_map(|installation| {
                installation.skill_ids.iter().map(move |id| {
                    (
                        id.clone(),
                        (installation.plugin_id.clone(), installation.version.clone()),
                    )
                })
            })
            .collect::<std::collections::BTreeMap<_, _>>();
        if let Some(transition) = data.transition.take() {
            if transition
                .replacement
                .server_ids
                .iter()
                .all(|id| state.mcp_supervisor.marketplace_server_active(id))
            {
                if let Some(index) = data
                    .installations
                    .iter()
                    .position(|i| i.id == transition.installation_id)
                {
                    data.installations[index] = transition.replacement;
                }
            }
        }
        oauth::cleanup_uninstalled(&mut data);
        for installation in &mut data.installations {
            oauth::recover_services(installation);
        }
        let current = data
            .installations
            .iter()
            .filter(|i| i.status != "uninstalled")
            .collect::<Vec<_>>();
        preserved.extend(current.iter().flat_map(|i| i.server_ids.iter().cloned()));
        if let Some(scope) = &data.scope {
            let skills = current
                .iter()
                .flat_map(|i| i.skill_ids.iter().cloned())
                .collect::<std::collections::BTreeSet<_>>();
            for installation in &current {
                for id in &installation.skill_ids {
                    resources::skill_status(
                        state,
                        &scope.tenant_id,
                        &scope.project_id,
                        installation,
                        id,
                        if installation.status == "enabled" {
                            "active"
                        } else {
                            "disabled"
                        },
                    )?;
                }
            }
            for mut skill in state.session_store.list_managed_resources(
                super::super::ManagedResourceKind::Skill,
                "project",
                &scope.project_id,
            )? {
                let id = package::text(&skill, "id");
                if owned_skills.get(&id).is_some_and(|(plugin, version)| {
                    package::text(&skill, "plugin_id") == *plugin
                        && package::text(&skill, "plugin_version") == *version
                }) && !skills.contains(&id)
                {
                    skill["status"] = json!("deleted");
                    skill["enabled"] = json!(false);
                    let revision = skill.get("revision").and_then(Value::as_u64);
                    state
                        .session_store
                        .put_managed_resource(
                            super::super::ManagedResourceKind::Skill,
                            "project",
                            &scope.project_id,
                            &id,
                            "deleted",
                            revision,
                            skill,
                            chrono::Utc::now().timestamp_millis(),
                        )
                        .map_err(|e| e.to_string())?;
                }
            }
        }
        jobs::interrupt_running(&mut data);
        cache::collect(&root, &mut data, true)?;
        save(&root, &data)?;
    }
    state
        .mcp_supervisor
        .recover_marketplace_candidates(&preserved)
        .map_err(|e| e.to_string())
}
