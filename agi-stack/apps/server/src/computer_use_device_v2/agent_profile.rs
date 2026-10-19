//! A focused native-tool scope from the persisted custom Agent selected by this conversation.
use super::*;
use sqlx::{FromRow, PgPool};

pub(super) const SNAPSHOT_KEY: &str = "computer_use_agent_profile";
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AgentProfile {
    pub source: String,
    pub selected_agent_id: Option<String>,
    pub allowed_tools: Option<Vec<String>>,
    pub allowed_mcp_servers: Vec<String>,
}
impl AgentProfile {
    pub(super) fn permits(&self, tool: &str) -> bool {
        self.allowed_tools.as_ref().is_none_or(|tools| {
            tools
                .iter()
                .any(|allowed| allowed == "*" || allowed == tool)
        })
    }
}
fn denied() -> CoreError {
    CoreError::Tool("computer_use_agent_profile_changed".into())
}
fn strings(value: &Value) -> CoreResult<Vec<String>> {
    value
        .as_array()
        .and_then(|values| {
            values
                .iter()
                .map(|value| {
                    value
                        .as_str()
                        .filter(|value| !value.is_empty())
                        .map(str::to_owned)
                })
                .collect()
        })
        .ok_or_else(denied)
}
#[derive(FromRow)]
struct AgentRow {
    id: String,
    allowed_tools: Value,
    allowed_mcp_servers: Value,
    enabled: bool,
}
fn from_row(selected: Option<String>, row: Option<AgentRow>) -> CoreResult<AgentProfile> {
    if let Some(row) = row {
        if !row.enabled || selected.as_deref() != Some(row.id.as_str()) {
            return Err(denied());
        }
        return Ok(AgentProfile {
            source: "persisted_custom_agent".into(),
            selected_agent_id: selected,
            allowed_tools: Some(strings(&row.allowed_tools)?),
            allowed_mcp_servers: strings(&row.allowed_mcp_servers)?,
        });
    }
    // The Rust foundation has no shared authority for Python's runtime-only builtin profiles.
    // It must not fabricate their external MCP roster from the workspace permission mode.
    let unresolved = selected
        .as_ref()
        .is_some_and(|id| !id.starts_with("builtin:"));
    Ok(AgentProfile {
        source: if unresolved {
            "unresolved_agent"
        } else {
            "foundation_undeclared"
        }
        .into(),
        selected_agent_id: selected,
        allowed_tools: unresolved.then(Vec::new),
        allowed_mcp_servers: vec![],
    })
}
pub(super) async fn load(
    pool: &PgPool,
    owner: &Owner,
    conversation: &str,
) -> CoreResult<AgentProfile> {
    let config:Option<Option<Value>>=sqlx::query_scalar("SELECT agent_config FROM conversations WHERE id=$1 AND user_id=$2 AND tenant_id=$3 AND project_id=$4")
        .bind(conversation).bind(&owner.user_id).bind(&owner.tenant_id).bind(&owner.project_id).fetch_optional(pool).await.map_err(|_|denied())?;
    let config = config.ok_or_else(denied)?.unwrap_or_else(|| json!({}));
    let selected = match config.get("selected_agent_id") {
        None | Some(Value::Null) => None,
        Some(Value::String(id)) if !id.is_empty() => Some(id.clone()),
        _ => return Err(denied()),
    };
    let row = if let Some(id) = selected.as_ref().filter(|id| !id.starts_with("builtin:")) {
        sqlx::query_as::<_,AgentRow>("SELECT id,allowed_tools,allowed_mcp_servers,enabled FROM agent_definitions WHERE id=$1 AND tenant_id=$2 AND (project_id=$3 OR project_id IS NULL)")
            .bind(id).bind(&owner.tenant_id).bind(&owner.project_id).fetch_optional(pool).await.map_err(|_|denied())?
    } else {
        None
    };
    from_row(selected, row)
}
pub(super) fn pinned(snapshot: &Value, current: &AgentProfile) -> CoreResult<AgentProfile> {
    let pinned: AgentProfile =
        serde_json::from_value(snapshot[SNAPSHOT_KEY].clone()).map_err(|_| denied())?;
    if &pinned != current {
        return Err(denied());
    }
    Ok(pinned)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn custom_agent_exact_tool_and_server_permissions_are_pinned_and_revalidated() {
        let profile = from_row(
            Some("custom-agent".into()),
            Some(AgentRow {
                id: "custom-agent".into(),
                enabled: true,
                allowed_tools: json!(["computer_connector_call"]),
                allowed_mcp_servers: json!(["specific-server"]),
            }),
        )
        .unwrap();
        assert!(profile.permits("computer_connector_call"));
        assert!(!profile.permits("computer_click"));
        let snapshot = json!({SNAPSHOT_KEY:profile});
        assert_eq!(pinned(&snapshot, &profile).unwrap(), profile);
        let mut changed = profile.clone();
        changed.allowed_mcp_servers.push("another-server".into());
        assert!(pinned(&snapshot, &changed).is_err());
        changed = profile.clone();
        changed.selected_agent_id = Some("different-agent".into());
        assert!(pinned(&snapshot, &changed).is_err());
        assert!(from_row(
            Some("custom-agent".into()),
            Some(AgentRow {
                id: "custom-agent".into(),
                enabled: false,
                allowed_tools: json!(["*"]),
                allowed_mcp_servers: json!(["*"])
            })
        )
        .is_err());
    }
    #[test]
    fn missing_builtin_authority_never_grants_external_mcp_and_unknown_custom_is_toolless() {
        let builtin = from_row(Some("builtin:all-access".into()), None).unwrap();
        assert!(builtin.permits("computer_connector_call"));
        assert!(builtin.allowed_mcp_servers.is_empty());
        let unknown = from_row(Some("unknown".into()), None).unwrap();
        assert!(!unknown.permits("computer_connector_call"));
    }
}
