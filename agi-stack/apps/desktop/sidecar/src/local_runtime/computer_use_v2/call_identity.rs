//! Engine-issued execution identity and durable admission before native dispatch.
use super::Owner;
use crate::local_runtime::{
    session_store::DesktopSessionStore, tool_authority::canonical_json_digest,
};
use agistack_core::{
    agent::{tool_policy::ToolPolicyContext, types::MediaAttachment},
    ports::{CoreError, CoreResult, ToolResult},
};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::future::Future;

#[derive(Clone)]
pub(in crate::local_runtime) struct CallIdentity {
    session_id: String,
    round: u64,
    tool: String,
}
impl CallIdentity {
    pub(super) fn engine_session_id(&self) -> &str {
        &self.session_id
    }
}
tokio::task_local! {static IDENTITY:CallIdentity;}
pub(in crate::local_runtime) async fn scope<F: Future>(
    context: &ToolPolicyContext<'_>,
    future: F,
) -> F::Output {
    IDENTITY
        .scope(
            CallIdentity {
                session_id: context.session_id.into(),
                round: context.round,
                tool: context.tool.into(),
            },
            future,
        )
        .await
}
pub(super) fn current(tool: &str) -> CoreResult<CallIdentity> {
    IDENTITY
        .try_with(Clone::clone)
        .ok()
        .filter(|identity| identity.tool == tool)
        .ok_or_else(|| CoreError::Tool("cua_engine_call_identity_required".into()))
}
pub(super) fn initialize(db: &Connection) -> Result<(), String> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS desktop_cua_calls_v2 (
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,device_id TEXT NOT NULL,
        run_id TEXT NOT NULL,engine_session_id TEXT NOT NULL,round INTEGER NOT NULL,tool_name TEXT NOT NULL,
        input_digest TEXT NOT NULL,status TEXT NOT NULL,result_json TEXT);")
        .map_err(|error|error.to_string())
}
pub(super) fn id(owner: &Owner, run_id: &str, identity: &CallIdentity) -> CoreResult<String> {
    canonical_json_digest(&json!({"owner":owner,"run_id":run_id,"engine_session_id":identity.session_id,"round":identity.round}))
        .map(|digest|format!("cua-call-{digest}")).map_err(|error|CoreError::Tool(error.to_string()))
}
pub(super) fn existing(
    db: &Connection,
    id: &str,
    input_digest: &str,
) -> CoreResult<Option<ToolResult>> {
    let row: Option<(String, String, Option<String>)> = db
        .query_row(
            "SELECT input_digest,status,result_json FROM desktop_cua_calls_v2 WHERE id=?1",
            [id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()
        .map_err(|error| CoreError::Storage(error.to_string()))?;
    let Some((prior, status, result)) = row else {
        return Ok(None);
    };
    if prior != input_digest {
        return Err(CoreError::Tool("cua_call_identity_conflict".into()));
    }
    if status == "not_sent" {
        return Ok(None);
    }
    if status != "completed" {
        return Err(CoreError::Tool(json!({"error":"cua_outcome_unknown","call_id":id,"hint":"This exact engine call may already have executed. Observe current application state in a new round before deciding the next action. Never retry the uncertain action automatically."}).to_string()));
    }
    let result: Value = serde_json::from_str(
        &result.ok_or_else(|| CoreError::Storage("cua_completed_result_missing".into()))?,
    )
    .map_err(|_| CoreError::Storage("cua_completed_result_invalid".into()))?;
    let output_json = result["output_json"]
        .as_str()
        .ok_or_else(|| CoreError::Storage("cua_completed_result_invalid".into()))?
        .into();
    let media: Vec<MediaAttachment> = serde_json::from_value(result["media"].clone())
        .map_err(|_| CoreError::Storage("cua_completed_media_invalid".into()))?;
    Ok(Some(ToolResult {
        output_json,
        media,
        control_outcome: serde_json::from_value(result["control_outcome"].clone())
            .map_err(|_| CoreError::Storage("cua_completed_control_invalid".into()))?,
        control_generation: serde_json::from_value(result["control_generation"].clone())
            .map_err(|_| CoreError::Storage("cua_completed_control_invalid".into()))?,
    }))
}
pub(super) fn claim(
    store: &DesktopSessionStore,
    owner: &Owner,
    run_id: &str,
    identity: &CallIdentity,
    id: &str,
    input_digest: &str,
) -> CoreResult<Dispatch> {
    let db = store.connection().map_err(CoreError::Storage)?;
    if existing(&db, id, input_digest)?.is_some() {
        return Err(CoreError::Tool("cua_call_already_completed".into()));
    }
    let changed=db.execute(
        "INSERT INTO desktop_cua_calls_v2 VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,'executing',NULL) ON CONFLICT(id) DO UPDATE SET status='executing',result_json=NULL WHERE desktop_cua_calls_v2.status='not_sent' AND desktop_cua_calls_v2.input_digest=excluded.input_digest",
        params![
            id,
            owner.user_id,
            owner.tenant_id,
            owner.project_id,
            owner.device_id,
            run_id,
            identity.session_id,
            identity.round,
            identity.tool,
            input_digest
        ],
    )
    .map_err(|error| CoreError::Storage(error.to_string()))?;
    if changed != 1 {
        return Err(CoreError::Tool("cua_call_admission_conflict".into()));
    }
    Ok(Dispatch {
        store: store.clone(),
        id: id.into(),
        completed: false,
    })
}
pub(super) struct Dispatch {
    store: DesktopSessionStore,
    id: String,
    completed: bool,
}
impl Dispatch {
    pub(super) fn not_sent(mut self) -> CoreResult<()> {
        let db = self.store.connection().map_err(CoreError::Storage)?;
        let changed=db.execute("UPDATE desktop_cua_calls_v2 SET status='not_sent',result_json=NULL WHERE id=?1 AND status='executing'",[&self.id]).map_err(|error|CoreError::Storage(error.to_string()))?;
        if changed != 1 {
            return Err(CoreError::Storage("cua_call_not_sent_conflict".into()));
        }
        self.completed = true;
        Ok(())
    }
    pub(super) fn complete(mut self, result: &ToolResult) -> CoreResult<()> {
        let raw = json!({"output_json":result.output_json,"media":result.media,"control_outcome":result.control_outcome,"control_generation":result.control_generation}).to_string();
        let db = self.store.connection().map_err(CoreError::Storage)?;
        let changed=db.execute("UPDATE desktop_cua_calls_v2 SET status='completed',result_json=?2 WHERE id=?1 AND status='executing'",params![self.id,raw]).map_err(|error|CoreError::Storage(error.to_string()))?;
        if changed != 1 {
            return Err(CoreError::Storage("cua_call_completion_conflict".into()));
        }
        self.completed = true;
        Ok(())
    }
}
impl Drop for Dispatch {
    fn drop(&mut self) {
        if !self.completed {
            if let Ok(db) = self.store.connection() {
                let _=db.execute("UPDATE desktop_cua_calls_v2 SET status='unknown' WHERE id=?1 AND status='executing'",[&self.id]);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn known_not_sent_releases_only_the_exact_call_without_allowing_changed_arguments() {
        let state = crate::local_runtime::tests::test_state("cua-known-not-sent");
        let owner = super::super::tests::owner(&state);
        let identity = CallIdentity {
            session_id: "engine".into(),
            round: 1,
            tool: "computer_click".into(),
        };
        let id = id(&owner, "run", &identity).unwrap();
        claim(
            &state.session_store,
            &owner,
            "run",
            &identity,
            &id,
            "exact-input",
        )
        .unwrap()
        .not_sent()
        .unwrap();
        assert!(existing(
            &state.session_store.connection().unwrap(),
            &id,
            "exact-input"
        )
        .unwrap()
        .is_none());
        assert!(existing(
            &state.session_store.connection().unwrap(),
            &id,
            "changed-input"
        )
        .is_err());
        drop(
            claim(
                &state.session_store,
                &owner,
                "run",
                &identity,
                &id,
                "exact-input",
            )
            .unwrap(),
        );
        assert!(existing(
            &state.session_store.connection().unwrap(),
            &id,
            "exact-input"
        )
        .unwrap_err()
        .to_string()
        .contains("outcome_unknown"));
    }
    #[test]
    fn uncertain_calls_never_replay_and_different_rounds_dispatch() {
        let state = crate::local_runtime::tests::test_state("cua-round-ledger");
        let owner = super::super::tests::owner(&state);
        let first = CallIdentity {
            session_id: "engine".into(),
            round: 1,
            tool: "computer_click".into(),
        };
        let first_id = id(&owner, "run", &first).unwrap();
        drop(
            claim(
                &state.session_store,
                &owner,
                "run",
                &first,
                &first_id,
                "input",
            )
            .unwrap(),
        );
        assert!(existing(
            &state.session_store.connection().unwrap(),
            &first_id,
            "input"
        )
        .unwrap_err()
        .to_string()
        .contains("outcome_unknown"));
        assert!(existing(
            &state.session_store.connection().unwrap(),
            &first_id,
            "changed-input"
        )
        .unwrap_err()
        .to_string()
        .contains("conflict"));
        let second = CallIdentity { round: 2, ..first };
        let second_id = id(&owner, "run", &second).unwrap();
        let changed_tool = CallIdentity {
            tool: "computer_type_text".into(),
            ..second.clone()
        };
        assert_eq!(id(&owner, "run", &changed_tool).unwrap(), second_id);
        let result = ToolResult {
            control_outcome: None,
            control_generation: None,
            output_json: "observed".into(),
            media: vec![MediaAttachment {
                artifact_path: "/task-owned/image.png".into(),
                mime_type: "image/png".into(),
            }],
        };
        claim(
            &state.session_store,
            &owner,
            "run",
            &second,
            &second_id,
            "input",
        )
        .unwrap()
        .complete(&result)
        .unwrap();
        assert_eq!(
            existing(
                &state.session_store.connection().unwrap(),
                &second_id,
                "input"
            )
            .unwrap(),
            Some(result)
        );
    }
    #[test]
    fn interrupted_executing_call_is_rejected_after_store_reopen() {
        let path =
            std::env::temp_dir().join(format!("memstack-cua-call-{}.sqlite", uuid::Uuid::new_v4()));
        let owner = Owner {
            user_id: "user".into(),
            tenant_id: "tenant".into(),
            project_id: "project".into(),
            device_id: "device".into(),
        };
        let identity = CallIdentity {
            session_id: "engine".into(),
            round: 1,
            tool: "computer_click".into(),
        };
        let call_id = id(&owner, "run", &identity).unwrap();
        {
            let store = DesktopSessionStore::open(&path).unwrap();
            let mut dispatch = claim(&store, &owner, "run", &identity, &call_id, "input").unwrap();
            // Simulate process loss after admission, before result persistence.
            dispatch.completed = true;
        }
        let store = DesktopSessionStore::open(&path).unwrap();
        assert!(existing(&store.connection().unwrap(), &call_id, "input")
            .unwrap_err()
            .to_string()
            .contains("outcome_unknown"));
        drop(store);
        std::fs::remove_file(path).unwrap();
    }
}
