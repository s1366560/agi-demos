//! Application boundary for durable Agent Runtime terminal convergence.

use std::collections::BTreeMap;

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_store::{
    WorkspaceRuntimeTerminalOutcome, WorkspaceRuntimeTerminalScope, WorkspaceRuntimeTerminalStore,
    WorkspaceRuntimeTerminalStoreError, WorkspaceRuntimeTerminalWrite,
};
use serde_json::Value;
use sha2::{Digest, Sha256};
use thiserror::Error;

/// Scoped terminal authority.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceRuntimeTerminalContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
}

/// Untrusted Runtime terminal input.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceRuntimeTerminalInput {
    pub execution_status: String,
    pub terminal_message_id: String,
    pub terminal_event_id: String,
    pub report: Value,
}

/// Durable terminal proof and structural convergence outcome.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceRuntimeTerminalOutcome {
    pub correlation_id: String,
    pub provider_run_id: String,
    pub delivery_request_id: String,
    pub status: String,
    pub outbox_id: String,
    pub terminal_id: Option<String>,
    pub terminal_message_id: String,
    pub terminal_event_id: String,
    pub report: Value,
    pub report_hash: String,
    pub task_status: Option<String>,
    pub attempt_status: Option<String>,
    pub provider_event_hash: Option<String>,
    pub provider_event_ingested: bool,
    pub created: bool,
}

/// Stable public Runtime terminal failure categories.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceRuntimeTerminalErrorKind {
    InvalidRequest,
    NotFound,
    Conflict,
    Unavailable,
}

/// Stable public Runtime terminal error.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceRuntimeTerminalError {
    #[error("invalid Workspace Runtime terminal request")]
    InvalidRequest,
    #[error(transparent)]
    Store(#[from] WorkspaceRuntimeTerminalStoreError),
}

impl PublicWorkspaceRuntimeTerminalError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceRuntimeTerminalErrorKind {
        match self {
            Self::InvalidRequest => PublicWorkspaceRuntimeTerminalErrorKind::InvalidRequest,
            Self::Store(WorkspaceRuntimeTerminalStoreError::NotFound) => {
                PublicWorkspaceRuntimeTerminalErrorKind::NotFound
            }
            Self::Store(WorkspaceRuntimeTerminalStoreError::Conflict) => {
                PublicWorkspaceRuntimeTerminalErrorKind::Conflict
            }
            Self::Store(_) => PublicWorkspaceRuntimeTerminalErrorKind::Unavailable,
        }
    }
}

/// Canonical terminal record/read/Provider-verification use cases.
pub struct PublicWorkspaceRuntimeTerminalService<'a> {
    store: WorkspaceRuntimeTerminalStore<'a>,
}

impl<'a> PublicWorkspaceRuntimeTerminalService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceRuntimeTerminalStore::new(db, flavor),
        }
    }

    /// Atomically persist the terminal and structurally converge linked execution state.
    pub async fn record(
        &self,
        context: &PublicWorkspaceRuntimeTerminalContext,
        correlation_id: &str,
        input: &PublicWorkspaceRuntimeTerminalInput,
    ) -> Result<PublicWorkspaceRuntimeTerminalOutcome, PublicWorkspaceRuntimeTerminalError> {
        let scope = validate_context(context)?;
        validate_identifier(correlation_id)?;
        validate_identifier(input.terminal_message_id.as_str())?;
        validate_identifier(input.terminal_event_id.as_str())?;
        if !input.report.is_object() {
            return Err(PublicWorkspaceRuntimeTerminalError::InvalidRequest);
        }
        let status = canonical_status(input.execution_status.as_str())?;
        let write = WorkspaceRuntimeTerminalWrite {
            execution_status: status.to_string(),
            terminal_message_id: input.terminal_message_id.clone(),
            terminal_event_id: input.terminal_event_id.clone(),
            report_hash: canonical_json_hash(&input.report)?,
            failure_reason: failure_reason(status, &input.report),
            report: input.report.clone(),
        };
        self.store
            .record(&scope, correlation_id, &write)
            .await
            .map(public_outcome)
            .map_err(Into::into)
    }

    /// Read a scoped durable terminal proof.
    pub async fn read(
        &self,
        context: &PublicWorkspaceRuntimeTerminalContext,
        correlation_id: &str,
    ) -> Result<PublicWorkspaceRuntimeTerminalOutcome, PublicWorkspaceRuntimeTerminalError> {
        let scope = validate_context(context)?;
        validate_identifier(correlation_id)?;
        self.store
            .read(&scope, correlation_id)
            .await
            .map(public_outcome)
            .map_err(Into::into)
    }

    /// Verify that a Provider terminal is backed by the exact durable Runtime authority.
    pub async fn verify_provider_terminal(
        &self,
        provider_run_id: &str,
        provider_state: &str,
        terminal_message_id: &str,
        terminal_event_id: &str,
        report: &Value,
        provider_event_hash: &str,
    ) -> Result<PublicWorkspaceRuntimeTerminalOutcome, PublicWorkspaceRuntimeTerminalError> {
        validate_identifier(provider_run_id)?;
        validate_identifier(terminal_message_id)?;
        validate_identifier(terminal_event_id)?;
        validate_sha256(provider_event_hash)?;
        if !report.is_object() {
            return Err(PublicWorkspaceRuntimeTerminalError::InvalidRequest);
        }
        let status = canonical_status(provider_state)?;
        self.store
            .verify_provider_terminal(
                provider_run_id,
                status,
                terminal_message_id,
                terminal_event_id,
                report,
                provider_event_hash,
            )
            .await
            .map(public_outcome)
            .map_err(Into::into)
    }

    /// Persist that Message Flow ingested the exact verified Provider terminal.
    pub async fn mark_provider_event_ingested(
        &self,
        provider_run_id: &str,
        provider_event_hash: &str,
    ) -> Result<(), PublicWorkspaceRuntimeTerminalError> {
        validate_identifier(provider_run_id)?;
        validate_sha256(provider_event_hash)?;
        self.store
            .mark_provider_event_ingested(provider_run_id, provider_event_hash)
            .await
            .map_err(Into::into)
    }
}

fn validate_context(
    context: &PublicWorkspaceRuntimeTerminalContext,
) -> Result<WorkspaceRuntimeTerminalScope, PublicWorkspaceRuntimeTerminalError> {
    for value in [
        context.tenant_id.as_str(),
        context.project_id.as_str(),
        context.workspace_id.as_str(),
    ] {
        validate_identifier(value)?;
    }
    Ok(WorkspaceRuntimeTerminalScope {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
    })
}

fn validate_identifier(value: &str) -> Result<(), PublicWorkspaceRuntimeTerminalError> {
    if value.trim().is_empty() || value.chars().count() > 191 {
        Err(PublicWorkspaceRuntimeTerminalError::InvalidRequest)
    } else {
        Ok(())
    }
}

fn validate_sha256(value: &str) -> Result<(), PublicWorkspaceRuntimeTerminalError> {
    if value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        Ok(())
    } else {
        Err(PublicWorkspaceRuntimeTerminalError::InvalidRequest)
    }
}

fn canonical_status(value: &str) -> Result<&'static str, PublicWorkspaceRuntimeTerminalError> {
    match value {
        "complete" | "completed" | "final" => Ok("completed"),
        "error" | "failed" => Ok("failed"),
        "aborted" => Ok("aborted"),
        _ => Err(PublicWorkspaceRuntimeTerminalError::InvalidRequest),
    }
}

fn failure_reason(status: &str, report: &Value) -> Option<String> {
    if status == "completed" {
        return None;
    }
    let explicit = report
        .get("error_message")
        .and_then(Value::as_str)
        .or_else(|| report.get("stop_reason").and_then(Value::as_str))
        .filter(|value| !value.trim().is_empty());
    let fallback = if status == "aborted" {
        "Agent Runtime aborted execution"
    } else {
        "Agent Runtime failed execution"
    };
    Some(explicit.unwrap_or(fallback).chars().take(1024).collect())
}

fn canonical_json_hash(value: &Value) -> Result<String, PublicWorkspaceRuntimeTerminalError> {
    let bytes = serde_json::to_vec(&canonical_json(value))
        .map_err(|_| PublicWorkspaceRuntimeTerminalError::InvalidRequest)?;
    Ok(hex::encode(Sha256::digest(bytes)))
}

fn canonical_json(value: &Value) -> Value {
    match value {
        Value::Array(items) => Value::Array(items.iter().map(canonical_json).collect()),
        Value::Object(items) => Value::Object(
            items
                .iter()
                .map(|(key, value)| (key.clone(), canonical_json(value)))
                .collect::<BTreeMap<_, _>>()
                .into_iter()
                .collect(),
        ),
        _ => value.clone(),
    }
}

fn public_outcome(
    outcome: WorkspaceRuntimeTerminalOutcome,
) -> PublicWorkspaceRuntimeTerminalOutcome {
    PublicWorkspaceRuntimeTerminalOutcome {
        correlation_id: outcome.correlation_id,
        provider_run_id: outcome.provider_run_id,
        delivery_request_id: outcome.delivery_request_id,
        status: outcome.status,
        outbox_id: outcome.outbox_id,
        terminal_id: outcome.terminal_id,
        terminal_message_id: outcome.terminal_message_id,
        terminal_event_id: outcome.terminal_event_id,
        report: outcome.report,
        report_hash: outcome.report_hash,
        task_status: outcome.task_status,
        attempt_status: outcome.attempt_status,
        provider_event_hash: outcome.provider_event_hash,
        provider_event_ingested: outcome.provider_event_ingested,
        created: outcome.created,
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn canonical_hash_is_stable_for_object_key_order() {
        let left = json!({"b": 2, "a": {"d": 4, "c": 3}});
        let right = json!({"a": {"c": 3, "d": 4}, "b": 2});

        assert_eq!(
            canonical_json_hash(&left).ok(),
            canonical_json_hash(&right).ok()
        );
    }

    #[test]
    fn terminal_status_is_structurally_bounded() {
        assert_eq!(canonical_status("complete").ok(), Some("completed"));
        assert_eq!(canonical_status("error").ok(), Some("failed"));
        assert!(canonical_status("subjective_guess").is_err());
    }
}
