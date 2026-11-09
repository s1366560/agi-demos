//! Device-user and project scoped CUA configuration. No grant crosses a scope boundary.
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
pub(in crate::local_runtime) struct Owner {
    pub user_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub device_id: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct Instance {
    pub installed: bool,
    pub enabled: bool,
    pub revision: u64,
    pub microphone: bool,
    pub system_audio: bool,
    pub locked_use: bool,
    #[serde(default)]
    pub input_mode: agistack_adapters_cua::CuaInputMode,
}

impl Default for Instance {
    fn default() -> Self {
        Self {
            installed: true,
            enabled: false,
            revision: 0,
            microphone: false,
            system_audio: false,
            locked_use: false,
            input_mode: Default::default(),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct Grant {
    pub id: String,
    pub app: String,
    pub identity_digest: String,
    pub capability: String,
    pub scope: GrantScope,
    pub session_id: Option<String>,
    pub request_id: Option<String>,
}

impl Grant {
    pub(super) fn covers(
        &self,
        app: &str,
        identity: &str,
        capability: &str,
        session: &str,
        request: &str,
    ) -> bool {
        self.app == app
            && self.identity_digest == identity
            && self.capability == capability
            && super::consent::scopes(capability).contains(&self.scope)
            && match self.scope {
                GrantScope::Always => true,
                GrantScope::Session => self.session_id.as_deref() == Some(session),
                GrantScope::Once => {
                    self.session_id.as_deref() == Some(session)
                        && self.request_id.as_deref() == Some(request)
                }
            }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(in crate::local_runtime) enum GrantScope {
    Once,
    Session,
    Always,
}

pub(super) const CAPABILITIES: &[&str] = &[
    "observe",
    "control",
    "clipboard",
    "microphone",
    "system_audio",
    "audio_mixed",
    "locked_use",
    "connectors",
    "calendar",
    "contacts",
    "messages",
    "connector_action",
];

pub(super) fn initialize(db: &Connection) -> Result<(), String> {
    db.execute_batch(
        "CREATE TABLE IF NOT EXISTS desktop_cua_instances_v2 (
        user_id TEXT NOT NULL, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL,
        device_id TEXT NOT NULL, config_json TEXT NOT NULL,
        PRIMARY KEY(user_id,tenant_id,project_id,device_id));
        CREATE TABLE IF NOT EXISTS desktop_cua_grants_v2 (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
        project_id TEXT NOT NULL, device_id TEXT NOT NULL, grant_json TEXT NOT NULL);",
    )
    .map_err(|error| error.to_string())
}

pub(super) fn pending_schema(db: &Connection) -> Result<(), String> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS desktop_cua_pending_v2 (
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,device_id TEXT NOT NULL,request_json TEXT NOT NULL);")
        .map_err(|error|error.to_string())
}
pub(super) fn save_pending(
    db: &Connection,
    owner: &Owner,
    id: &str,
    value: &serde_json::Value,
) -> Result<(), String> {
    db.execute(
        "INSERT OR REPLACE INTO desktop_cua_pending_v2 VALUES(?1,?2,?3,?4,?5,?6)",
        params![
            id,
            owner.user_id,
            owner.tenant_id,
            owner.project_id,
            owner.device_id,
            value.to_string()
        ],
    )
    .map(|_| ())
    .map_err(|error| error.to_string())
}
pub(super) fn pending_matches(
    db: &Connection,
    owner: &Owner,
    id: &str,
    value: &serde_json::Value,
) -> Result<bool, String> {
    let raw:Option<String>=db.query_row("SELECT request_json FROM desktop_cua_pending_v2 WHERE id=?1 AND user_id=?2 AND tenant_id=?3 AND project_id=?4 AND device_id=?5",params![id,owner.user_id,owner.tenant_id,owner.project_id,owner.device_id],|row|row.get(0)).optional().map_err(|error|error.to_string())?;
    Ok(raw.as_deref() == Some(value.to_string().as_str()))
}
pub(super) fn remove_pending(db: &Connection, owner: &Owner, id: &str) -> Result<(), String> {
    db.execute("DELETE FROM desktop_cua_pending_v2 WHERE id=?1 AND user_id=?2 AND tenant_id=?3 AND project_id=?4 AND device_id=?5",params![id,owner.user_id,owner.tenant_id,owner.project_id,owner.device_id]).map(|_|()).map_err(|error|error.to_string())
}

pub(super) fn instance(db: &Connection, owner: &Owner) -> Result<Instance, String> {
    let raw: Option<String> = db
        .query_row(
            "SELECT config_json FROM desktop_cua_instances_v2
        WHERE user_id=?1 AND tenant_id=?2 AND project_id=?3 AND device_id=?4",
            params![
                owner.user_id,
                owner.tenant_id,
                owner.project_id,
                owner.device_id
            ],
            |row| row.get(0),
        )
        .optional()
        .map_err(|error| error.to_string())?;
    raw.map(|raw| serde_json::from_str(&raw).map_err(|error| error.to_string()))
        .transpose()
        .map(|value| value.unwrap_or_default())
}

pub(super) fn update(
    db: &Connection,
    owner: &Owner,
    expected: u64,
    action: &str,
    capability: Option<(&str, bool)>,
) -> Result<Instance, String> {
    let mut value = instance(db, owner)?;
    if value.revision != expected {
        return Err("cua_instance_revision_conflict".into());
    }
    match action {
        "install" => value.installed = true,
        "enable" if value.installed => value.enabled = true,
        "disable" => value.enabled = false,
        "uninstall" => {
            value.installed = false;
            value.enabled = false;
            value.microphone = false;
            value.system_audio = false;
            value.locked_use = false;
            value.input_mode = Default::default();
        }
        "configure" if value.installed => match capability {
            Some(("microphone", enabled)) => value.microphone = enabled,
            Some(("system_audio", enabled)) => value.system_audio = enabled,
            Some(("locked_use", enabled)) => value.locked_use = enabled,
            _ => return Err("cua_capability_invalid".into()),
        },
        _ => return Err("cua_instance_action_invalid".into()),
    }
    value.revision = value
        .revision
        .checked_add(1)
        .ok_or("cua_instance_revision_exhausted")?;
    db.execute("INSERT INTO desktop_cua_instances_v2 VALUES(?1,?2,?3,?4,?5)
        ON CONFLICT(user_id,tenant_id,project_id,device_id) DO UPDATE SET config_json=excluded.config_json",
        params![owner.user_id,owner.tenant_id,owner.project_id,owner.device_id,
            serde_json::to_string(&value).map_err(|error| error.to_string())?])
        .map_err(|error| error.to_string())?;
    if action == "uninstall" {
        revoke_all(db, owner)?;
    }
    Ok(value)
}

pub(super) fn set_input_mode(
    db: &Connection,
    owner: &Owner,
    expected: u64,
    mode: agistack_adapters_cua::CuaInputMode,
) -> Result<Instance, String> {
    let mut value = instance(db, owner)?;
    if value.revision != expected {
        return Err("cua_instance_revision_conflict".into());
    }
    if !value.installed {
        return Err("cua_instance_action_invalid".into());
    }
    value.input_mode = mode;
    value.revision = value
        .revision
        .checked_add(1)
        .ok_or("cua_instance_revision_exhausted")?;
    db.execute("INSERT INTO desktop_cua_instances_v2 VALUES(?1,?2,?3,?4,?5) ON CONFLICT(user_id,tenant_id,project_id,device_id) DO UPDATE SET config_json=excluded.config_json",
        params![owner.user_id,owner.tenant_id,owner.project_id,owner.device_id,serde_json::to_string(&value).map_err(|error|error.to_string())?]).map_err(|error|error.to_string())?;
    Ok(value)
}

pub(super) fn grants(db: &Connection, owner: &Owner) -> Result<Vec<Grant>, String> {
    let mut query = db
        .prepare(
            "SELECT grant_json FROM desktop_cua_grants_v2
        WHERE user_id=?1 AND tenant_id=?2 AND project_id=?3 AND device_id=?4 ORDER BY id",
        )
        .map_err(|error| error.to_string())?;
    let rows = query
        .query_map(
            params![
                owner.user_id,
                owner.tenant_id,
                owner.project_id,
                owner.device_id
            ],
            |row| row.get::<_, String>(0),
        )
        .map_err(|error| error.to_string())?;
    rows.map(|row| {
        serde_json::from_str(&row.map_err(|error| error.to_string())?)
            .map_err(|error| error.to_string())
    })
    .collect()
}

pub(super) fn grant(db: &Connection, owner: &Owner, mut grant: Grant) -> Result<Grant, String> {
    if !instance(db, owner)?.enabled {
        return Err("cua_instance_disabled".into());
    }
    if grant.app.is_empty()
        || grant.identity_digest.is_empty()
        || !CAPABILITIES.contains(&grant.capability.as_str())
    {
        return Err("cua_grant_invalid".into());
    }
    if !super::consent::scopes(&grant.capability).contains(&grant.scope) {
        return Err("cua_action_requires_once".into());
    }
    match grant.scope {
        GrantScope::Once if grant.request_id.as_deref().is_none_or(str::is_empty) => {
            return Err("cua_request_required".into());
        }
        GrantScope::Session if grant.session_id.as_deref().is_none_or(str::is_empty) => {
            return Err("cua_session_required".into());
        }
        GrantScope::Always => {
            grant.session_id = None;
            grant.request_id = None;
        }
        _ => {}
    }
    grant.id = format!("cua-grant-{}", Uuid::new_v4());
    db.execute(
        "INSERT INTO desktop_cua_grants_v2 VALUES(?1,?2,?3,?4,?5,?6)",
        params![
            grant.id,
            owner.user_id,
            owner.tenant_id,
            owner.project_id,
            owner.device_id,
            serde_json::to_string(&grant).map_err(|error| error.to_string())?
        ],
    )
    .map_err(|error| error.to_string())?;
    Ok(grant)
}

/// The connection is already protected by the session-store DB mutex; once consumption is atomic.
pub(super) fn authorize(
    db: &Connection,
    owner: &Owner,
    app: &str,
    identity: &str,
    capability: &str,
    session: &str,
    request: &str,
) -> Result<bool, String> {
    let matching = grants(db, owner)?
        .into_iter()
        .find(|grant| grant.covers(app, identity, capability, session, request));
    match matching {
        Some(grant) if grant.scope == GrantScope::Once => {
            revoke(db, owner, &grant.id).map(|count| count == 1)
        }
        Some(_) => Ok(true),
        None => Ok(false),
    }
}

pub(super) fn revoke(db: &Connection, owner: &Owner, id: &str) -> Result<usize, String> {
    db.execute(
        "DELETE FROM desktop_cua_grants_v2 WHERE id=?1 AND user_id=?2
        AND tenant_id=?3 AND project_id=?4 AND device_id=?5",
        params![
            id,
            owner.user_id,
            owner.tenant_id,
            owner.project_id,
            owner.device_id
        ],
    )
    .map_err(|error| error.to_string())
}

pub(super) fn revoke_all(db: &Connection, owner: &Owner) -> Result<usize, String> {
    db.execute(
        "DELETE FROM desktop_cua_grants_v2 WHERE user_id=?1 AND tenant_id=?2
        AND project_id=?3 AND device_id=?4",
        params![
            owner.user_id,
            owner.tenant_id,
            owner.project_id,
            owner.device_id
        ],
    )
    .map_err(|error| error.to_string())
}

pub(super) fn end_session(db: &Connection, owner: &Owner, session: &str) -> Result<(), String> {
    for grant in grants(db, owner)? {
        if grant.scope != GrantScope::Always && grant.session_id.as_deref() == Some(session) {
            revoke(db, owner, &grant.id)?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn owner() -> Owner {
        Owner {
            user_id: "user".into(),
            tenant_id: "tenant".into(),
            project_id: "project".into(),
            device_id: "device".into(),
        }
    }
    fn consent(scope: GrantScope) -> Grant {
        Grant {
            id: String::new(),
            app: "org.app".into(),
            identity_digest: "signed-app".into(),
            capability: "observe".into(),
            scope,
            session_id: Some("session".into()),
            request_id: Some("request".into()),
        }
    }
    #[test]
    fn preinstalled_disabled_and_revision_protected() {
        let db = Connection::open_in_memory().unwrap();
        initialize(&db).unwrap();
        let owner = owner();
        assert!(!instance(&db, &owner).unwrap().enabled);
        update(&db, &owner, 0, "enable", None).unwrap();
        assert!(update(&db, &owner, 0, "disable", None).is_err());
        assert!(instance(&db, &owner).unwrap().enabled);
    }
    #[test]
    fn grants_are_exact_scope_identity_capability_and_once_is_consumed() {
        let db = Connection::open_in_memory().unwrap();
        initialize(&db).unwrap();
        let owner = owner();
        update(&db, &owner, 0, "enable", None).unwrap();
        grant(&db, &owner, consent(GrantScope::Once)).unwrap();
        assert!(
            !authorize(&db, &owner, "org.app", "changed", "observe", "session", "request").unwrap()
        );
        assert!(!authorize(
            &db,
            &owner,
            "org.app",
            "signed-app",
            "control",
            "session",
            "request"
        )
        .unwrap());
        let mut other = owner.clone();
        other.project_id = "other".into();
        assert!(!authorize(
            &db,
            &other,
            "org.app",
            "signed-app",
            "observe",
            "session",
            "request"
        )
        .unwrap());
        assert!(authorize(
            &db,
            &owner,
            "org.app",
            "signed-app",
            "observe",
            "session",
            "request"
        )
        .unwrap());
        assert!(!authorize(
            &db,
            &owner,
            "org.app",
            "signed-app",
            "observe",
            "session",
            "request"
        )
        .unwrap());
    }

    #[test]
    fn direct_grant_rejects_persistent_connector_and_recording_actions() {
        let db = Connection::open_in_memory().unwrap();
        initialize(&db).unwrap();
        let owner = owner();
        update(&db, &owner, 0, "enable", None).unwrap();
        for capability in [
            "connector_action",
            "microphone",
            "system_audio",
            "audio_mixed",
        ] {
            for scope in [GrantScope::Session, GrantScope::Always] {
                let mut action = consent(scope);
                action.capability = capability.into();
                assert_eq!(
                    grant(&db, &owner, action).unwrap_err(),
                    "cua_action_requires_once"
                );
            }
        }
    }
    #[test]
    fn session_expires_and_uninstall_revokes_persistent_grants() {
        let db = Connection::open_in_memory().unwrap();
        initialize(&db).unwrap();
        let owner = owner();
        update(&db, &owner, 0, "enable", None).unwrap();
        grant(&db, &owner, consent(GrantScope::Session)).unwrap();
        end_session(&db, &owner, "session").unwrap();
        assert!(grants(&db, &owner).unwrap().is_empty());
        grant(&db, &owner, consent(GrantScope::Always)).unwrap();
        update(&db, &owner, 1, "uninstall", None).unwrap();
        assert!(grants(&db, &owner).unwrap().is_empty());
        assert!(!instance(&db, &owner).unwrap().installed);
    }

    #[test]
    fn locked_use_rejects_persistent_grants_and_legacy_coverage() {
        let db = Connection::open_in_memory().unwrap();
        initialize(&db).unwrap();
        let owner = owner();
        update(&db, &owner, 0, "enable", None).unwrap();
        for scope in [GrantScope::Session, GrantScope::Always] {
            let legacy: Grant = serde_json::from_value(serde_json::json!({
                "id":format!("legacy-locked-use-{scope:?}"),
                "app":"device:control",
                "identity_digest":"device",
                "capability":"locked_use",
                "scope":scope,
                "session_id":if scope == GrantScope::Always { None } else { Some("session") },
                "request_id":null,
            }))
            .unwrap();
            assert_eq!(
                grant(&db, &owner, legacy.clone()).unwrap_err(),
                "cua_action_requires_once"
            );
            // Represent a prior version's persisted grant in this isolated in-memory database.
            db.execute(
                "INSERT INTO desktop_cua_grants_v2 VALUES(?1,?2,?3,?4,?5,?6)",
                params![
                    legacy.id,
                    owner.user_id,
                    owner.tenant_id,
                    owner.project_id,
                    owner.device_id,
                    serde_json::to_string(&legacy).unwrap()
                ],
            )
            .unwrap();
            let persisted = grants(&db, &owner).unwrap();
            for session in ["session", "new-run-session"] {
                assert!(!legacy.covers(
                    "device:control",
                    "device",
                    "locked_use",
                    session,
                    "new-request"
                ));
                assert!(!authorize(
                    &db,
                    &owner,
                    "device:control",
                    "device",
                    "locked_use",
                    session,
                    "new-request"
                )
                .unwrap());
                let pending = super::super::PendingConsent {
                    request_id: "new-request".into(),
                    session_id: session.into(),
                    engine_session_id: Some("new-engine".into()),
                    app: "device:control".into(),
                    identity_digest: "device".into(),
                    capability: "locked_use".into(),
                    tool_name: "computer_locked_use".into(),
                    input_digest: "enable-input".into(),
                    target: None,
                    app_icon: None,
                    owner: owner.clone(),
                };
                assert!(super::super::consent::needs_approval(&pending, &persisted));
            }
        }
        assert_eq!(
            grants(&db, &owner).unwrap().len(),
            2,
            "legacy rows are harmless without rewriting storage"
        );
    }
}

#[cfg(test)]
mod input_tests {
    use super::*;
    #[test]
    fn old_configuration_defaults_to_background_without_erasing_permissions() {
        let value: Instance = serde_json::from_str(r#"{"installed":true,"enabled":true,"revision":7,"microphone":true,"system_audio":false,"locked_use":false}"#).unwrap();
        assert_eq!(
            value.input_mode,
            agistack_adapters_cua::CuaInputMode::Background
        );
        assert!(value.microphone);
        assert_eq!(value.revision, 7);
    }
}
