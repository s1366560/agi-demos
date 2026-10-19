//! Explicit operation ownership for local business features. An accepted renderer
//! configuration controls admission; a running operation keeps its existing lease.

use super::{AuthenticatedContext, LocalRuntimeState};
use crate::{local_plugin_configuration_v2, plugin_snapshots_v2};
use agistack_plugin_host::protocol_v2::{ScopeKindV2, ScopeV2};
use std::collections::{BTreeMap, BTreeSet};

/// These are exact Axum route templates, declared alongside their business owner.
/// No request text or user-provided category participates in ownership selection.
pub(super) fn owner(route: &str) -> Option<&'static str> {
    Some(match route {
        "/api/v1/llm-providers/"
        | "/api/v1/llm-providers/types"
        | "/api/v1/llm-providers/models/:provider_type"
        | "/api/v1/llm-providers/test-connection"
        | "/api/v1/llm-providers/routing-policy"
        | "/api/v1/llm-providers/:provider_id"
        | "/api/v1/llm-providers/:provider_id/runtime-selection"
        | "/api/v1/llm-providers/:provider_id/health-check"
        | "/api/v1/llm-providers/:provider_id/models/discover"
        | "/api/v1/llm-providers/:provider_id/usage" => {
            "builtin-desktop-feature-tenant-tenant-providers"
        }
        "/api/v1/skills/"
        | "/api/v1/skills/import"
        | "/api/v1/skills/:skill_id"
        | "/api/v1/skills/:skill_id/status"
        | "/api/v1/skills/:skill_id/content"
        | "/api/v1/skills/:skill_id/versions"
        | "/api/v1/skills/:skill_id/versions/:version_number"
        | "/api/v1/skills/:skill_id/rollback"
        | "/api/v1/skills/:skill_id/export" => "builtin-desktop-feature-tenant-tenant-skills",
        "/api/v1/agent/definitions"
        | "/api/v1/agent/definitions/:definition_id"
        | "/api/v1/agent/definitions/:definition_id/enabled" => {
            "builtin-desktop-feature-tenant-tenant-agent-definitions"
        }
        "/api/v1/subagents/"
        | "/api/v1/subagents/:subagent_id"
        | "/api/v1/subagents/:subagent_id/enable" => "builtin-desktop-settings-subagents",
        "/api/v1/agent/templates" | "/api/v1/agent/templates/:template_id" => {
            "builtin-desktop-feature-tenant-tenant-templates"
        }
        "/api/v1/projects/:project_id/cron-jobs"
        | "/api/v1/projects/:project_id/cron-jobs/capabilities"
        | "/api/v1/projects/:project_id/cron-jobs/:automation_id"
        | "/api/v1/projects/:project_id/cron-jobs/:automation_id/toggle"
        | "/api/v1/projects/:project_id/cron-jobs/:automation_id/run"
        | "/api/v1/projects/:project_id/cron-jobs/:automation_id/runs" => {
            "builtin-desktop-feature-project-project-cron-jobs"
        }
        "/api/v1/browser-bridge/origin-grants"
        | "/api/v1/browser-bridge/origin-grants/:grant_id"
        | "/api/v1/browser-bridge/capability-grants"
        | "/api/v1/browser-bridge/capability-grants/:grant_id"
        | "/api/v1/browser-bridge/site-credentials"
        | "/api/v1/browser-bridge/site-credentials/:credential_id"
        | "/api/v1/browser-bridge/audit" => "builtin-desktop-settings-browser",
        "/api/v1/projects/:project_id/sandbox/terminal" => "builtin-desktop-panel-terminal",
        // The existing terminal WebSocket and run-control endpoints complete leases
        // admitted earlier, so disabling an entry does not interrupt their cleanup.
        _ => return None,
    })
}

pub(super) fn require_feature(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    entry_id: &str,
) -> Result<(), &'static str> {
    let scope = ScopeV2 {
        kind: ScopeKindV2::Project,
        tenant_id: Some(auth.workspace.tenant_id.clone()),
        project_id: Some(auth.workspace.project_id.clone()),
        session_id: None,
    };
    let identity = local_plugin_configuration_v2::authority(&scope)
        .map_err(|_| "feature_configuration_unavailable")?;
    let connection = state
        .session_store
        .connection()
        .map_err(|_| "feature_configuration_unavailable")?;
    plugin_snapshots_v2::initialize_schema(&connection)
        .map_err(|_| "feature_configuration_unavailable")?;
    let record = plugin_snapshots_v2::read_state(&connection, &identity)
        .map_err(|_| "feature_configuration_unavailable")?;
    let Some(accepted) = record.and_then(|value| value.last_good) else {
        return Ok(());
    };
    let entries: BTreeMap<_, _> = accepted
        .snapshot
        .entries
        .iter()
        .map(|entry| (entry.entry_id.as_str(), entry))
        .collect();
    let Some(mut entry) = entries.get(entry_id).copied() else {
        return Ok(());
    };
    let mut visited = BTreeSet::new();
    loop {
        if !entry.enabled || !visited.insert(entry.entry_id.as_str()) {
            return Err("feature_disabled");
        }
        let Some(parent_id) = entry.parent_entry_id.as_deref() else {
            return Ok(());
        };
        entry = entries.get(parent_id).copied().ok_or("feature_disabled")?;
    }
}
