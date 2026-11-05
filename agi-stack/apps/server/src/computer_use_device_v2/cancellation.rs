//! Durable chat revocation does not depend on an executor or connected device.
use super::*;
use sqlx::{FromRow, Postgres, Transaction};

#[derive(FromRow)]
pub(super) struct CancelledChatRun {
    pub run_id: String,
    pub user_id: String,
    pub tenant_id: String,
    pub project_id: String,
}

impl authority::PgAuthority {
    pub(super) async fn cancel_chat(
        &self,
        user: &str,
        conversation: &str,
    ) -> CoreResult<Vec<CancelledChatRun>> {
        let Some(pool) = self.pool.as_ref() else {
            return Ok(vec![]);
        };
        let mut transaction = pool.begin().await.map_err(storage)?;
        let rows = sqlx::query_as::<_, CancelledChatRun>(
            "UPDATE agent_run_authorities AS run \
             SET status='cancelled',revision=run.revision+1,completed_at=NOW(),updated_at=NOW(), \
                 error='agent_session_stopped' \
             FROM conversations AS conversation, users AS owner, projects AS project \
             WHERE conversation.id=$2 AND conversation.user_id=$1 \
               AND owner.id=conversation.user_id AND owner.is_active=true \
               AND project.id=conversation.project_id AND project.tenant_id=conversation.tenant_id \
               AND run.conversation_id=conversation.id AND run.tenant_id=conversation.tenant_id \
               AND run.project_id=conversation.project_id AND run.run_kind='chat' \
               AND run.status IN ('queued','running') \
               AND EXISTS(SELECT 1 FROM user_projects WHERE user_id=$1 AND project_id=run.project_id) \
               AND EXISTS(SELECT 1 FROM user_tenants WHERE user_id=$1 AND tenant_id=run.tenant_id) \
             RETURNING run.id AS run_id,conversation.user_id,run.tenant_id,run.project_id",
        )
        .bind(user)
        .bind(conversation)
        .fetch_all(&mut *transaction)
        .await
        .map_err(storage)?;
        for row in &rows {
            cancel_hitl(&mut transaction, row, conversation).await?;
        }
        transaction.commit().await.map_err(storage)?;
        Ok(rows)
    }

    pub(super) async fn fail_chat(
        &self,
        owner: &Owner,
        run: &authority::RunAuthority,
        code: &str,
    ) -> CoreResult<()> {
        if run.run_kind != "chat" {
            return Ok(());
        }
        let Some(pool) = self.pool.as_ref() else {
            return Ok(());
        };
        let mut transaction = pool.begin().await.map_err(storage)?;
        let conversation: Option<String> = sqlx::query_scalar(
            "UPDATE agent_run_authorities AS run \
             SET status='failed',revision=run.revision+1,completed_at=NOW(),updated_at=NOW(),error=$5 \
             FROM conversations AS conversation \
             WHERE run.id=$1 AND run.tenant_id=$2 AND run.project_id=$3 AND run.revision=$4 \
               AND run.run_kind='chat' AND run.status IN ('queued','running') \
               AND conversation.id=run.conversation_id AND conversation.user_id=$6 \
               AND conversation.tenant_id=run.tenant_id AND conversation.project_id=run.project_id \
             RETURNING run.conversation_id",
        )
        .bind(&run.run_id).bind(&owner.tenant_id).bind(&owner.project_id)
        .bind(run.authorization_revision).bind(code).bind(&owner.user_id)
        .fetch_optional(&mut *transaction).await.map_err(storage)?;
        if let Some(conversation) = conversation {
            cancel_hitl(
                &mut transaction,
                &CancelledChatRun {
                    run_id: run.run_id.clone(),
                    user_id: owner.user_id.clone(),
                    tenant_id: owner.tenant_id.clone(),
                    project_id: owner.project_id.clone(),
                },
                &conversation,
            )
            .await?;
        }
        transaction.commit().await.map_err(storage)
    }
}

async fn cancel_hitl(
    transaction: &mut Transaction<'_, Postgres>,
    run: &CancelledChatRun,
    conversation: &str,
) -> CoreResult<()> {
    sqlx::query(
        "UPDATE hitl_requests SET status='cancelled' \
         WHERE conversation_id=$1 AND user_id=$2 AND tenant_id=$3 AND project_id=$4 \
           AND status='pending' AND request_metadata->'native_computer_use'->>'run_id'=$5",
    )
    .bind(conversation)
    .bind(&run.user_id)
    .bind(&run.tenant_id)
    .bind(&run.project_id)
    .bind(&run.run_id)
    .execute(&mut **transaction)
    .await
    .map_err(storage)?;
    Ok(())
}

pub(crate) async fn cancel_owned_chat(
    app: &AppState,
    user: &str,
    conversation: &str,
) -> CoreResult<bool> {
    let rows = match app.computer_use_devices.authority.as_ref() {
        Some(authority) => authority.cancel_owned_chat(user, conversation).await?,
        None => vec![],
    };
    for row in &rows {
        let owner = Owner {
            user_id: row.user_id.clone(),
            tenant_id: row.tenant_id.clone(),
            project_id: row.project_id.clone(),
        };
        app.computer_use_devices.cancel_run(&owner, &row.run_id);
        hitl::cancel_run(&app.computer_use_devices, &owner, &row.run_id);
    }
    Ok(!rows.is_empty())
}

pub(crate) async fn fail_bound(app: &AppState, bound: BoundRun, code: &str) -> CoreResult<()> {
    app.computer_use_devices
        .cancel_run(&bound.owner, &bound.run.run_id);
    hitl::cancel_run(&app.computer_use_devices, &bound.owner, &bound.run.run_id);
    if let Some(authority) = app.computer_use_devices.authority.as_ref() {
        authority.fail(&bound.owner, &bound.run, code).await?;
    }
    Ok(())
}

fn storage(_: sqlx::Error) -> CoreError {
    CoreError::Storage("computer_use_chat_terminal_write_failed".into())
}
