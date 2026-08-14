use std::collections::BTreeMap;

use rusqlite::{params, OptionalExtension, Transaction, TransactionBehavior};

use super::{map_store_error, McpStore};
use crate::local_runtime::mcp_supervisor::{
    McpResult, McpScope, McpServerDefinition, McpServerDefinitionInput,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(in crate::local_runtime::mcp_supervisor) enum CredentialStageStatus {
    Pending,
    Ready,
    Active,
    Abandoned,
    Retired,
}

impl CredentialStageStatus {
    fn parse(value: &str) -> Result<Self, String> {
        match value {
            "pending" => Ok(Self::Pending),
            "ready" => Ok(Self::Ready),
            "active" => Ok(Self::Active),
            "abandoned" => Ok(Self::Abandoned),
            "retired" => Ok(Self::Retired),
            _ => Err("stored MCP credential stage status is invalid".to_string()),
        }
    }

    pub(in crate::local_runtime::mcp_supervisor) fn stores_secret(self) -> bool {
        !matches!(self, Self::Retired)
    }
}

pub(in crate::local_runtime::mcp_supervisor) struct CredentialStageReservation {
    pub(in crate::local_runtime::mcp_supervisor) staged_reference: String,
    pub(in crate::local_runtime::mcp_supervisor) status: CredentialStageStatus,
    pub(in crate::local_runtime::mcp_supervisor) duplicate: bool,
}

pub(in crate::local_runtime::mcp_supervisor) struct PendingCredentialCleanup {
    pub(in crate::local_runtime::mcp_supervisor) scope: McpScope,
    pub(in crate::local_runtime::mcp_supervisor) binding_reference: String,
    pub(in crate::local_runtime::mcp_supervisor) cleanup_token: String,
}

impl McpStore {
    #[allow(clippy::too_many_arguments)]
    pub(in crate::local_runtime::mcp_supervisor) fn reserve_credential_stage(
        &self,
        scope: &McpScope,
        provision_idempotency_key: &str,
        mutation_idempotency_key: &str,
        request_hash: &str,
        logical_reference: &str,
        staged_reference: &str,
    ) -> McpResult<CredentialStageReservation> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let transaction = connection
                    .transaction_with_behavior(TransactionBehavior::Immediate)
                    .map_err(|error| error.to_string())?;
                if let Some((
                    stored_mutation_key,
                    stored_hash,
                    stored_logical_reference,
                    stored_staged_reference,
                    stored_status,
                )) = transaction
                    .query_row(
                        "SELECT mutation_idempotency_key, request_hash, logical_reference,
                                staged_reference, status
                         FROM desktop_mcp_credential_stages_v2
                         WHERE tenant_id = ?1 AND project_id = ?2
                           AND provision_idempotency_key = ?3",
                        params![scope.tenant_id, scope.project_id, provision_idempotency_key,],
                        |row| {
                            Ok((
                                row.get::<_, String>(0)?,
                                row.get::<_, String>(1)?,
                                row.get::<_, String>(2)?,
                                row.get::<_, String>(3)?,
                                row.get::<_, String>(4)?,
                            ))
                        },
                    )
                    .optional()
                    .map_err(|error| error.to_string())?
                {
                    if stored_mutation_key != mutation_idempotency_key
                        || stored_hash != request_hash
                        || stored_logical_reference != logical_reference
                        || stored_staged_reference != staged_reference
                    {
                        return Err("idempotency_conflict".to_string());
                    }
                    let status = CredentialStageStatus::parse(&stored_status)?;
                    if status == CredentialStageStatus::Abandoned {
                        transaction
                            .execute(
                                "DELETE FROM desktop_mcp_credential_cleanup_v2
                                 WHERE tenant_id = ?1 AND project_id = ?2
                                   AND binding_reference = ?3",
                                params![scope.tenant_id, scope.project_id, staged_reference],
                            )
                            .map_err(|error| error.to_string())?;
                        let now = chrono::Utc::now().to_rfc3339();
                        transaction
                            .execute(
                                "UPDATE desktop_mcp_credential_stages_v2
                                 SET status = 'pending', updated_at = ?4
                                 WHERE tenant_id = ?1 AND project_id = ?2
                                   AND provision_idempotency_key = ?3",
                                params![
                                    scope.tenant_id,
                                    scope.project_id,
                                    provision_idempotency_key,
                                    now,
                                ],
                            )
                            .map_err(|error| error.to_string())?;
                        transaction.commit().map_err(|error| error.to_string())?;
                        return Ok(CredentialStageReservation {
                            staged_reference: stored_staged_reference,
                            status: CredentialStageStatus::Pending,
                            duplicate: true,
                        });
                    }
                    transaction.commit().map_err(|error| error.to_string())?;
                    return Ok(CredentialStageReservation {
                        staged_reference: stored_staged_reference,
                        status,
                        duplicate: true,
                    });
                }

                let mutation_completed = transaction
                    .query_row(
                        "SELECT 1 FROM desktop_mcp_receipts_v1
                         WHERE tenant_id = ?1 AND project_id = ?2 AND idempotency_key = ?3",
                        params![scope.tenant_id, scope.project_id, mutation_idempotency_key,],
                        |_| Ok(()),
                    )
                    .optional()
                    .map_err(|error| error.to_string())?
                    .is_some();
                if mutation_completed {
                    return Err("idempotency_conflict".to_string());
                }

                let now = chrono::Utc::now().to_rfc3339();
                transaction
                    .execute(
                        "INSERT INTO desktop_mcp_credential_stages_v2(
                           tenant_id, project_id, provision_idempotency_key,
                           mutation_idempotency_key, request_hash, logical_reference,
                           staged_reference, status, server_id, created_at, updated_at
                         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 'pending', NULL, ?8, ?8)",
                        params![
                            scope.tenant_id,
                            scope.project_id,
                            provision_idempotency_key,
                            mutation_idempotency_key,
                            request_hash,
                            logical_reference,
                            staged_reference,
                            now,
                        ],
                    )
                    .map_err(|error| {
                        if error.to_string().contains("UNIQUE constraint failed") {
                            "idempotency_conflict".to_string()
                        } else {
                            error.to_string()
                        }
                    })?;
                transaction.commit().map_err(|error| error.to_string())?;
                Ok(CredentialStageReservation {
                    staged_reference: staged_reference.to_string(),
                    status: CredentialStageStatus::Pending,
                    duplicate: false,
                })
            })
            .map_err(map_store_error)
    }

    pub(in crate::local_runtime::mcp_supervisor) fn mark_credential_stage_ready(
        &self,
        scope: &McpScope,
        provision_idempotency_key: &str,
        request_hash: &str,
    ) -> McpResult<()> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let now = chrono::Utc::now().to_rfc3339();
                let updated = connection
                    .execute(
                        "UPDATE desktop_mcp_credential_stages_v2
                         SET status = CASE status
                               WHEN 'pending' THEN 'ready'
                               WHEN 'abandoned' THEN 'ready'
                               ELSE status
                             END,
                             updated_at = ?5
                         WHERE tenant_id = ?1 AND project_id = ?2
                           AND provision_idempotency_key = ?3 AND request_hash = ?4",
                        params![
                            scope.tenant_id,
                            scope.project_id,
                            provision_idempotency_key,
                            request_hash,
                            now,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
                if updated != 1 {
                    return Err("idempotency_conflict".to_string());
                }
                Ok(())
            })
            .map_err(map_store_error)
    }

    pub(in crate::local_runtime::mcp_supervisor) fn abandon_unbound_credential_stages(
        &self,
    ) -> McpResult<()> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let transaction = connection
                    .transaction_with_behavior(TransactionBehavior::Immediate)
                    .map_err(|error| error.to_string())?;
                let now = chrono::Utc::now().to_rfc3339();
                transaction
                    .execute(
                        "INSERT OR IGNORE INTO desktop_mcp_credential_cleanup_v2(
                           tenant_id, project_id, binding_reference, cleanup_token,
                           attempts, last_error, created_at, updated_at
                         )
                         SELECT tenant_id, project_id, staged_reference,
                                'abandon:' || provision_idempotency_key,
                                0, NULL, ?1, ?1
                         FROM desktop_mcp_credential_stages_v2
                         WHERE status IN ('pending', 'ready')",
                        params![now],
                    )
                    .map_err(|error| error.to_string())?;
                transaction
                    .execute(
                        "UPDATE desktop_mcp_credential_stages_v2
                         SET status = 'abandoned', server_id = NULL, updated_at = ?1
                         WHERE status IN ('pending', 'ready')",
                        params![now],
                    )
                    .map_err(|error| error.to_string())?;
                transaction.commit().map_err(|error| error.to_string())
            })
            .map_err(map_store_error)
    }

    pub(in crate::local_runtime::mcp_supervisor) fn pending_credential_cleanups(
        &self,
    ) -> McpResult<Vec<PendingCredentialCleanup>> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let mut statement = connection
                    .prepare(
                        "SELECT tenant_id, project_id, binding_reference, cleanup_token
                         FROM desktop_mcp_credential_cleanup_v2
                         ORDER BY created_at, tenant_id, project_id, binding_reference",
                    )
                    .map_err(|error| error.to_string())?;
                let rows = statement
                    .query_map([], |row| {
                        Ok(PendingCredentialCleanup {
                            scope: McpScope {
                                tenant_id: row.get(0)?,
                                project_id: row.get(1)?,
                            },
                            binding_reference: row.get(2)?,
                            cleanup_token: row.get(3)?,
                        })
                    })
                    .map_err(|error| error.to_string())?;
                rows.collect::<rusqlite::Result<Vec<_>>>()
                    .map_err(|error| error.to_string())
            })
            .map_err(map_store_error)
    }

    pub(in crate::local_runtime::mcp_supervisor) fn credential_cleanup_reference_is_live(
        &self,
        cleanup: &PendingCredentialCleanup,
    ) -> McpResult<bool> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let binding_is_live = connection
                    .query_row(
                        "SELECT 1 FROM desktop_mcp_credential_bindings_v1
                         WHERE tenant_id = ?1 AND project_id = ?2 AND binding_reference = ?3",
                        params![
                            cleanup.scope.tenant_id,
                            cleanup.scope.project_id,
                            cleanup.binding_reference,
                        ],
                        |_| Ok(()),
                    )
                    .optional()
                    .map_err(|error| error.to_string())?
                    .is_some();
                if binding_is_live {
                    return Ok(true);
                }
                let stage_is_live = connection
                    .query_row(
                        "SELECT 1 FROM desktop_mcp_credential_stages_v2
                         WHERE tenant_id = ?1 AND project_id = ?2 AND staged_reference = ?3
                           AND status IN ('pending', 'ready', 'active')",
                        params![
                            cleanup.scope.tenant_id,
                            cleanup.scope.project_id,
                            cleanup.binding_reference,
                        ],
                        |_| Ok(()),
                    )
                    .optional()
                    .map_err(|error| error.to_string())?
                    .is_some();
                if stage_is_live {
                    return Ok(true);
                }

                let mut statement = connection
                    .prepare(
                        "SELECT vault_env_refs_json FROM desktop_mcp_servers_v1
                         WHERE tenant_id = ?1 AND project_id = ?2",
                    )
                    .map_err(|error| error.to_string())?;
                let rows = statement
                    .query_map(
                        params![cleanup.scope.tenant_id, cleanup.scope.project_id],
                        |row| row.get::<_, String>(0),
                    )
                    .map_err(|error| error.to_string())?;
                for value in rows {
                    let references: BTreeMap<String, String> =
                        serde_json::from_str(&value.map_err(|error| error.to_string())?)
                            .map_err(|error| error.to_string())?;
                    if references
                        .values()
                        .any(|reference| reference == &cleanup.binding_reference)
                    {
                        return Ok(true);
                    }
                }
                Ok(false)
            })
            .map_err(map_store_error)
    }

    pub(in crate::local_runtime::mcp_supervisor) fn complete_credential_cleanup(
        &self,
        cleanup: &PendingCredentialCleanup,
    ) -> McpResult<()> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                connection
                    .execute(
                        "DELETE FROM desktop_mcp_credential_cleanup_v2
                         WHERE tenant_id = ?1 AND project_id = ?2
                           AND binding_reference = ?3 AND cleanup_token = ?4",
                        params![
                            cleanup.scope.tenant_id,
                            cleanup.scope.project_id,
                            cleanup.binding_reference,
                            cleanup.cleanup_token,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
                Ok(())
            })
            .map_err(map_store_error)
    }

    pub(in crate::local_runtime::mcp_supervisor) fn record_credential_cleanup_failure(
        &self,
        cleanup: &PendingCredentialCleanup,
        reason_code: &str,
    ) -> McpResult<()> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let now = chrono::Utc::now().to_rfc3339();
                connection
                    .execute(
                        "UPDATE desktop_mcp_credential_cleanup_v2
                         SET attempts = attempts + 1, last_error = ?5, updated_at = ?6
                         WHERE tenant_id = ?1 AND project_id = ?2
                           AND binding_reference = ?3 AND cleanup_token = ?4",
                        params![
                            cleanup.scope.tenant_id,
                            cleanup.scope.project_id,
                            cleanup.binding_reference,
                            cleanup.cleanup_token,
                            reason_code,
                            now,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
                Ok(())
            })
            .map_err(map_store_error)
    }

    #[cfg(test)]
    pub(in crate::local_runtime::mcp_supervisor) fn pending_credential_cleanup_count(
        &self,
    ) -> McpResult<usize> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let count = connection
                    .query_row(
                        "SELECT COUNT(*) FROM desktop_mcp_credential_cleanup_v2",
                        [],
                        |row| row.get::<_, i64>(0),
                    )
                    .map_err(|error| error.to_string())?;
                usize::try_from(count).map_err(|_| "cleanup count is invalid".to_string())
            })
            .map_err(map_store_error)
    }

    #[cfg(test)]
    pub(in crate::local_runtime::mcp_supervisor) fn staged_credential_reference(
        &self,
        scope: &McpScope,
        provision_idempotency_key: &str,
    ) -> McpResult<Option<String>> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                connection
                    .query_row(
                        "SELECT staged_reference FROM desktop_mcp_credential_stages_v2
                         WHERE tenant_id = ?1 AND project_id = ?2
                           AND provision_idempotency_key = ?3",
                        params![scope.tenant_id, scope.project_id, provision_idempotency_key,],
                        |row| row.get(0),
                    )
                    .optional()
                    .map_err(|error| error.to_string())
            })
            .map_err(map_store_error)
    }
}

pub(super) fn resolve_credential_bindings(
    transaction: &Transaction<'_>,
    scope: &McpScope,
    mutation_idempotency_key: &str,
    input: &McpServerDefinitionInput,
    current: Option<&McpServerDefinition>,
) -> Result<(BTreeMap<String, String>, Vec<String>), String> {
    let mut resolved = BTreeMap::new();
    let mut activated_stage_references = Vec::new();
    for (name, logical_reference) in &input.vault_env_refs {
        let stage = transaction
            .query_row(
                "SELECT staged_reference, status
                 FROM desktop_mcp_credential_stages_v2
                 WHERE tenant_id = ?1 AND project_id = ?2
                   AND mutation_idempotency_key = ?3 AND logical_reference = ?4",
                params![
                    scope.tenant_id,
                    scope.project_id,
                    mutation_idempotency_key,
                    logical_reference,
                ],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        if let Some((staged_reference, status)) = stage {
            if CredentialStageStatus::parse(&status)? != CredentialStageStatus::Ready {
                return Err("credential_stage_unavailable".to_string());
            }
            activated_stage_references.push(staged_reference.clone());
            resolved.insert(name.clone(), staged_reference);
            continue;
        }

        if let Some(current) = current {
            if let Some(current_reference) = current.vault_env_refs.get(name) {
                if current_reference == logical_reference
                    || active_stage_matches(
                        transaction,
                        scope,
                        &current.id,
                        logical_reference,
                        current_reference,
                    )?
                {
                    resolved.insert(name.clone(), current_reference.clone());
                    continue;
                }
                return Err("credential_stage_mismatch".to_string());
            }
        }
        resolved.insert(name.clone(), logical_reference.clone());
    }

    let unbound_stage_count = transaction
        .query_row(
            "SELECT COUNT(*) FROM desktop_mcp_credential_stages_v2
             WHERE tenant_id = ?1 AND project_id = ?2 AND mutation_idempotency_key = ?3
               AND status IN ('pending', 'ready', 'abandoned')",
            params![scope.tenant_id, scope.project_id, mutation_idempotency_key,],
            |row| row.get::<_, i64>(0),
        )
        .map_err(|error| error.to_string())?;
    if usize::try_from(unbound_stage_count)
        .map_err(|_| "credential stage count is invalid".to_string())?
        != activated_stage_references.len()
    {
        return Err("credential_stage_mismatch".to_string());
    }
    Ok((resolved, activated_stage_references))
}

pub(super) fn activate_credential_stages(
    transaction: &Transaction<'_>,
    scope: &McpScope,
    server_id: &str,
    references: &[String],
    now: &str,
) -> Result<(), String> {
    for reference in references {
        let updated = transaction
            .execute(
                "UPDATE desktop_mcp_credential_stages_v2
                 SET status = 'active', server_id = ?4, updated_at = ?5
                 WHERE tenant_id = ?1 AND project_id = ?2 AND staged_reference = ?3
                   AND status = 'ready'",
                params![scope.tenant_id, scope.project_id, reference, server_id, now],
            )
            .map_err(|error| error.to_string())?;
        if updated != 1 {
            return Err("credential_stage_unavailable".to_string());
        }
    }
    Ok(())
}

pub(super) fn retire_removed_credentials(
    transaction: &Transaction<'_>,
    scope: &McpScope,
    references: &[String],
    cleanup_token: &str,
    now: &str,
) -> Result<(), String> {
    for reference in references {
        transaction
            .execute(
                "DELETE FROM desktop_mcp_credential_bindings_v1
                 WHERE tenant_id = ?1 AND project_id = ?2 AND binding_reference = ?3",
                params![scope.tenant_id, scope.project_id, reference],
            )
            .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "UPDATE desktop_mcp_credential_stages_v2
                 SET status = 'retired', server_id = NULL, updated_at = ?4
                 WHERE tenant_id = ?1 AND project_id = ?2 AND staged_reference = ?3
                   AND status = 'active'",
                params![scope.tenant_id, scope.project_id, reference, now],
            )
            .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "INSERT OR IGNORE INTO desktop_mcp_credential_cleanup_v2(
                   tenant_id, project_id, binding_reference, cleanup_token,
                   attempts, last_error, created_at, updated_at
                 ) VALUES (?1, ?2, ?3, ?4, 0, NULL, ?5, ?5)",
                params![
                    scope.tenant_id,
                    scope.project_id,
                    reference,
                    cleanup_token,
                    now,
                ],
            )
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn active_stage_matches(
    transaction: &Transaction<'_>,
    scope: &McpScope,
    server_id: &str,
    logical_reference: &str,
    staged_reference: &str,
) -> Result<bool, String> {
    transaction
        .query_row(
            "SELECT 1 FROM desktop_mcp_credential_stages_v2
             WHERE tenant_id = ?1 AND project_id = ?2 AND server_id = ?3
               AND logical_reference = ?4 AND staged_reference = ?5 AND status = 'active'",
            params![
                scope.tenant_id,
                scope.project_id,
                server_id,
                logical_reference,
                staged_reference,
            ],
            |_| Ok(()),
        )
        .optional()
        .map(|value| value.is_some())
        .map_err(|error| error.to_string())
}
