//! Application-vault persistence for a pending native OAuth authorization.

use std::{
    fmt,
    sync::{Arc, Mutex, MutexGuard},
};

use serde::{Deserialize, Serialize};
use url::Url;

use crate::application_vault::ApplicationCredentialVault;

const PENDING_ATTEMPT_VERSION: u16 = 1;
const PENDING_ATTEMPT_VAULT_KEY: &str = "oauth-pending-attempt.v1";
const MAX_SAFE_JAVASCRIPT_INTEGER: u64 = 9_007_199_254_740_991;

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct OAuthPendingAttemptRecord {
    pub(crate) version: u16,
    pub(crate) api_base_url: String,
    pub(crate) provider: String,
    pub(crate) resume_route: String,
    pub(crate) state: String,
    pub(crate) expires_at: u64,
}

impl fmt::Debug for OAuthPendingAttemptRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("OAuthPendingAttemptRecord")
            .field("version", &self.version)
            .field("api_base_url", &"[REDACTED]")
            .field("provider", &self.provider)
            .field("resume_route", &self.resume_route)
            .field("state", &"[REDACTED]")
            .field("expires_at", &self.expires_at)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum OAuthPendingAttemptError {
    InvalidRecord,
    UnsupportedVersion,
    CorruptRecord,
    StorageUnavailable,
}

impl fmt::Display for OAuthPendingAttemptError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidRecord => formatter.write_str("OAuth pending attempt record is invalid"),
            Self::UnsupportedVersion => {
                formatter.write_str("OAuth pending attempt version is unsupported")
            }
            Self::CorruptRecord => formatter.write_str("OAuth pending attempt record is corrupt"),
            Self::StorageUnavailable => {
                formatter.write_str("OAuth pending attempt storage is unavailable")
            }
        }
    }
}

#[derive(Clone)]
pub(crate) struct OAuthPendingAttemptBroker {
    vault: ApplicationCredentialVault,
    operations: Arc<Mutex<()>>,
}

impl OAuthPendingAttemptBroker {
    pub(crate) fn new(vault: ApplicationCredentialVault) -> Self {
        Self {
            vault,
            operations: Arc::new(Mutex::new(())),
        }
    }

    pub(crate) fn save(
        &self,
        record: OAuthPendingAttemptRecord,
    ) -> Result<(), OAuthPendingAttemptError> {
        let _operation = self.lock_operations()?;
        validate_record(&record)?;
        let serialized =
            serde_json::to_string(&record).map_err(|_| OAuthPendingAttemptError::InvalidRecord)?;
        self.vault
            .put(PENDING_ATTEMPT_VAULT_KEY, &serialized)
            .map_err(|_| OAuthPendingAttemptError::StorageUnavailable)
    }

    pub(crate) fn load(
        &self,
    ) -> Result<Option<OAuthPendingAttemptRecord>, OAuthPendingAttemptError> {
        let _operation = self.lock_operations()?;
        let Some(serialized) = self
            .vault
            .get(PENDING_ATTEMPT_VAULT_KEY)
            .map_err(|_| OAuthPendingAttemptError::StorageUnavailable)?
        else {
            return Ok(None);
        };
        let record = match serde_json::from_str::<OAuthPendingAttemptRecord>(&serialized) {
            Ok(record) => record,
            Err(_) => return self.discard_invalid(OAuthPendingAttemptError::CorruptRecord),
        };
        if let Err(error) = validate_record(&record) {
            return self.discard_invalid(error);
        }
        Ok(Some(record))
    }

    pub(crate) fn clear(&self) -> Result<(), OAuthPendingAttemptError> {
        let _operation = self.lock_operations()?;
        self.vault
            .clear(PENDING_ATTEMPT_VAULT_KEY)
            .map_err(|_| OAuthPendingAttemptError::StorageUnavailable)
    }

    fn discard_invalid<T>(
        &self,
        error: OAuthPendingAttemptError,
    ) -> Result<T, OAuthPendingAttemptError> {
        self.vault
            .clear(PENDING_ATTEMPT_VAULT_KEY)
            .map_err(|_| OAuthPendingAttemptError::StorageUnavailable)?;
        Err(error)
    }

    fn lock_operations(&self) -> Result<MutexGuard<'_, ()>, OAuthPendingAttemptError> {
        self.operations
            .lock()
            .map_err(|_| OAuthPendingAttemptError::StorageUnavailable)
    }
}

fn validate_record(record: &OAuthPendingAttemptRecord) -> Result<(), OAuthPendingAttemptError> {
    if record.version != PENDING_ATTEMPT_VERSION {
        return Err(OAuthPendingAttemptError::UnsupportedVersion);
    }
    if secure_origin(&record.api_base_url).is_none()
        || !valid_provider(&record.provider)
        || !valid_resume_route(&record.resume_route)
        || !valid_state(&record.state)
        || record.expires_at == 0
        || record.expires_at > MAX_SAFE_JAVASCRIPT_INTEGER
    {
        return Err(OAuthPendingAttemptError::InvalidRecord);
    }
    Ok(())
}

fn secure_origin(value: &str) -> Option<String> {
    if value.is_empty() || value.len() > 2048 || value.trim() != value {
        return None;
    }
    let url = Url::parse(value).ok()?;
    let host = url.host_str()?.to_ascii_lowercase();
    let loopback = matches!(host.as_str(), "localhost" | "127.0.0.1" | "::1" | "[::1]");
    if (url.scheme() != "https" && !(url.scheme() == "http" && loopback))
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.path() != "/"
    {
        return None;
    }
    Some(url.origin().ascii_serialization())
}

fn valid_provider(value: &str) -> bool {
    if value.is_empty() || value.len() > 64 {
        return false;
    }
    let mut characters = value.chars();
    let Some(first) = characters.next() else {
        return false;
    };
    let last = value.chars().next_back().unwrap_or(first);
    (first.is_ascii_lowercase() || first.is_ascii_digit())
        && (last.is_ascii_lowercase() || last.is_ascii_digit())
        && value.chars().all(|character| {
            character.is_ascii_lowercase()
                || character.is_ascii_digit()
                || matches!(character, '_' | '-')
        })
}

fn valid_resume_route(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 2048
        && value.starts_with('/')
        && !value.starts_with("//")
        && !value.chars().any(char::is_control)
}

fn valid_state(value: &str) -> bool {
    value.len() == 43
        && value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '_' | '-'))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record() -> OAuthPendingAttemptRecord {
        OAuthPendingAttemptRecord {
            version: 1,
            api_base_url: "https://api.memstack.example".to_string(),
            provider: "github".to_string(),
            resume_route: "/tenant/tenant-1/overview".to_string(),
            state: "a234567890123456789012345678901234567890123".to_string(),
            expires_at: 1_700_000_600_000,
        }
    }

    #[test]
    fn pending_attempt_survives_vault_reopen_and_can_be_cleared() {
        let root =
            std::env::temp_dir().join(format!("agistack-oauth-pending-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).expect("create test directory");
        let expected = record();
        {
            let vault = ApplicationCredentialVault::open(&root).expect("open first vault");
            OAuthPendingAttemptBroker::new(vault)
                .save(expected.clone())
                .expect("save pending attempt");
        }
        {
            let vault = ApplicationCredentialVault::open(&root).expect("reopen vault");
            let broker = OAuthPendingAttemptBroker::new(vault);
            assert_eq!(broker.load().expect("load pending attempt"), Some(expected));
            broker.clear().expect("clear pending attempt");
            assert_eq!(broker.load().expect("load cleared attempt"), None);
        }
        std::fs::remove_dir_all(root).expect("remove test directory");
    }

    #[test]
    fn invalid_records_are_rejected_without_secret_diagnostics() {
        let root =
            std::env::temp_dir().join(format!("agistack-oauth-invalid-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).expect("create test directory");
        let vault = ApplicationCredentialVault::open(&root).expect("open vault");
        let broker = OAuthPendingAttemptBroker::new(vault);
        let mut invalid = record();
        invalid.state = "secret-state-that-must-not-appear".to_string();

        let error = broker.save(invalid).expect_err("reject invalid state");

        assert_eq!(error, OAuthPendingAttemptError::InvalidRecord);
        assert!(!error.to_string().contains("secret-state"));
        std::fs::remove_dir_all(root).expect("remove test directory");
    }

    #[test]
    fn record_debug_redacts_state_and_origin() {
        let debug = format!("{:?}", record());

        assert!(debug.contains("[REDACTED]"));
        assert!(!debug.contains("api.memstack.example"));
        assert!(!debug.contains("a234567890"));
    }
}
