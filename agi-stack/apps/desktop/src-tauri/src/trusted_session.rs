//! Application-encrypted trusted-session credential storage.

use std::{
    fmt,
    sync::{Arc, Mutex, MutexGuard},
};

use serde::{Deserialize, Serialize};
use tauri::State;

use crate::{application_vault::ApplicationCredentialVault, local_runtime::LocalRuntimeService};

const TRUSTED_SESSION_RECORD_VERSION: u16 = 1;
const TRUSTED_SESSION_VAULT_KEY: &str = "trusted-session.v1";

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

    pub(crate) fn native(vault: ApplicationCredentialVault) -> Self {
        Self::new(Arc::new(vault))
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

impl TrustedSessionStore for ApplicationCredentialVault {
    fn save_raw(&self, value: &str) -> Result<(), TrustedSessionStoreError> {
        self.put(TRUSTED_SESSION_VAULT_KEY, value)
            .map_err(|_| TrustedSessionStoreError::Unavailable)
    }

    fn load_raw(&self) -> Result<Option<String>, TrustedSessionStoreError> {
        self.get(TRUSTED_SESSION_VAULT_KEY)
            .map_err(|_| TrustedSessionStoreError::Unavailable)
    }

    fn clear_raw(&self) -> Result<(), TrustedSessionStoreError> {
        self.clear(TRUSTED_SESSION_VAULT_KEY)
            .map_err(|_| TrustedSessionStoreError::Unavailable)
    }
}

const BLOCKING_TASK_ERROR: &str = "trusted session credential task failed";
const LOCAL_BLOCKING_TASK_ERROR: &str = "local trusted session task failed";

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

fn serialize_local_record(
    record: &TrustedSessionRecord,
) -> Result<String, TrustedSessionBrokerError> {
    validate_record(record)?;
    if !matches!(
        (record.runtime_mode, record.credential_kind),
        (
            TrustedSessionRuntimeMode::Local,
            TrustedSessionCredentialKind::LocalSessionReference
        )
    ) {
        return Err(TrustedSessionBrokerError::InvalidRecord);
    }
    serde_json::to_string(record).map_err(|_| TrustedSessionBrokerError::InvalidRecord)
}

fn deserialize_local_record(
    serialized: &str,
) -> Result<TrustedSessionRecord, TrustedSessionBrokerError> {
    let record = serde_json::from_str::<TrustedSessionRecord>(serialized)
        .map_err(|_| TrustedSessionBrokerError::CorruptRecord)?;
    serialize_local_record(&record)?;
    Ok(record)
}

#[tauri::command]
pub(crate) async fn local_trusted_session_save(
    runtime: State<'_, LocalRuntimeService>,
    input: TrustedSessionRecord,
) -> Result<(), String> {
    let serialized = serialize_local_record(&input).map_err(|error| error.to_string())?;
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || runtime.save_local_trusted_session(&serialized))
        .await
        .map_err(|_| LOCAL_BLOCKING_TASK_ERROR.to_string())?
}

#[tauri::command]
pub(crate) async fn local_trusted_session_load(
    runtime: State<'_, LocalRuntimeService>,
) -> Result<Option<TrustedSessionRecord>, String> {
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let Some(serialized) = runtime.load_local_trusted_session()? else {
            return Ok(None);
        };
        match deserialize_local_record(&serialized) {
            Ok(record) => Ok(Some(record)),
            Err(error) => {
                runtime.clear_local_trusted_session()?;
                Err(error.to_string())
            }
        }
    })
    .await
    .map_err(|_| LOCAL_BLOCKING_TASK_ERROR.to_string())?
}

#[tauri::command]
pub(crate) async fn local_trusted_session_clear(
    runtime: State<'_, LocalRuntimeService>,
) -> Result<(), String> {
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || runtime.clear_local_trusted_session())
        .await
        .map_err(|_| LOCAL_BLOCKING_TASK_ERROR.to_string())?
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

    #[test]
    fn local_record_storage_rejects_cloud_bearers() {
        assert_eq!(
            serialize_local_record(&cloud_record()),
            Err(TrustedSessionBrokerError::InvalidRecord)
        );
    }
}
