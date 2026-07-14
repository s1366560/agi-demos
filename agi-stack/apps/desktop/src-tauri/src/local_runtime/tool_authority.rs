//! Run-scoped authority primitives for local tool execution.
//!
//! This module deliberately has no runtime or persistence dependencies. It defines the durable
//! grant and invocation records that a later integration layer can store transactionally before
//! dispatching a tool. Matching is exact and structural: callers provide the approved run, plan,
//! revision, environment, tool, target, and input; no semantic or keyword-based authorization is
//! performed here.

use std::{collections::BTreeSet, error::Error, fmt};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

const REDACTED_VALUE: &str = "[REDACTED]";

/// Whether a tool is observational or may mutate state.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ToolEffect {
    /// The tool is declared to have no external or durable side effects.
    Read,
    /// The tool may change files, processes, remote systems, or other durable state.
    Mutate,
}

/// Static authority metadata declared by a tool definition.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ToolMetadata {
    /// Stable tool name used in grants and invocation records.
    pub name: String,
    /// Declared read-versus-mutate effect.
    pub effect: ToolEffect,
    /// Exact JSON field names that must be redacted wherever they occur in inputs.
    #[serde(default, skip_serializing_if = "BTreeSet::is_empty")]
    pub sensitive_input_fields: BTreeSet<String>,
}

impl ToolMetadata {
    /// Returns whether the tool requires a consumed permission grant.
    #[must_use]
    pub(crate) fn requires_grant(&self) -> bool {
        self.effect == ToolEffect::Mutate
    }
}

/// Durable lifecycle state for a tool invocation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum InvocationStatus {
    /// Authority has been checked and the invocation is durably prepared.
    Prepared,
    /// Dispatch has started, but no durable outcome has been recorded.
    Executing,
    /// The tool completed and its result was durably recorded.
    Completed,
    /// The tool returned a known failure that was durably recorded.
    Failed,
    /// A crash or disconnect left the external side-effect outcome indeterminate.
    UnknownOutcome,
}

/// A request whose complete binding is matched against a [`PermissionGrant`].
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ToolInvocationRequest {
    /// Authoritative run identifier.
    pub run_id: String,
    /// Exact reviewed plan version identifier.
    pub plan_version_id: String,
    /// Authoritative run revision observed by the caller.
    pub run_revision: u64,
    /// Environment or worktree identifier in which the tool must execute.
    pub environment_id: String,
    /// Stable tool name.
    pub tool_name: String,
    /// Structured target approved for the operation, such as a path or remote resource.
    pub target: Value,
    /// Full structured tool input. Only its digest and redacted form enter invocation records.
    pub input: Value,
}

impl ToolInvocationRequest {
    /// Computes the canonical digest of the full tool input.
    ///
    /// # Errors
    ///
    /// Returns [`AuthorityError::JsonSerialization`] if canonical JSON cannot be serialized.
    pub(crate) fn input_digest(&self) -> Result<String, AuthorityError> {
        canonical_json_digest(&self.input)
    }
}

/// The exact field that failed grant matching.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum GrantField {
    /// Run identifier.
    Run,
    /// Reviewed plan version.
    Plan,
    /// Authoritative run revision.
    Revision,
    /// Execution environment.
    Environment,
    /// Tool name.
    Tool,
    /// Structured target.
    Target,
    /// Canonical input digest.
    InputDigest,
}

/// A durable, bounded authorization for one exact class of tool invocation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PermissionGrant {
    /// Stable grant identifier used by the audit ledger.
    pub grant_id: String,
    /// Authorized run identifier.
    pub run_id: String,
    /// Exact reviewed plan version identifier.
    pub plan_version_id: String,
    /// Exact authorized run revision.
    pub run_revision: u64,
    /// Exact authorized environment identifier.
    pub environment_id: String,
    /// Exact authorized tool name.
    pub tool_name: String,
    /// Exact structured target approved by the human or policy layer.
    pub target: Value,
    /// SHA-256 digest of the canonical approved tool input.
    pub input_digest: String,
    /// Maximum number of successful authorizations permitted.
    pub use_limit: u32,
    /// Number of authorizations already consumed.
    pub uses: u32,
    /// Exclusive Unix-millisecond expiry boundary.
    pub expires_at_ms: i64,
}

/// Evidence that one grant use was consumed for an exact request.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct GrantConsumption {
    /// Grant that authorized the request.
    pub grant_id: String,
    /// One-based use number consumed by this authorization.
    pub use_number: u32,
    /// Remaining permitted uses after this authorization.
    pub remaining_uses: u32,
}

impl PermissionGrant {
    /// Exact-matches and consumes one use of this grant.
    ///
    /// All matching completes before the use counter is changed. The expiry boundary is exclusive:
    /// a grant with `expires_at_ms == now_ms` is expired.
    ///
    /// # Errors
    ///
    /// Returns a structured mismatch, expiry, exhaustion, overflow, or JSON serialization error.
    pub(crate) fn authorize_and_consume(
        &mut self,
        request: &ToolInvocationRequest,
        now_ms: i64,
    ) -> Result<GrantConsumption, AuthorityError> {
        if now_ms >= self.expires_at_ms {
            return Err(AuthorityError::GrantExpired);
        }
        if self.uses >= self.use_limit {
            return Err(AuthorityError::GrantUseLimitExceeded);
        }

        ensure_equal(&self.run_id, &request.run_id, GrantField::Run)?;
        ensure_equal(
            &self.plan_version_id,
            &request.plan_version_id,
            GrantField::Plan,
        )?;
        if self.run_revision != request.run_revision {
            return Err(AuthorityError::GrantMismatch(GrantField::Revision));
        }
        ensure_equal(
            &self.environment_id,
            &request.environment_id,
            GrantField::Environment,
        )?;
        ensure_equal(&self.tool_name, &request.tool_name, GrantField::Tool)?;

        let approved_target = canonical_json_digest(&self.target)?;
        let requested_target = canonical_json_digest(&request.target)?;
        if approved_target != requested_target {
            return Err(AuthorityError::GrantMismatch(GrantField::Target));
        }

        let requested_input_digest = request.input_digest()?;
        if self.input_digest != requested_input_digest {
            return Err(AuthorityError::GrantMismatch(GrantField::InputDigest));
        }

        let next_use = self
            .uses
            .checked_add(1)
            .ok_or(AuthorityError::GrantUseCounterOverflow)?;
        self.uses = next_use;

        Ok(GrantConsumption {
            grant_id: self.grant_id.clone(),
            use_number: next_use,
            remaining_uses: self.use_limit.saturating_sub(next_use),
        })
    }
}

/// Durable audit record for one tool execution attempt.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ToolInvocation {
    /// Stable invocation identifier and idempotency boundary.
    pub invocation_id: String,
    /// Consumed grant identifier for mutating tools.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub grant_id: Option<String>,
    /// Run identifier copied from the authorized request.
    pub run_id: String,
    /// Reviewed plan version copied from the authorized request.
    pub plan_version_id: String,
    /// Run revision copied from the authorized request.
    pub run_revision: u64,
    /// Execution environment copied from the authorized request.
    pub environment_id: String,
    /// Tool name copied from the authorized request.
    pub tool_name: String,
    /// Approved structured target.
    pub target: Value,
    /// Declared tool effect.
    pub effect: ToolEffect,
    /// Canonical input digest used for authority matching and replay detection.
    pub input_digest: String,
    /// Recursively redacted input suitable for the audit ledger.
    pub redacted_input: Value,
    /// Current durable invocation status.
    pub status: InvocationStatus,
    /// Unix-millisecond preparation time.
    pub prepared_at_ms: i64,
    /// Unix-millisecond dispatch time.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub started_at_ms: Option<i64>,
    /// Unix-millisecond terminal-state time.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub finished_at_ms: Option<i64>,
}

impl ToolInvocation {
    /// Builds a prepared audit record from an already authorized request.
    ///
    /// Mutating tools require a consumed grant. Read-only tools may omit it.
    ///
    /// # Errors
    ///
    /// Returns an error for metadata mismatch, a missing mutation grant, or JSON serialization.
    pub(crate) fn prepare(
        invocation_id: String,
        request: &ToolInvocationRequest,
        metadata: &ToolMetadata,
        grant: Option<&GrantConsumption>,
        now_ms: i64,
    ) -> Result<Self, AuthorityError> {
        if metadata.name != request.tool_name {
            return Err(AuthorityError::ToolMetadataMismatch);
        }
        if metadata.requires_grant() && grant.is_none() {
            return Err(AuthorityError::MutationGrantRequired);
        }

        Ok(Self {
            invocation_id,
            grant_id: grant.map(|consumption| consumption.grant_id.clone()),
            run_id: request.run_id.clone(),
            plan_version_id: request.plan_version_id.clone(),
            run_revision: request.run_revision,
            environment_id: request.environment_id.clone(),
            tool_name: request.tool_name.clone(),
            target: request.target.clone(),
            effect: metadata.effect,
            input_digest: request.input_digest()?,
            redacted_input: redact_sensitive_fields(
                &request.input,
                &metadata.sensitive_input_fields,
            ),
            status: InvocationStatus::Prepared,
            prepared_at_ms: now_ms,
            started_at_ms: None,
            finished_at_ms: None,
        })
    }

    /// Transitions a prepared invocation to executing.
    ///
    /// # Errors
    ///
    /// Returns [`AuthorityError::InvalidInvocationTransition`] unless currently prepared.
    pub(crate) fn mark_executing(&mut self, now_ms: i64) -> Result<(), AuthorityError> {
        self.transition(InvocationStatus::Executing, now_ms)
    }

    /// Records a completed terminal result.
    ///
    /// # Errors
    ///
    /// Returns [`AuthorityError::InvalidInvocationTransition`] unless currently executing.
    pub(crate) fn mark_completed(&mut self, now_ms: i64) -> Result<(), AuthorityError> {
        self.transition(InvocationStatus::Completed, now_ms)
    }

    /// Records a known failed terminal result.
    ///
    /// # Errors
    ///
    /// Returns [`AuthorityError::InvalidInvocationTransition`] unless currently executing.
    pub(crate) fn mark_failed(&mut self, now_ms: i64) -> Result<(), AuthorityError> {
        self.transition(InvocationStatus::Failed, now_ms)
    }

    /// Records that a dispatched tool's external outcome cannot be determined safely.
    ///
    /// # Errors
    ///
    /// Returns [`AuthorityError::InvalidInvocationTransition`] unless currently executing.
    pub(crate) fn mark_unknown_outcome(&mut self, now_ms: i64) -> Result<(), AuthorityError> {
        self.transition(InvocationStatus::UnknownOutcome, now_ms)
    }

    fn transition(&mut self, next: InvocationStatus, now_ms: i64) -> Result<(), AuthorityError> {
        let is_valid = matches!(
            (self.status, next),
            (InvocationStatus::Prepared, InvocationStatus::Executing)
                | (InvocationStatus::Executing, InvocationStatus::Completed)
                | (InvocationStatus::Executing, InvocationStatus::Failed)
                | (
                    InvocationStatus::Executing,
                    InvocationStatus::UnknownOutcome
                )
        );
        if !is_valid {
            return Err(AuthorityError::InvalidInvocationTransition {
                from: self.status,
                to: next,
            });
        }

        self.status = next;
        match next {
            InvocationStatus::Executing => self.started_at_ms = Some(now_ms),
            InvocationStatus::Completed
            | InvocationStatus::Failed
            | InvocationStatus::UnknownOutcome => self.finished_at_ms = Some(now_ms),
            InvocationStatus::Prepared => {}
        }
        Ok(())
    }
}

/// Errors produced while matching grants or advancing invocation state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum AuthorityError {
    /// A request field differs from the exact grant binding.
    GrantMismatch(GrantField),
    /// The grant has reached its exclusive expiry boundary.
    GrantExpired,
    /// The grant has no remaining permitted uses.
    GrantUseLimitExceeded,
    /// The persisted use counter cannot be incremented safely.
    GrantUseCounterOverflow,
    /// A mutating invocation was prepared without a consumed grant.
    MutationGrantRequired,
    /// Tool metadata does not describe the requested tool.
    ToolMetadataMismatch,
    /// The requested invocation state transition is not legal.
    InvalidInvocationTransition {
        /// Current persisted state.
        from: InvocationStatus,
        /// Requested next state.
        to: InvocationStatus,
    },
    /// Canonical JSON serialization failed.
    JsonSerialization(String),
}

impl fmt::Display for AuthorityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::GrantMismatch(field) => write!(formatter, "permission grant mismatch: {field:?}"),
            Self::GrantExpired => formatter.write_str("permission grant expired"),
            Self::GrantUseLimitExceeded => {
                formatter.write_str("permission grant use limit exceeded")
            }
            Self::GrantUseCounterOverflow => {
                formatter.write_str("permission grant use counter overflow")
            }
            Self::MutationGrantRequired => {
                formatter.write_str("mutating tool requires a consumed grant")
            }
            Self::ToolMetadataMismatch => {
                formatter.write_str("tool metadata does not match request")
            }
            Self::InvalidInvocationTransition { from, to } => {
                write!(
                    formatter,
                    "invalid invocation transition: {from:?} -> {to:?}"
                )
            }
            Self::JsonSerialization(message) => {
                write!(formatter, "canonical JSON serialization failed: {message}")
            }
        }
    }
}

impl Error for AuthorityError {}

/// Returns a stable SHA-256 digest of canonical compact JSON.
///
/// Object keys are sorted recursively, array order is preserved, and serialization uses
/// `serde_json`'s compact representation. This is deterministic within `serde_json`'s value and
/// number model; it does not claim full RFC 8785 number normalization.
///
/// # Errors
///
/// Returns [`AuthorityError::JsonSerialization`] if the canonical value cannot be serialized.
pub(crate) fn canonical_json_digest(value: &Value) -> Result<String, AuthorityError> {
    let canonical = canonicalize_json(value);
    let bytes = serde_json::to_vec(&canonical)
        .map_err(|error| AuthorityError::JsonSerialization(error.to_string()))?;
    let digest = Sha256::digest(bytes);
    Ok(lower_hex(&digest))
}

/// Recursively redacts values whose exact field names are declared sensitive.
///
/// The explicit set is intentional: tool metadata, rather than a text heuristic, determines what
/// is sensitive. Object and array shape is preserved for audit usability.
#[must_use]
pub(crate) fn redact_sensitive_fields(value: &Value, sensitive_fields: &BTreeSet<String>) -> Value {
    match value {
        Value::Object(object) => {
            let redacted = object.iter().map(|(key, child)| {
                let value = if sensitive_fields.contains(key) {
                    Value::String(REDACTED_VALUE.to_string())
                } else {
                    redact_sensitive_fields(child, sensitive_fields)
                };
                (key.clone(), value)
            });
            Value::Object(redacted.collect())
        }
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| redact_sensitive_fields(item, sensitive_fields))
                .collect(),
        ),
        Value::String(text) => serde_json::from_str::<Value>(text)
            .ok()
            .map(|nested| {
                let redacted = redact_sensitive_fields(&nested, sensitive_fields);
                serde_json::to_string(&redacted).unwrap_or_else(|_| REDACTED_VALUE.to_string())
            })
            .map(Value::String)
            .unwrap_or_else(|| Value::String(text.clone())),
        scalar => scalar.clone(),
    }
}

fn ensure_equal<T: PartialEq>(
    approved: &T,
    requested: &T,
    field: GrantField,
) -> Result<(), AuthorityError> {
    if approved == requested {
        Ok(())
    } else {
        Err(AuthorityError::GrantMismatch(field))
    }
}

fn canonicalize_json(value: &Value) -> Value {
    match value {
        Value::Object(object) => {
            let mut keys: Vec<&String> = object.keys().collect();
            keys.sort_unstable();

            let mut canonical = Map::new();
            for key in keys {
                if let Some(child) = object.get(key) {
                    canonical.insert(key.clone(), canonicalize_json(child));
                }
            }
            Value::Object(canonical)
        }
        Value::Array(items) => Value::Array(items.iter().map(canonicalize_json).collect()),
        scalar => scalar.clone(),
    }
}

fn lower_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";

    let mut encoded = String::with_capacity(bytes.len().saturating_mul(2));
    for byte in bytes {
        encoded.push(char::from(HEX[usize::from(byte >> 4)]));
        encoded.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    encoded
}

#[cfg(test)]
mod tests {
    use super::*;

    const NOW_MS: i64 = 1_720_000_000_000;

    fn request() -> ToolInvocationRequest {
        ToolInvocationRequest {
            run_id: "run-1".to_string(),
            plan_version_id: "plan-v3".to_string(),
            run_revision: 7,
            environment_id: "worktree-9".to_string(),
            tool_name: "write_file".to_string(),
            target: serde_json::json!({"path": "src/main.rs", "workspace": "repo-1"}),
            input: serde_json::json!({"content": "fn main() {}", "path": "src/main.rs"}),
        }
    }

    fn grant(
        request: &ToolInvocationRequest,
        use_limit: u32,
    ) -> Result<PermissionGrant, AuthorityError> {
        Ok(PermissionGrant {
            grant_id: "grant-1".to_string(),
            run_id: request.run_id.clone(),
            plan_version_id: request.plan_version_id.clone(),
            run_revision: request.run_revision,
            environment_id: request.environment_id.clone(),
            tool_name: request.tool_name.clone(),
            target: request.target.clone(),
            input_digest: request.input_digest()?,
            use_limit,
            uses: 0,
            expires_at_ms: NOW_MS + 60_000,
        })
    }

    #[test]
    fn exact_grant_matching_rejects_any_bound_field_change() -> Result<(), AuthorityError> {
        let base = request();
        let mut cases = Vec::new();

        let mut changed = base.clone();
        changed.run_id = "run-2".to_string();
        cases.push((GrantField::Run, changed));

        let mut changed = base.clone();
        changed.plan_version_id = "plan-v4".to_string();
        cases.push((GrantField::Plan, changed));

        let mut changed = base.clone();
        changed.run_revision = 8;
        cases.push((GrantField::Revision, changed));

        let mut changed = base.clone();
        changed.environment_id = "worktree-10".to_string();
        cases.push((GrantField::Environment, changed));

        let mut changed = base.clone();
        changed.tool_name = "bash".to_string();
        cases.push((GrantField::Tool, changed));

        let mut changed = base.clone();
        changed.target = serde_json::json!({"path": "src/lib.rs", "workspace": "repo-1"});
        cases.push((GrantField::Target, changed));

        let mut changed = base.clone();
        changed.input = serde_json::json!({"content": "different", "path": "src/main.rs"});
        cases.push((GrantField::InputDigest, changed));

        for (field, changed_request) in cases {
            let mut permission = grant(&base, 1)?;
            assert_eq!(
                permission.authorize_and_consume(&changed_request, NOW_MS),
                Err(AuthorityError::GrantMismatch(field))
            );
            assert_eq!(permission.uses, 0);
        }
        Ok(())
    }

    #[test]
    fn one_time_grant_is_consumed_exactly_once() -> Result<(), AuthorityError> {
        let request = request();
        let mut permission = grant(&request, 1)?;

        let consumption = permission.authorize_and_consume(&request, NOW_MS)?;

        assert_eq!(consumption.use_number, 1);
        assert_eq!(consumption.remaining_uses, 0);
        assert_eq!(permission.uses, 1);
        assert_eq!(
            permission.authorize_and_consume(&request, NOW_MS),
            Err(AuthorityError::GrantUseLimitExceeded)
        );
        Ok(())
    }

    #[test]
    fn sensitive_fields_are_redacted_recursively() {
        let sensitive_fields = BTreeSet::from([
            "api_key".to_string(),
            "password".to_string(),
            "token".to_string(),
        ]);
        let input = serde_json::json!({
            "api_key": "top-secret",
            "nested": {
                "password": "hidden",
                "safe": "visible",
                "items": [{"token": "also-hidden"}, {"value": 3}]
            }
        });

        let redacted = redact_sensitive_fields(&input, &sensitive_fields);

        assert_eq!(
            redacted,
            serde_json::json!({
                "api_key": "[REDACTED]",
                "nested": {
                    "password": "[REDACTED]",
                    "safe": "visible",
                    "items": [{"token": "[REDACTED]"}, {"value": 3}]
                }
            })
        );
    }

    #[test]
    fn canonical_digest_is_stable_across_object_key_order() -> Result<(), Box<dyn std::error::Error>>
    {
        let first: Value =
            serde_json::from_str(r#"{"z":1,"a":{"second":2,"first":1},"items":[{"b":2,"a":1}]}"#)?;
        let second: Value =
            serde_json::from_str(r#"{"items":[{"a":1,"b":2}],"a":{"first":1,"second":2},"z":1}"#)?;

        assert_eq!(
            canonical_json_digest(&first)?,
            canonical_json_digest(&second)?
        );
        Ok(())
    }
}
