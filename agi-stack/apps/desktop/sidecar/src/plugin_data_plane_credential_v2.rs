//! Dedicated application-vault credential for protocol-v2 desktop data-plane transport.

use std::{
    fmt,
    sync::{Arc, Mutex, MutexGuard},
};

use serde::{Deserialize, Serialize};
use url::Url;
use zeroize::{Zeroize, Zeroizing};

use crate::application_vault::ApplicationCredentialVault;

pub(crate) const DESKTOP_PLUGIN_DATA_PLANE_ID_V2: &str = "desktop-sidecar-v2";
const RECORD_VERSION_V2: u16 = 2;
const VAULT_KEY_V2: &str = "plugin-data-plane.desktop-sidecar-v2.v2";
const CREDENTIAL_PREFIX_V2: &str = "ms_dp_";
const CREDENTIAL_HEX_LENGTH_V2: usize = 64;

#[derive(Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PluginDataPlaneCredentialRecordV2 {
    pub(crate) version: u16,
    pub(crate) api_base_url: String,
    pub(crate) data_plane_id: String,
    pub(crate) credential: String,
    pub(crate) ack_participation: bool,
}

impl fmt::Debug for PluginDataPlaneCredentialRecordV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PluginDataPlaneCredentialRecordV2")
            .field("version", &self.version)
            .field("api_base_url", &"[REDACTED]")
            .field("data_plane_id", &self.data_plane_id)
            .field("credential", &"[REDACTED]")
            .field("ack_participation", &self.ack_participation)
            .finish()
    }
}

impl Drop for PluginDataPlaneCredentialRecordV2 {
    fn drop(&mut self) {
        self.credential.zeroize();
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum PluginDataPlaneCredentialStoreErrorV2 {
    Unavailable,
}

pub(crate) trait PluginDataPlaneCredentialStoreV2: Send + Sync {
    fn save_raw(&self, value: &str) -> Result<(), PluginDataPlaneCredentialStoreErrorV2>;
    fn load_raw(&self) -> Result<Option<String>, PluginDataPlaneCredentialStoreErrorV2>;
    fn clear_raw(&self) -> Result<(), PluginDataPlaneCredentialStoreErrorV2>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum PluginDataPlaneCredentialBrokerErrorV2 {
    InvalidRecord,
    UnsupportedVersion,
    CorruptRecord,
    StorageUnavailable,
}

impl fmt::Display for PluginDataPlaneCredentialBrokerErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidRecord => {
                formatter.write_str("plugin data-plane credential record is invalid")
            }
            Self::UnsupportedVersion => {
                formatter.write_str("plugin data-plane credential record version is unsupported")
            }
            Self::CorruptRecord => {
                formatter.write_str("plugin data-plane credential record is corrupt")
            }
            Self::StorageUnavailable => {
                formatter.write_str("plugin data-plane credential storage is unavailable")
            }
        }
    }
}

#[derive(Clone)]
pub(crate) struct PluginDataPlaneCredentialBrokerV2 {
    store: Arc<dyn PluginDataPlaneCredentialStoreV2>,
    operations: Arc<Mutex<()>>,
}

impl PluginDataPlaneCredentialBrokerV2 {
    pub(crate) fn new(store: Arc<dyn PluginDataPlaneCredentialStoreV2>) -> Self {
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
        record: &PluginDataPlaneCredentialRecordV2,
    ) -> Result<(), PluginDataPlaneCredentialBrokerErrorV2> {
        let _operation = self.lock_operations()?;
        validate_record_v2(record)?;
        let serialized = Zeroizing::new(
            serde_json::to_string(record)
                .map_err(|_| PluginDataPlaneCredentialBrokerErrorV2::InvalidRecord)?,
        );
        self.store
            .save_raw(serialized.as_str())
            .map_err(map_store_error_v2)
    }

    pub(crate) fn load(
        &self,
    ) -> Result<Option<PluginDataPlaneCredentialRecordV2>, PluginDataPlaneCredentialBrokerErrorV2>
    {
        let _operation = self.lock_operations()?;
        let Some(serialized) = self.store.load_raw().map_err(map_store_error_v2)? else {
            return Ok(None);
        };
        let serialized = Zeroizing::new(serialized);
        let record =
            match serde_json::from_str::<PluginDataPlaneCredentialRecordV2>(serialized.as_str()) {
                Ok(record) => record,
                Err(_) => {
                    return self
                        .discard_invalid(PluginDataPlaneCredentialBrokerErrorV2::CorruptRecord)
                }
            };
        if let Err(error) = validate_record_v2(&record) {
            return self.discard_invalid(error);
        }
        Ok(Some(record))
    }

    pub(crate) fn clear(&self) -> Result<(), PluginDataPlaneCredentialBrokerErrorV2> {
        let _operation = self.lock_operations()?;
        self.store.clear_raw().map_err(map_store_error_v2)
    }

    fn discard_invalid<T>(
        &self,
        error: PluginDataPlaneCredentialBrokerErrorV2,
    ) -> Result<T, PluginDataPlaneCredentialBrokerErrorV2> {
        self.store.clear_raw().map_err(map_store_error_v2)?;
        Err(error)
    }

    fn lock_operations(
        &self,
    ) -> Result<MutexGuard<'_, ()>, PluginDataPlaneCredentialBrokerErrorV2> {
        self.operations
            .lock()
            .map_err(|_| PluginDataPlaneCredentialBrokerErrorV2::StorageUnavailable)
    }
}

fn validate_record_v2(
    record: &PluginDataPlaneCredentialRecordV2,
) -> Result<(), PluginDataPlaneCredentialBrokerErrorV2> {
    if record.version != RECORD_VERSION_V2 {
        return Err(PluginDataPlaneCredentialBrokerErrorV2::UnsupportedVersion);
    }
    if record.data_plane_id != DESKTOP_PLUGIN_DATA_PLANE_ID_V2
        || !credential_is_valid_v2(&record.credential)
        || validate_base_url_v2(&record.api_base_url).is_err()
    {
        return Err(PluginDataPlaneCredentialBrokerErrorV2::InvalidRecord);
    }
    Ok(())
}

pub(crate) fn validate_base_url_v2(value: &str) -> Result<Url, ()> {
    let url = Url::parse(value).map_err(|_| ())?;
    let loopback = matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "::1"));
    if (url.scheme() != "https" && !(url.scheme() == "http" && loopback))
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(());
    }
    Ok(url)
}

fn credential_is_valid_v2(value: &str) -> bool {
    let Some(hex) = value.strip_prefix(CREDENTIAL_PREFIX_V2) else {
        return false;
    };
    hex.len() == CREDENTIAL_HEX_LENGTH_V2
        && hex
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn map_store_error_v2(
    _error: PluginDataPlaneCredentialStoreErrorV2,
) -> PluginDataPlaneCredentialBrokerErrorV2 {
    PluginDataPlaneCredentialBrokerErrorV2::StorageUnavailable
}

impl PluginDataPlaneCredentialStoreV2 for ApplicationCredentialVault {
    fn save_raw(&self, value: &str) -> Result<(), PluginDataPlaneCredentialStoreErrorV2> {
        self.put(VAULT_KEY_V2, value)
            .map_err(|_| PluginDataPlaneCredentialStoreErrorV2::Unavailable)
    }

    fn load_raw(&self) -> Result<Option<String>, PluginDataPlaneCredentialStoreErrorV2> {
        self.get(VAULT_KEY_V2)
            .map_err(|_| PluginDataPlaneCredentialStoreErrorV2::Unavailable)
    }

    fn clear_raw(&self) -> Result<(), PluginDataPlaneCredentialStoreErrorV2> {
        self.clear(VAULT_KEY_V2)
            .map_err(|_| PluginDataPlaneCredentialStoreErrorV2::Unavailable)
    }
}

#[cfg(test)]
mod tests {
    use std::{path::PathBuf, sync::Mutex};

    use uuid::Uuid;

    use super::*;

    #[derive(Default)]
    struct InMemoryStoreV2 {
        value: Mutex<Option<String>>,
    }

    impl InMemoryStoreV2 {
        fn replace_raw(&self, value: &str) {
            *self.value.lock().expect("in-memory store lock") = Some(value.to_owned());
        }
    }

    impl PluginDataPlaneCredentialStoreV2 for InMemoryStoreV2 {
        fn save_raw(&self, value: &str) -> Result<(), PluginDataPlaneCredentialStoreErrorV2> {
            *self.value.lock().expect("in-memory store lock") = Some(value.to_owned());
            Ok(())
        }

        fn load_raw(&self) -> Result<Option<String>, PluginDataPlaneCredentialStoreErrorV2> {
            Ok(self.value.lock().expect("in-memory store lock").clone())
        }

        fn clear_raw(&self) -> Result<(), PluginDataPlaneCredentialStoreErrorV2> {
            self.value.lock().expect("in-memory store lock").take();
            Ok(())
        }
    }

    struct TestDirectory(PathBuf);

    impl TestDirectory {
        fn new() -> Self {
            Self(std::env::temp_dir().join(format!(
                "agistack-plugin-data-plane-credential-v2-{}",
                Uuid::new_v4()
            )))
        }
    }

    impl Drop for TestDirectory {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn record(credential: &str) -> PluginDataPlaneCredentialRecordV2 {
        PluginDataPlaneCredentialRecordV2 {
            version: 2,
            api_base_url: "https://plugins.example.test/control".to_owned(),
            data_plane_id: DESKTOP_PLUGIN_DATA_PLANE_ID_V2.to_owned(),
            credential: credential.to_owned(),
            ack_participation: false,
        }
    }

    fn credential(fill: char) -> String {
        format!("{CREDENTIAL_PREFIX_V2}{}", fill.to_string().repeat(64))
    }

    #[test]
    fn dedicated_record_round_trips_and_debug_redacts_secrets() {
        let store = Arc::new(InMemoryStoreV2::default());
        let broker = PluginDataPlaneCredentialBrokerV2::new(store);
        let secret = credential('a');
        let input = record(&secret);

        broker.save(&input).expect("save credential");
        let loaded = broker.load().expect("load credential").expect("record");

        assert_eq!(loaded, input);
        let debug = format!("{loaded:?}");
        assert!(!debug.contains(&secret));
        assert!(!debug.contains("plugins.example.test"));
    }

    #[test]
    fn invalid_or_corrupt_records_fail_closed_and_are_discarded() {
        let store = Arc::new(InMemoryStoreV2::default());
        let broker = PluginDataPlaneCredentialBrokerV2::new(store.clone());
        let mut invalid = record(&credential('b'));
        invalid.data_plane_id = "forged-plane".to_owned();
        assert_eq!(
            broker.save(&invalid),
            Err(PluginDataPlaneCredentialBrokerErrorV2::InvalidRecord)
        );

        store.replace_raw("{not-json");
        assert_eq!(
            broker.load(),
            Err(PluginDataPlaneCredentialBrokerErrorV2::CorruptRecord)
        );
        assert!(broker.load().expect("discarded record").is_none());
    }

    #[test]
    fn unsupported_version_and_unsafe_stored_origin_fail_closed_without_secret_disclosure() {
        let store = Arc::new(InMemoryStoreV2::default());
        let broker = PluginDataPlaneCredentialBrokerV2::new(store.clone());
        let secret = credential('d');
        let mut unsupported = record(&secret);
        unsupported.version = 1;
        assert_eq!(
            broker.save(&unsupported),
            Err(PluginDataPlaneCredentialBrokerErrorV2::UnsupportedVersion)
        );

        store.replace_raw(
            &serde_json::json!({
                "version": 2,
                "api_base_url": "http://plugins.example.test/control",
                "data_plane_id": DESKTOP_PLUGIN_DATA_PLANE_ID_V2,
                "credential": secret.clone(),
                "ack_participation": false,
            })
            .to_string(),
        );
        let error = broker.load().expect_err("unsafe origin must be rejected");

        assert_eq!(error, PluginDataPlaneCredentialBrokerErrorV2::InvalidRecord);
        assert!(!error.to_string().contains(&secret));
        assert!(broker.load().expect("unsafe record discarded").is_none());
    }

    #[test]
    fn native_broker_persists_only_in_the_application_vault() {
        let directory = TestDirectory::new();
        let secret = credential('c');
        let input = record(&secret);
        {
            let vault = ApplicationCredentialVault::open(&directory.0).expect("open vault");
            PluginDataPlaneCredentialBrokerV2::native(vault)
                .save(&input)
                .expect("save credential");
        }

        let reopened = ApplicationCredentialVault::open(&directory.0).expect("reopen vault");
        let broker = PluginDataPlaneCredentialBrokerV2::native(reopened);
        assert_eq!(broker.load().expect("load credential"), Some(input));
        broker.clear().expect("clear credential");
        assert!(broker.load().expect("cleared credential").is_none());
    }
}
