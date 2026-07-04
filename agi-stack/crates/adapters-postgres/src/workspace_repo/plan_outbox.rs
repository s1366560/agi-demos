use super::*;

impl PgWorkspaceRepository {
    pub async fn enqueue_plan_outbox(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxRecord> {
        sqlx::query(&format!(
            "INSERT INTO workspace_plan_outbox \
                (id, plan_id, workspace_id, event_type, payload_json, status, attempt_count, \
                 max_attempts, lease_owner, lease_expires_at, last_error, next_attempt_at, \
                 processed_at, metadata_json, created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16) \
             RETURNING {PLAN_OUTBOX_COLS}"
        ))
        .bind(&item.id)
        .bind(&item.plan_id)
        .bind(&item.workspace_id)
        .bind(&item.event_type)
        .bind(Json(&item.payload_json))
        .bind(&item.status)
        .bind(item.attempt_count)
        .bind(item.max_attempts)
        .bind(&item.lease_owner)
        .bind(item.lease_expires_at)
        .bind(&item.last_error)
        .bind(item.next_attempt_at)
        .bind(item.processed_at)
        .bind(Json(&item.metadata_json))
        .bind(item.created_at)
        .bind(item.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan_outbox)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("workspace plan outbox insert returned no row".into()))
    }

    pub async fn list_plan_outbox(
        &self,
        plan_id: &str,
        limit: i64,
    ) -> CoreResult<Vec<WorkspacePlanOutboxRecord>> {
        if limit <= 0 {
            return Ok(Vec::new());
        }
        let rows = sqlx::query(&format!(
            "SELECT {PLAN_OUTBOX_COLS} FROM workspace_plan_outbox \
             WHERE plan_id = $1 ORDER BY created_at DESC, id DESC LIMIT $2"
        ))
        .bind(plan_id)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_plan_outbox).collect()
    }

    pub async fn get_plan_outbox(
        &self,
        outbox_id: &str,
    ) -> CoreResult<Option<WorkspacePlanOutboxRecord>> {
        sqlx::query(&format!(
            "SELECT {PLAN_OUTBOX_COLS} FROM workspace_plan_outbox WHERE id = $1"
        ))
        .bind(outbox_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan_outbox)
        .transpose()
    }

    pub async fn claim_due_plan_outbox(
        &self,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<WorkspacePlanOutboxRecord>> {
        if limit <= 0 {
            return Ok(Vec::new());
        }
        let lease_expires_at = add_seconds(now, lease_seconds.max(1));
        let rows = sqlx::query(&format!(
            "WITH due AS ( \
                 SELECT id FROM workspace_plan_outbox \
                 WHERE attempt_count < max_attempts \
                   AND ( \
                     (status IN ('pending', 'failed') \
                      AND (next_attempt_at IS NULL OR next_attempt_at <= $1)) \
                     OR (event_type = 'workspace_agent_mention' \
                         AND status IN ('pending_runtime', 'runtime_response_ready', 'runtime_error_ready') \
                         AND (next_attempt_at IS NULL OR next_attempt_at <= $1)) \
                     OR (status = 'processing' \
                         AND lease_expires_at IS NOT NULL \
                         AND lease_expires_at <= $1) \
                   ) \
                 ORDER BY created_at ASC, id ASC \
                 LIMIT $2 \
                 FOR UPDATE SKIP LOCKED \
             ) \
             UPDATE workspace_plan_outbox AS outbox \
             SET status = 'processing', \
                 attempt_count = outbox.attempt_count + 1, \
                 lease_owner = $3, \
                 lease_expires_at = $4, \
                 next_attempt_at = NULL, \
                 last_error = NULL, \
                 updated_at = $1 \
             FROM due \
             WHERE outbox.id = due.id \
             RETURNING {PLAN_OUTBOX_COLS}"
        ))
        .bind(now)
        .bind(limit)
        .bind(lease_owner)
        .bind(lease_expires_at)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_plan_outbox).collect()
    }

    pub async fn mark_plan_outbox_completed(
        &self,
        outbox_id: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut query = "UPDATE workspace_plan_outbox \
             SET status = 'completed', lease_owner = NULL, lease_expires_at = NULL, \
                 last_error = NULL, next_attempt_at = NULL, processed_at = $2, updated_at = $2 \
             WHERE id = $1 AND status = 'processing'"
            .to_string();
        if lease_owner.is_some() {
            query.push_str(" AND lease_owner = $3");
        }
        let mut query = sqlx::query(&query).bind(outbox_id).bind(now);
        if let Some(owner) = lease_owner {
            query = query.bind(owner);
        }
        let result = query.execute(&self.pool).await.map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn mark_plan_outbox_failed(
        &self,
        outbox_id: &str,
        error_message: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let Some(item) = self.get_plan_outbox(outbox_id).await? else {
            return Ok(false);
        };
        if item.status != "processing" {
            return Ok(false);
        }
        if lease_owner.is_some() && item.lease_owner.as_deref() != lease_owner {
            return Ok(false);
        }
        let (next_status, next_attempt_at) = if item.attempt_count >= item.max_attempts {
            ("dead_letter", None)
        } else {
            let exponent = item.attempt_count.clamp(0, 9) as u32;
            let backoff_seconds = (1_i64 << exponent).min(300);
            ("failed", Some(add_seconds(now, backoff_seconds)))
        };
        let mut query = String::from(
            "UPDATE workspace_plan_outbox \
             SET status = $2, lease_owner = NULL, lease_expires_at = NULL, \
                 last_error = $3, next_attempt_at = $4, updated_at = $5 \
             WHERE id = $1 AND status = 'processing'",
        );
        if lease_owner.is_some() {
            query.push_str(" AND lease_owner = $6");
        }
        let mut query = sqlx::query(&query)
            .bind(outbox_id)
            .bind(next_status)
            .bind(error_message)
            .bind(next_attempt_at)
            .bind(now);
        if let Some(owner) = lease_owner {
            query = query.bind(owner);
        }
        let result = query.execute(&self.pool).await.map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn release_plan_outbox_processing(
        &self,
        outbox_id: &str,
        error_message: Option<&str>,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut query = String::from(
            "UPDATE workspace_plan_outbox \
             SET status = 'pending', lease_owner = NULL, lease_expires_at = NULL, \
                 last_error = $2, next_attempt_at = NULL, \
                 attempt_count = GREATEST(attempt_count - 1, 0), updated_at = $3 \
             WHERE id = $1 AND status = 'processing'",
        );
        if lease_owner.is_some() {
            query.push_str(" AND lease_owner = $4");
        }
        let mut query = sqlx::query(&query)
            .bind(outbox_id)
            .bind(error_message)
            .bind(now);
        if let Some(owner) = lease_owner {
            query = query.bind(owner);
        }
        let result = query.execute(&self.pool).await.map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn park_plan_outbox_processing(
        &self,
        outbox_id: &str,
        status: &str,
        metadata_patch: &Value,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut query = String::from(
            "UPDATE workspace_plan_outbox \
             SET status = $2, lease_owner = NULL, lease_expires_at = NULL, \
                 last_error = NULL, next_attempt_at = NULL, \
                 metadata_json = COALESCE(metadata_json, '{}'::jsonb) || $3, updated_at = $4 \
             WHERE id = $1 AND status = 'processing'",
        );
        if lease_owner.is_some() {
            query.push_str(" AND lease_owner = $5");
        }
        let mut query = sqlx::query(&query)
            .bind(outbox_id)
            .bind(status)
            .bind(Json(metadata_patch))
            .bind(now);
        if let Some(owner) = lease_owner {
            query = query.bind(owner);
        }
        let result = query.execute(&self.pool).await.map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn park_plan_outbox_processing_with_payload_patch(
        &self,
        outbox_id: &str,
        status: &str,
        metadata_patch: &Value,
        payload_patch: &Value,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut query = String::from(
            "UPDATE workspace_plan_outbox \
             SET status = $2, lease_owner = NULL, lease_expires_at = NULL, \
                 last_error = NULL, next_attempt_at = NULL, \
                 payload_json = COALESCE(payload_json, '{}'::jsonb) || $3, \
                 metadata_json = COALESCE(metadata_json, '{}'::jsonb) || $4, updated_at = $5 \
             WHERE id = $1 AND status = 'processing'",
        );
        if lease_owner.is_some() {
            query.push_str(" AND lease_owner = $6");
        }
        let mut query = sqlx::query(&query)
            .bind(outbox_id)
            .bind(status)
            .bind(Json(payload_patch))
            .bind(Json(metadata_patch))
            .bind(now);
        if let Some(owner) = lease_owner {
            query = query.bind(owner);
        }
        let result = query.execute(&self.pool).await.map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn renew_plan_outbox_lease(
        &self,
        outbox_id: &str,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let lease_expires_at = add_seconds(now, lease_seconds.max(1));
        let result = sqlx::query(
            "UPDATE workspace_plan_outbox \
             SET lease_expires_at = $3, updated_at = $4 \
             WHERE id = $1 AND status = 'processing' AND lease_owner = $2",
        )
        .bind(outbox_id)
        .bind(lease_owner)
        .bind(lease_expires_at)
        .bind(now)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn retry_plan_outbox_now(
        &self,
        outbox_id: &str,
        workspace_id: &str,
        actor_id: Option<&str>,
        reason: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePlanOutboxRecord>> {
        let Some(item) = self.get_plan_outbox(outbox_id).await? else {
            return Ok(None);
        };
        if item.workspace_id != workspace_id {
            return Ok(None);
        }
        let delayed_pending = item.status == "pending"
            && item
                .next_attempt_at
                .map(|next_attempt_at| next_attempt_at > now)
                .unwrap_or(false);
        if !matches!(item.status.as_str(), "failed" | "dead_letter") && !delayed_pending {
            return Err(CoreError::Storage(format!(
                "workspace plan outbox item {outbox_id} is not retryable from {}",
                item.status
            )));
        }

        let previous_status = item.status.clone();
        let previous_error = item.last_error.clone();
        let previous_next_attempt_at = item.next_attempt_at.map(|value| value.to_rfc3339());
        let mut metadata = match item.metadata_json {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        metadata.insert(
            "operator_retry".to_string(),
            json!({
                "actor_id": actor_id,
                "reason": reason,
                "retried_at": now.to_rfc3339(),
                "previous_status": previous_status,
                "previous_error": previous_error,
                "previous_next_attempt_at": previous_next_attempt_at,
            }),
        );
        let attempt_count = if previous_status == "dead_letter" {
            0
        } else {
            item.attempt_count
        };
        sqlx::query(&format!(
            "UPDATE workspace_plan_outbox \
             SET status = 'pending', attempt_count = $2, lease_owner = NULL, \
                 lease_expires_at = NULL, last_error = NULL, next_attempt_at = NULL, \
                 processed_at = NULL, metadata_json = $3, updated_at = $4 \
             WHERE id = $1 \
             RETURNING {PLAN_OUTBOX_COLS}"
        ))
        .bind(outbox_id)
        .bind(attempt_count)
        .bind(Json(Value::Object(metadata)))
        .bind(now)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan_outbox)
        .transpose()
    }
}
