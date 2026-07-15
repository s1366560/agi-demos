//! Native trusted-session credential storage.

use std::{
    fmt,
    sync::{Arc, Mutex, MutexGuard},
};

use serde::{Deserialize, Serialize};
use tauri::State;

const TRUSTED_SESSION_RECORD_VERSION: u16 = 1;
const KEYRING_SERVICE: &str = "ai.memstack.desktop";
const KEYRING_ACCOUNT: &str = "trusted-session.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum TrustedSessionRuntimeMode {
    Cloud,
    Local,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum TrustedSessionCredentialKind {
    CloudBearer,
    LocalSessionReference,
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct TrustedSessionRecord {
    pub(crate) version: u16,
    pub(crate) api_base_url: String,
    pub(crate) runtime_mode: TrustedSessionRuntimeMode,
    pub(crate) credential_kind: TrustedSessionCredentialKind,
    pub(crate) credential: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) expires_at: Option<String>,
}

impl fmt::Debug for TrustedSessionRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("TrustedSessionRecord")
            .field("version", &self.version)
            .field("api_base_url", &"[REDACTED]")
            .field("runtime_mode", &self.runtime_mode)
            .field("credential_kind", &self.credential_kind)
            .field("credential", &"[REDACTED]")
            .field("expires_at", &self.expires_at)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TrustedSessionStoreError {
    Unavailable,
}

pub(crate) trait TrustedSessionStore: Send + Sync {
    fn save_raw(&self, value: &str) -> Result<(), TrustedSessionStoreError>;
    fn load_raw(&self) -> Result<Option<String>, TrustedSessionStoreError>;
    fn clear_raw(&self) -> Result<(), TrustedSessionStoreError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TrustedSessionBrokerError {
    InvalidRecord,
    UnsupportedVersion,
    CorruptRecord,
    StorageUnavailable,
}

impl fmt::Display for TrustedSessionBrokerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidRecord => formatter.write_str("trusted session record is invalid"),
            Self::UnsupportedVersion => {
                formatter.write_str("trusted session record version is unsupported")
            }
            Self::CorruptRecord => formatter.write_str("trusted session record is corrupt"),
            Self::StorageUnavailable => {
                formatter.write_str("trusted session credential storage is unavailable")
            }
        }
    }
}

#[derive(Clone)]
pub(crate) struct TrustedSessionBroker {
    store: Arc<dyn TrustedSessionStore>,
    operations: Arc<Mutex<()>>,
}

impl TrustedSessionBroker {
    pub(crate) fn new(store: Arc<dyn TrustedSessionStore>) -> Self {
        Self {
            store,
            operations: Arc::new(Mutex::new(())),
        }
    }

    pub(crate) fn native() -> Self {
        Self::new(Arc::new(NativeTrustedSessionStore))
    }

    pub(crate) fn save(
        &self,
        record: TrustedSessionRecord,
    ) -> Result<(), TrustedSessionBrokerError> {
        let _operation = self.lock_operations()?;
        validate_record(&record)?;
        let serialized =
            serde_json::to_string(&record).map_err(|_| TrustedSessionBrokerError::InvalidRecord)?;
        self.store.save_raw(&serialized).map_err(map_store_error)
    }

    pub(crate) fn load(&self) -> Result<Option<TrustedSessionRecord>, TrustedSessionBrokerError> {
        let _operation = self.lock_operations()?;
        let Some(serialized) = self.store.load_raw().map_err(map_store_error)? else {
            return Ok(None);
        };
        let record = match serde_json::from_str::<TrustedSessionRecord>(&serialized) {
            Ok(record) => record,
            Err(_) => return self.discard_invalid(TrustedSessionBrokerError::CorruptRecord),
        };
        if let Err(error) = validate_record(&record) {
            return self.discard_invalid(error);
        }
        Ok(Some(record))
    }

    pub(crate) fn clear(&self) -> Result<(), TrustedSessionBrokerError> {
        let _operation = self.lock_operations()?;
        self.store.clear_raw().map_err(map_store_error)
    }

    fn discard_invalid<T>(
        &self,
        error: TrustedSessionBrokerError,
    ) -> Result<T, TrustedSessionBrokerError> {
        self.store.clear_raw().map_err(map_store_error)?;
        Err(error)
    }

    fn lock_operations(&self) -> Result<MutexGuard<'_, ()>, TrustedSessionBrokerError> {
        self.operations
            .lock()
            .map_err(|_| TrustedSessionBrokerError::StorageUnavailable)
    }
}

fn validate_record(record: &TrustedSessionRecord) -> Result<(), TrustedSessionBrokerError> {
    if record.version != TRUSTED_SESSION_RECORD_VERSION {
        return Err(TrustedSessionBrokerError::UnsupportedVersion);
    }
    if record.api_base_url.trim().is_empty()
        || record.credential.trim().is_empty()
        || record
            .expires_at
            .as_ref()
            .is_some_and(|expires_at| expires_at.trim().is_empty())
    {
        return Err(TrustedSessionBrokerError::InvalidRecord);
    }
    let mode_matches_kind = matches!(
        (record.runtime_mode, record.credential_kind),
        (
            TrustedSessionRuntimeMode::Cloud,
            TrustedSessionCredentialKind::CloudBearer
        ) | (
            TrustedSessionRuntimeMode::Local,
            TrustedSessionCredentialKind::LocalSessionReference
        )
    );
    if !mode_matches_kind {
        return Err(TrustedSessionBrokerError::InvalidRecord);
    }
    Ok(())
}

fn map_store_error(_error: TrustedSessionStoreError) -> TrustedSessionBrokerError {
    TrustedSessionBrokerError::StorageUnavailable
}

struct NativeTrustedSessionStore;

impl NativeTrustedSessionStore {
    fn entry() -> Result<keyring::Entry, TrustedSessionStoreError> {
        keyring::Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT)
            .map_err(|_| TrustedSessionStoreError::Unavailable)
    }
}

impl TrustedSessionStore for NativeTrustedSessionStore {
    fn save_raw(&self, value: &str) -> Result<(), TrustedSessionStoreError> {
        Self::entry()?
            .set_password(value)
            .map_err(|_| TrustedSessionStoreError::Unavailable)
    }

    fn load_raw(&self) -> Result<Option<String>, TrustedSessionStoreError> {
        match Self::entry()?.get_password() {
            Ok(value) => Ok(Some(value)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(_) => Err(TrustedSessionStoreError::Unavailable),
        }
    }

    fn clear_raw(&self) -> Result<(), TrustedSessionStoreError> {
        match Self::entry()?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(_) => Err(TrustedSessionStoreError::Unavailable),
        }
    }
}

const BLOCKING_TASK_ERROR: &str = "trusted session credential task failed";

#[tauri::command]
pub(crate) async fn trusted_session_save(
    broker: State<'_, TrustedSessionBroker>,
    input: TrustedSessionRecord,
) -> Result<(), String> {
    let broker = broker.inner().clone();
    tauri::async_runtime::spawn_blocking(move || broker.save(input))
        .await
        .map_err(|_| BLOCKING_TASK_ERROR.to_string())?
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub(crate) async fn trusted_session_load(
    broker: State<'_, TrustedSessionBroker>,
) -> Result<Option<TrustedSessionRecord>, String> {
    let broker = broker.inner().clone();
    tauri::async_runtime::spawn_blocking(move || broker.load())
        .await
        .map_err(|_| BLOCKING_TASK_ERROR.to_string())?
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub(crate) async fn trusted_session_clear(
    broker: State<'_, TrustedSessionBroker>,
) -> Result<(), String> {
    let broker = broker.inner().clone();
    tauri::async_runtime::spawn_blocking(move || broker.clear())
        .await
        .map_err(|_| BLOCKING_TASK_ERROR.to_string())?
        .map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Default)]
    struct InMemoryTrustedSessionStore {
        value: Mutex<Option<String>>,
    }

    impl InMemoryTrustedSessionStore {
        fn replace_raw(&self, value: &str) {
            *self.value.lock().expect("in-memory store lock") = Some(value.to_string());
        }
    }

    impl TrustedSessionStore for InMemoryTrustedSessionStore {
        fn save_raw(&self, value: &str) -> Result<(), TrustedSessionStoreError> {
            *self.value.lock().expect("in-memory store lock") = Some(value.to_string());
            Ok(())
        }

        fn load_raw(&self) -> Result<Option<String>, TrustedSessionStoreError> {
            Ok(self.value.lock().expect("in-memory store lock").clone())
        }

        fn clear_raw(&self) -> Result<(), TrustedSessionStoreError> {
            *self.value.lock().expect("in-memory store lock") = None;
            Ok(())
        }
    }

    fn cloud_record() -> TrustedSessionRecord {
        TrustedSessionRecord {
            version: TRUSTED_SESSION_RECORD_VERSION,
            api_base_url: "https://api.memstack.example/api/v1".to_string(),
            runtime_mode: TrustedSessionRuntimeMode::Cloud,
            credential_kind: TrustedSessionCredentialKind::CloudBearer,
            credential: "secret-cloud-bearer".to_string(),
            expires_at: Some("2026-07-16T00:00:00Z".to_string()),
        }
    }

    #[test]
    fn trusted_session_round_trip_preserves_versioned_record() {
        let store = Arc::new(InMemoryTrustedSessionStore::default());
        let broker = TrustedSessionBroker::new(store);
        let record = cloud_record();

        broker.save(record.clone()).expect("save trusted session");

        assert_eq!(broker.load().expect("load trusted session"), Some(record));
    }

    #[test]
    fn whitespace_only_credentials_are_rejected() {
        let store = Arc::new(InMemoryTrustedSessionStore::default());
        let broker = TrustedSessionBroker::new(store);
        let mut record = cloud_record();
        record.credential = "   ".to_string();

        assert_eq!(
            broker.save(record),
            Err(TrustedSessionBrokerError::InvalidRecord)
        );
    }

    #[test]
    fn corrupt_record_is_cleared_and_reported_without_payload() {
        let store = Arc::new(InMemoryTrustedSessionStore::default());
        store.replace_raw(r#"{"version":1,"credential":"secret-corrupt-value"}"#);
        let broker = TrustedSessionBroker::new(store.clone());

        let error = broker.load().expect_err("corrupt record must fail closed");

        assert_eq!(error, TrustedSessionBrokerError::CorruptRecord);
        assert_eq!(store.load_raw().expect("inspect store"), None);
        assert!(!error.to_string().contains("secret-corrupt-value"));
    }

    #[test]
    fn clear_is_idempotent() {
        let store = Arc::new(InMemoryTrustedSessionStore::default());
        let broker = TrustedSessionBroker::new(store);

        broker.clear().expect("clear missing credential");
        broker.save(cloud_record()).expect("save trusted session");
        broker.clear().expect("clear stored credential");
        broker.clear().expect("clear already removed credential");

        assert_eq!(broker.load().expect("load after clear"), None);
    }

    #[test]
    fn record_debug_redacts_credential() {
        let debug = format!("{:?}", cloud_record());

        assert!(debug.contains("[REDACTED]"));
        assert!(!debug.contains("secret-cloud-bearer"));
        assert!(!debug.contains("api.memstack.example"));
    }

    #[test]
    fn dto_rejects_unknown_fields() {
        let serialized = r#"{
          "version": 1,
          "api_base_url": "https://api.memstack.example/api/v1",
          "runtime_mode": "cloud",
          "credential_kind": "cloud_bearer",
          "credential": "secret-cloud-bearer",
          "expires_at": null,
          "unexpected": true
        }"#;

        assert!(serde_json::from_str::<TrustedSessionRecord>(serialized).is_err());
    }
}
