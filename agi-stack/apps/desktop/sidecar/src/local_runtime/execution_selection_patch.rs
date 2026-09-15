//! Explicit user edits preserve omitted fields and clear only explicit nulls.
use super::*;
use execution_selection::ExecutionSelection;

#[derive(Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ExecutionSelectionPatch {
    #[serde(default)]
    agent_id: Field,
    #[serde(default)]
    forced_skill_id: Field,
    #[serde(default)]
    subagent_id: Field,
}

pub(super) fn deserialize_patch<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<ExecutionSelectionPatch>, D::Error> {
    ExecutionSelectionPatch::deserialize(deserializer).map(Some)
}

#[derive(Debug, Default)]
enum Field {
    #[default]
    Missing,
    Set(Option<String>),
}
impl<'de> Deserialize<'de> for Field {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = Value::deserialize(deserializer)?;
        match value {
            Value::Null => Ok(Self::Set(None)),
            Value::String(id) if !id.trim().is_empty() => Ok(Self::Set(Some(id))),
            _ => Err(serde::de::Error::custom(
                "selection field requires a nonempty ID or null",
            )),
        }
    }
}
impl Field {
    fn apply(self, target: &mut Option<String>) {
        if let Self::Set(value) = self {
            *target = value;
        }
    }
}

pub(super) fn update(
    state: &Arc<LocalRuntimeState>,
    authenticated: &AuthenticatedContext,
    conversation_id: &str,
    patch: ExecutionSelectionPatch,
) -> LocalJsonResult {
    let conversation = scoped_conversation(state, authenticated, conversation_id)?;
    let controls = state
        .agent_runs
        .lock()
        .map_err(|_| local_store_error("local controls unavailable".into()))?;
    if controls.contains_key(conversation_id)
        || state
            .session_store
            .list_runs(conversation_id)
            .map_err(local_store_error)?
            .iter()
            .any(|run| !run.status.is_terminal())
    {
        return Err((
            StatusCode::CONFLICT,
            Json(
                json!({"code":"execution_selection_run_active","detail":"Execution selection cannot change while a run is active or awaiting review"}),
            ),
        ));
    }
    let mut selection = state
        .session_store
        .execution_selection(conversation_id)
        .map_err(local_store_error)?
        .unwrap_or_default();
    patch.agent_id.apply(&mut selection.agent_id);
    patch.forced_skill_id.apply(&mut selection.forced_skill_id);
    patch.subagent_id.apply(&mut selection.subagent_id);
    let selection = selection.normalized().map_err(local_bad_request)?;
    validate(state, &conversation, &selection).map_err(local_bad_request)?;
    state
        .session_store
        .replace_execution_selection(conversation_id, &selection, &now_iso())
        .map_err(local_store_error)?;
    drop(controls);
    Ok(Json(state.conversation_value(&conversation)))
}

fn validate(
    state: &LocalRuntimeState,
    conversation: &LocalConversation,
    selection: &ExecutionSelection,
) -> Result<(), String> {
    let agent_id = selection
        .agent_id
        .as_deref()
        .unwrap_or("builtin:all-access");
    let agent = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Agent,
            "project",
            &conversation.project_id,
            agent_id,
        )?
        .ok_or("selected Agent unavailable")?;
    let skill = selection
        .forced_skill_id
        .as_deref()
        .map(|id| state.resolve_selected_skill(conversation, id))
        .transpose()?;
    if skill.as_ref().is_some_and(|skill| {
        skill.get("enabled").and_then(Value::as_bool) == Some(false)
            || skill
                .get("tenant_id")
                .and_then(Value::as_str)
                .is_some_and(|id| id != conversation.tenant_id)
            || skill
                .get("project_id")
                .and_then(Value::as_str)
                .is_some_and(|id| id != conversation.project_id)
    }) {
        return Err("selected Skill unavailable".into());
    }
    let child = selection
        .subagent_id
        .as_deref()
        .map(|id| {
            state
                .session_store
                .managed_resource(
                    ManagedResourceKind::SubAgent,
                    "tenant",
                    &conversation.tenant_id,
                    id,
                )
                .and_then(|value| value.ok_or_else(|| "selected SubAgent unavailable".into()))
        })
        .transpose()?;
    if child.as_ref().is_some_and(|value| {
        !subagent_scope::is_visible_in_project(value, &conversation.project_id)
    }) {
        return Err("selected SubAgent unavailable".into());
    }
    execution_profile::ExecutionProfile::resolve(agent_id, &agent, skill.as_ref(), child.as_ref())
        .map(|_| ())
}

impl DesktopSessionStore {
    pub(super) fn replace_execution_selection(
        &self,
        conversation_id: &str,
        selection: &ExecutionSelection,
        now: &str,
    ) -> Result<(), String> {
        self.connection()?.execute(
            "INSERT INTO desktop_conversation_execution_selections(conversation_id,agent_id,forced_skill_id,subagent_id,message_id,updated_at) VALUES(?1,?2,?3,?4,'conversation-config',?5) ON CONFLICT(conversation_id) DO UPDATE SET agent_id=excluded.agent_id,forced_skill_id=excluded.forced_skill_id,subagent_id=excluded.subagent_id,message_id=excluded.message_id,updated_at=excluded.updated_at",
            rusqlite::params![conversation_id,selection.agent_id,selection.forced_skill_id,selection.subagent_id,now],
        ).map(|_|()).map_err(|error|error.to_string())
    }
}
