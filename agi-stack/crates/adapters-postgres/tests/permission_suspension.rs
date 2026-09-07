//! Real PostgreSQL producer transactions, isolated in disposable schemas.
#[path = "cron_hitl_admission/support.rs"]
#[allow(dead_code)]
mod admission_support;
#[path = "automation_permission/support.rs"]
#[allow(dead_code)]
mod support;

use agistack_adapters_postgres::{
    AutomationPayload, AutomationPermissionOutcome as Outcome,
    AutomationPermissionSuspensionCommand as Command, AutomationRunContext, AutomationRunLease,
    AutomationRunStatus, PgAutomationPermissionStore as Store,
};
use agistack_core::{
    automation_permission::{HostPermissionBinding, PermissionInvocationProposal},
    HitlKind, HitlRequest, Role, SessionState, SessionStatus, TranscriptEntry,
};
use chrono::{Duration, Utc};
use serde_json::json;
use sha2::{Digest, Sha256};
use support::Fixture;

async fn setup(f: &Fixture) -> (AutomationRunLease, Command) {
    support::seed(f).await;
    for sql in [
        "DELETE FROM hitl_requests",
        "DELETE FROM agistack_checkpoints",
        "ALTER TABLE hitl_requests ADD COLUMN question text, ADD COLUMN context jsonb",
        "UPDATE agistack_cron_operations SET actor_api_key_id='actor-key'",
    ] {
        sqlx::query(sql).execute(&f.pool).await.unwrap();
    }
    let now = Utc::now();
    let lease = AutomationRunLease {
        context: AutomationRunContext {
            tenant_id: "tenant".into(),
            project_id: "project".into(),
            job_id: "job".into(),
            run_id: "run".into(),
            runtime_execution_id: "run".into(),
            conversation_id: "conversation".into(),
            actor_user_id: "actor".into(),
            actor_api_key_id: Some("actor-key".into()),
            payload: AutomationPayload::AgentTurn {
                message: "test".into(),
            },
            timeout_seconds: 300,
            status: AutomationRunStatus::Running,
        },
        runtime_revision: 7,
        lease_owner: "producer".into(),
        lease_token: "producer-token".into(),
        lease_expires_at: now + Duration::minutes(2),
        deadline_at: now + Duration::minutes(5),
    };
    sqlx::query("UPDATE cron_job_runs SET status='running',runtime_lease_owner='producer',runtime_lease_token='producer-token',runtime_lease_expires_at=$1,deadline_at=$2")
        .bind(lease.lease_expires_at).bind(lease.deadline_at).execute(&f.pool).await.unwrap();
    let input = json!({"path":"file-1","text":"new"});
    let mut request = HitlRequest::new("request", HitlKind::Permission, "Write file?")
        .with_decision(support::intent(f).decision);
    request.permission_invocation = Some(Box::new(PermissionInvocationProposal {
        tool: "write".into(),
        input: input.clone(),
    }));
    let mut state = SessionState::new("run", "test", Some("project"));
    state.round = 2;
    state.push_unique(TranscriptEntry::new(0, Role::Observation, "prior work"));
    state
        .completed_tool_calls
        .push(agistack_core::agent::types::CompletedCall {
            round: 1,
            tool: "pure".into(),
            input_json: "{}".into(),
            output_json: "observed".into(),
            failed: false,
        });
    state.push_unique(TranscriptEntry::new(
        2,
        Role::Action,
        "request_human[Permission] Write file?",
    ));
    state.pending_hitl = Some(request);
    state.status = SessionStatus::AwaitingInput;
    let binding = HostPermissionBinding::from_host_observation(
        "invocation".into(),
        "write".into(),
        "1.2.0".into(),
        format!("{:x}", Sha256::digest(serde_jcs::to_vec(&input).unwrap())),
    )
    .unwrap();
    (
        lease,
        Command {
            intent_id: "intent".into(),
            binding,
            state,
            expires_at: now + Duration::minutes(4),
        },
    )
}

async fn assert_empty(f: &Fixture) {
    for table in [
        "hitl_requests",
        "agistack_checkpoints",
        "agistack_automation_permission_intents",
    ] {
        let n: i64 = sqlx::query_scalar(&format!("SELECT count(*) FROM {table}"))
            .fetch_one(&f.pool)
            .await
            .unwrap();
        assert_eq!(n, 0, "{table}");
    }
    let status: String = sqlx::query_scalar("SELECT status FROM cron_job_runs")
        .fetch_one(&f.pool)
        .await
        .unwrap();
    assert_eq!(status, "running");
}

#[tokio::test]
async fn commits_exact_checkpoint_hitl_intent_and_park_without_dispatch() {
    let Some(f) = Fixture::open().await else {
        return;
    };
    let (lease, command) = setup(&f).await;
    assert_eq!(
        Store::new(f.pool.clone())
            .suspend_with_lease(&lease, &command, Utc::now())
            .await
            .unwrap(),
        Outcome::Applied
    );
    assert_eq!(
        f.checkpoint().await,
        serde_json::to_value(&command.state).unwrap()
    );
    let run: (String, i64, Option<String>, Option<String>) = sqlx::query_as(
        "SELECT status,runtime_revision,runtime_lease_owner,runtime_lease_token FROM cron_job_runs",
    )
    .fetch_one(&f.pool)
    .await
    .unwrap();
    assert_eq!(run, ("waiting_human".into(), 7, None, None));
    let intent:(String,String,String)=sqlx::query_as("SELECT actor_user_id,actor_api_key_id,input_sha256 FROM agistack_automation_permission_intents").fetch_one(&f.pool).await.unwrap();
    assert_eq!(
        intent,
        (
            "actor".into(),
            "actor-key".into(),
            command.binding.input_sha256().into()
        )
    );
    let mut answer = support::answer(
        &f,
        agistack_core::automation_permission::PermissionAnswer::AllowOnce,
    );
    answer.responder_user_id = "actor".into();
    assert_eq!(
        Store::new(f.pool.clone())
            .answer(&answer, Utc::now())
            .await
            .unwrap(),
        Outcome::Applied
    );
    assert_eq!(
        f.checkpoint().await,
        serde_json::to_value(&command.state).unwrap()
    );
    f.close().await;
}

#[tokio::test]
async fn stale_lease_revocation_and_changed_inputs_leave_no_partial_effects() {
    for case in 0..8 {
        let Some(f) = Fixture::open().await else {
            return;
        };
        let (mut lease, mut command) = setup(&f).await;
        match case {
            0 => lease.lease_token = "old-token".into(),
            1 => lease.runtime_revision -= 1,
            2 => lease.context.actor_user_id = "responder".into(),
            3 => {
                sqlx::query("UPDATE api_keys SET is_active=false")
                    .execute(&f.pool)
                    .await
                    .unwrap();
            }
            4 => {
                sqlx::query("DELETE FROM user_projects WHERE user_id='actor'")
                    .execute(&f.pool)
                    .await
                    .unwrap();
            }
            5 => {
                command
                    .state
                    .pending_hitl
                    .as_mut()
                    .unwrap()
                    .permission_invocation
                    .as_mut()
                    .unwrap()
                    .input = json!({"different":true})
            }
            6 => lease.context.actor_api_key_id = None,
            _ => {
                sqlx::query("UPDATE agistack_cron_operations SET status='cancelled'")
                    .execute(&f.pool)
                    .await
                    .unwrap();
            }
        }
        assert_eq!(
            Store::new(f.pool.clone())
                .suspend_with_lease(&lease, &command, Utc::now())
                .await
                .unwrap(),
            Outcome::NotAdmitted,
            "case {case}"
        );
        assert_empty(&f).await;
        f.close().await;
    }
}

#[tokio::test]
async fn postwrite_lease_deadline_or_key_expiry_rolls_back_every_effect() {
    for kind in ["lease", "deadline", "key"] {
        let Some(f) = Fixture::open().await else {
            return;
        };
        let (lease, command) = setup(&f).await;
        let update=match kind {
            "lease"=>"UPDATE cron_job_runs SET runtime_lease_expires_at=clock_timestamp()+interval '200 milliseconds'",
            "deadline"=>"UPDATE cron_job_runs SET deadline_at=clock_timestamp()+interval '200 milliseconds'",
            _=>"UPDATE api_keys SET expires_at=clock_timestamp()+interval '200 milliseconds'",
        };
        sqlx::query(update).execute(&f.pool).await.unwrap();
        sqlx::raw_sql("CREATE FUNCTION producer_delay() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(0.35); RETURN NEW; END $$;
            CREATE TRIGGER producer_delay AFTER UPDATE OF status ON cron_job_runs FOR EACH ROW EXECUTE FUNCTION producer_delay();")
            .execute(&f.pool).await.unwrap();
        assert_eq!(
            Store::new(f.pool.clone())
                .suspend_with_lease(&lease, &command, Utc::now())
                .await
                .unwrap(),
            Outcome::NotAdmitted,
            "{kind}"
        );
        assert_empty(&f).await;
        f.close().await;
    }
}

#[tokio::test]
async fn cancelled_transaction_rolls_back_even_after_hitl_and_intent_inserts() {
    let Some(f) = Fixture::open().await else {
        return;
    };
    let (lease, command) = setup(&f).await;
    let lock_id = i64::from(std::process::id()) + 9_000_000;
    let mut blocker = f.pool.begin().await.unwrap();
    sqlx::query("SELECT pg_advisory_xact_lock($1)")
        .bind(lock_id)
        .execute(&mut *blocker)
        .await
        .unwrap();
    sqlx::raw_sql(&format!("CREATE FUNCTION producer_block() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_xact_lock({lock_id}); RETURN NEW; END $$;
        CREATE TRIGGER producer_block AFTER INSERT ON agistack_automation_permission_intents FOR EACH ROW EXECUTE FUNCTION producer_block();"))
        .execute(&f.pool).await.unwrap();
    let pool = f.pool.clone();
    let task = tokio::spawn(async move {
        Store::new(pool)
            .suspend_with_lease(&lease, &command, Utc::now())
            .await
    });
    tokio::time::timeout(std::time::Duration::from_secs(5),async {
        loop {
            let waiting:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND objid=$1 AND NOT granted)")
                .bind(lock_id as i32).fetch_one(&f.pool).await.unwrap();
            if waiting { break; }
            tokio::task::yield_now().await;
        }
    }).await.unwrap();
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    blocker.commit().await.unwrap();
    // A locked read waits until the cancelled transaction has actually settled.
    sqlx::query("SELECT id FROM cron_job_runs FOR UPDATE")
        .execute(&f.pool)
        .await
        .unwrap();
    assert_empty(&f).await;
    f.close().await;
}

#[tokio::test]
async fn ordinary_admission_cannot_resume_a_bound_permission_even_with_legacy_answer_metadata() {
    let Some(f) = Fixture::open().await else {
        return;
    };
    let (lease, command) = setup(&f).await;
    assert_eq!(
        Store::new(f.pool.clone())
            .suspend_with_lease(&lease, &command, Utc::now())
            .await
            .unwrap(),
        Outcome::Applied
    );
    sqlx::query("UPDATE hitl_requests SET status='answered',answered_at=clock_timestamp(),response_metadata='{\"resume_answer\":\"allow_once\"}'")
        .execute(&f.pool).await.unwrap();
    let before = f.checkpoint().await;
    assert!(
        agistack_adapters_postgres::PgAutomationHitlAdmission::new(f.pool.clone())
            .admit(&f.command(), Utc::now())
            .await
            .is_err()
    );
    assert_eq!(before, f.checkpoint().await);
    let status: String = sqlx::query_scalar("SELECT status FROM cron_job_runs")
        .fetch_one(&f.pool)
        .await
        .unwrap();
    assert_eq!(status, "waiting_human");
    f.close().await;
}

#[tokio::test]
async fn request_collision_or_checkpoint_write_failure_cannot_leave_an_intent() {
    for collision in [true, false] {
        let Some(f) = Fixture::open().await else {
            return;
        };
        let (lease, command) = setup(&f).await;
        if collision {
            sqlx::query("INSERT INTO hitl_requests (id,request_type,tenant_id,project_id,conversation_id,status,expires_at)
                VALUES ('request','clarification','other','other','other','pending',$1)")
                .bind(lease.deadline_at).execute(&f.pool).await.unwrap();
        } else {
            sqlx::raw_sql("CREATE FUNCTION reject_checkpoint() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture failure'; END $$;
                CREATE TRIGGER reject_checkpoint BEFORE INSERT ON agistack_checkpoints FOR EACH ROW EXECUTE FUNCTION reject_checkpoint();")
                .execute(&f.pool).await.unwrap();
        }
        let result = Store::new(f.pool.clone())
            .suspend_with_lease(&lease, &command, Utc::now())
            .await;
        if collision {
            assert_eq!(result.unwrap(), Outcome::NotAdmitted);
            let scope: String = sqlx::query_scalar("SELECT tenant_id FROM hitl_requests")
                .fetch_one(&f.pool)
                .await
                .unwrap();
            assert_eq!(scope, "other");
            sqlx::query("DELETE FROM hitl_requests")
                .execute(&f.pool)
                .await
                .unwrap();
        } else {
            assert!(result.is_err());
        }
        assert_empty(&f).await;
        f.close().await;
    }
}
