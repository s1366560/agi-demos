//! Adapter over Python-owned support ticket tables.
//!
//! Rust owns current-user support ticket list/detail plus the API-v1
//! create/update/close mutation slice.

use sqlx::postgres::PgRow;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const SUPPORT_TICKET_COLS: &str =
    "id, tenant_id, user_id, subject, message, priority, status, created_at, updated_at, resolved_at";

#[derive(Debug, Clone)]
pub struct SupportTicketRecord {
    pub id: String,
    pub tenant_id: Option<String>,
    pub user_id: String,
    pub subject: String,
    pub message: String,
    pub priority: String,
    pub status: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub resolved_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy)]
pub struct SupportTicketListQuery<'a> {
    pub user_id: &'a str,
    pub tenant_id: Option<&'a str>,
    pub status: Option<&'a str>,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone, Copy)]
pub struct CreateSupportTicket<'a> {
    pub id: &'a str,
    pub tenant_id: Option<&'a str>,
    pub user_id: &'a str,
    pub subject: &'a str,
    pub message: &'a str,
    pub priority: &'a str,
}

#[derive(Debug, Clone, Copy)]
pub struct UpdateSupportTicket<'a> {
    pub subject: Option<&'a str>,
    pub message: Option<&'a str>,
    pub priority: Option<&'a str>,
}

#[derive(Debug, Clone)]
pub struct ClosedSupportTicketRecord {
    pub id: String,
    pub status: String,
    pub resolved_at: DateTime<Utc>,
}

pub struct PgSupportRepository {
    pool: PgPool,
}

impl PgSupportRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn user_is_superuser(&self, user_id: &str) -> CoreResult<bool> {
        sqlx::query_as::<_, (Option<bool>,)>("SELECT is_superuser FROM users WHERE id = $1")
            .bind(user_id)
            .fetch_optional(&self.pool)
            .await
            .map(|row| {
                row.and_then(|(is_superuser,)| is_superuser)
                    .unwrap_or(false)
            })
            .map_err(|e| CoreError::Storage(format!("read support user superuser: {e}")))
    }

    pub async fn user_has_tenant_membership(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> CoreResult<bool> {
        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(|e| CoreError::Storage(format!("check support tenant access: {e}")))
    }

    pub async fn list_tickets(
        &self,
        query: SupportTicketListQuery<'_>,
    ) -> CoreResult<(Vec<SupportTicketRecord>, i64)> {
        let total = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM support_tickets \
             WHERE user_id = $1 \
               AND ($2::text IS NULL OR tenant_id = $2) \
               AND ($3::text IS NULL OR status = $3)",
        )
        .bind(query.user_id)
        .bind(query.tenant_id)
        .bind(query.status)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("count support tickets: {e}")))?
        .0;

        let sql = format!(
            "SELECT {SUPPORT_TICKET_COLS} \
             FROM support_tickets \
             WHERE user_id = $1 \
               AND ($2::text IS NULL OR tenant_id = $2) \
               AND ($3::text IS NULL OR status = $3) \
             ORDER BY created_at DESC \
             LIMIT $4 OFFSET $5"
        );
        let rows = sqlx::query(&sql)
            .bind(query.user_id)
            .bind(query.tenant_id)
            .bind(query.status)
            .bind(query.limit)
            .bind(query.offset)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list support tickets: {e}")))?;

        let tickets = rows
            .into_iter()
            .map(|row| support_ticket_from_row(&row))
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read support ticket row: {e}")))?;
        Ok((tickets, total))
    }

    pub async fn get_ticket(
        &self,
        user_id: &str,
        ticket_id: &str,
    ) -> CoreResult<Option<SupportTicketRecord>> {
        let sql = format!(
            "SELECT {SUPPORT_TICKET_COLS} \
             FROM support_tickets \
             WHERE id = $1 AND user_id = $2"
        );
        let Some(row) = sqlx::query(&sql)
            .bind(ticket_id)
            .bind(user_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("get support ticket: {e}")))?
        else {
            return Ok(None);
        };

        support_ticket_from_row(&row)
            .map(Some)
            .map_err(|e| CoreError::Storage(format!("read support ticket row: {e}")))
    }

    pub async fn create_ticket(
        &self,
        ticket: CreateSupportTicket<'_>,
    ) -> CoreResult<SupportTicketRecord> {
        let sql = format!(
            "INSERT INTO support_tickets \
             (id, tenant_id, user_id, subject, message, priority, status, created_at, updated_at) \
             VALUES ($1, $2, $3, $4, $5, $6, 'open', now(), now()) \
             RETURNING {SUPPORT_TICKET_COLS}"
        );
        let row = sqlx::query(&sql)
            .bind(ticket.id)
            .bind(ticket.tenant_id)
            .bind(ticket.user_id)
            .bind(ticket.subject)
            .bind(ticket.message)
            .bind(ticket.priority)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("create support ticket: {e}")))?;

        support_ticket_from_row(&row)
            .map_err(|e| CoreError::Storage(format!("read created support ticket row: {e}")))
    }

    pub async fn update_ticket(
        &self,
        user_id: &str,
        ticket_id: &str,
        update: UpdateSupportTicket<'_>,
    ) -> CoreResult<Option<SupportTicketRecord>> {
        if update.subject.is_none() && update.message.is_none() && update.priority.is_none() {
            return self.get_ticket(user_id, ticket_id).await;
        }

        let sql = format!(
            "UPDATE support_tickets \
             SET subject = COALESCE($3, subject), \
                 message = COALESCE($4, message), \
                 priority = COALESCE($5, priority), \
                 updated_at = now() \
             WHERE id = $1 AND user_id = $2 \
             RETURNING {SUPPORT_TICKET_COLS}"
        );
        let Some(row) = sqlx::query(&sql)
            .bind(ticket_id)
            .bind(user_id)
            .bind(update.subject)
            .bind(update.message)
            .bind(update.priority)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("update support ticket: {e}")))?
        else {
            return Ok(None);
        };

        support_ticket_from_row(&row)
            .map(Some)
            .map_err(|e| CoreError::Storage(format!("read updated support ticket row: {e}")))
    }

    pub async fn close_ticket(
        &self,
        user_id: &str,
        ticket_id: &str,
    ) -> CoreResult<Option<ClosedSupportTicketRecord>> {
        let Some(row) = sqlx::query(
            "UPDATE support_tickets \
             SET status = 'closed', resolved_at = now(), updated_at = now() \
             WHERE id = $1 AND user_id = $2 \
             RETURNING id, status, resolved_at",
        )
        .bind(ticket_id)
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("close support ticket: {e}")))?
        else {
            return Ok(None);
        };

        Ok(Some(ClosedSupportTicketRecord {
            id: row
                .try_get("id")
                .map_err(|e| CoreError::Storage(format!("read closed support ticket row: {e}")))?,
            status: row
                .try_get("status")
                .map_err(|e| CoreError::Storage(format!("read closed support ticket row: {e}")))?,
            resolved_at: row
                .try_get("resolved_at")
                .map_err(|e| CoreError::Storage(format!("read closed support ticket row: {e}")))?,
        }))
    }
}

fn support_ticket_from_row(row: &PgRow) -> Result<SupportTicketRecord, sqlx::Error> {
    Ok(SupportTicketRecord {
        id: row.try_get("id")?,
        tenant_id: row.try_get("tenant_id")?,
        user_id: row.try_get("user_id")?,
        subject: row.try_get("subject")?,
        message: row.try_get("message")?,
        priority: row.try_get("priority")?,
        status: row.try_get("status")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
        resolved_at: row.try_get("resolved_at")?,
    })
}
