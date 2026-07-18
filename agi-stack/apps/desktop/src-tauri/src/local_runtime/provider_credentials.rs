//! Operating-system credential storage for local LLM providers.

use std::{
    fmt,
    sync::{Arc, Mutex, MutexGuard},
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const PROVIDER_CREDENTIAL_RECORD_VERSION: u16 = 2;
const KEYRING_SERVICE: &str = "ai.memstack.desktop";
const KEYRING_ACCOUNT_PREFIX: &str = "llm-provider-credential.v2";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum ProviderCredentialStoreError {
    InvalidKey,
    InvalidRecord,
    UnsupportedVersion,
    CorruptRecord,
    Unavailable,
}

impl fmt::Display for ProviderCredentialStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidKey => formatter.write_str("provider credential key is invalid"),
            Self::InvalidRecord => formatter.write_str("provider credential record is invalid"),
            Self::UnsupportedVersion => {
                formatter.write_str("provider credential record version is unsupported")
            }
            Self::CorruptRecord => formatter.write_str("provider credential record is corrupt"),
            Self::Unavailable => {
                formatter.write_str("operating system credential storage is unavailable")
            }
        }
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ProviderCredentialRecord {
    version: u16,
    installation_id: String,
    tenant_id: String,
    provider_id: String,
    provider_revision: u64,
    binding_digest: String,
    credential: String,
}

impl fmt::Debug for ProviderCredentialRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProviderCredentialRecord")
            .field("version", &self.version)
            .field("installation_id", &"[REDACTED]")
            .field("tenant_id", &"[REDACTED]")
            .field("provider_id", &"[REDACTED]")
            .field("provider_revision", &self.provider_revision)
            .field("binding_digest", &"[REDACTED]")
            .field("credential", &"[REDACTED]")
            .finish()
    }
}

pub(super) trait ProviderCredentialStore: Send + Sync {
    fn save(&self, account: &str, value: &str) -> Result<(), ProviderCredentialStoreError>;
    fn load(&self, account: &str) -> Result<Option<String>, ProviderCredentialStoreError>;
    fn clear(&self, account: &str) -> Result<(), ProviderCredentialStoreError>;
}

#[derive(Clone)]
pub(super) struct ProviderCredentialBroker {
    store: Arc<dyn ProviderCredentialStore>,
    installation_id: Arc<str>,
    operations: Arc<Mutex<()>>,
}

impl ProviderCredentialBroker {
    pub(super) fn new(
        store: Arc<dyn ProviderCredentialStore>,
        installation_id: &str,
    ) -> Result<Self, ProviderCredentialStoreError> {
        let installation_id = uuid::Uuid::parse_str(installation_id)
            .map_err(|_| ProviderCredentialStoreError::InvalidKey)?
            .to_string();
        Ok(Self {
            store,
            installation_id: Arc::from(installation_id),
            operations: Arc::new(Mutex::new(())),
        })
    }

    pub(super) fn native(installation_id: &str) -> Result<Self, ProviderCredentialStoreError> {
        Self::new(Arc::new(NativeProviderCredentialStore), installation_id)
    }

    #[cfg(test)]
    pub(super) fn in_memory(installation_id: &str) -> Result<Self, ProviderCredentialStoreError> {
        Self::new(
            Arc::new(InMemoryProviderCredentialStore::default()),
            installation_id,
        )
    }

    pub(super) fn installation_id(&self) -> &str {
        &self.installation_id
    }

    pub(super) fn save(
        &self,
        tenant_id: &str,
        provider_id: &str,
        provider_revision: u64,
        binding_digest: &str,
        credential: &str,
    ) -> Result<(), ProviderCredentialStoreError> {
        let _operation = self.lock_operations()?;
        let account = provider_credential_account(
            &self.installation_id,
            tenant_id,
            provider_id,
            provider_revision,
            binding_digest,
        )?;
        let record = ProviderCredentialRecord {
            version: PROVIDER_CREDENTIAL_RECORD_VERSION,
            installation_id: self.installation_id.to_string(),
            tenant_id: tenant_id.to_string(),
            provider_id: provider_id.to_string(),
            provider_revision,
            binding_digest: binding_digest.to_string(),
            credential: credential.to_string(),
        };
        validate_record(
            &record,
            &self.installation_id,
            tenant_id,
            provider_id,
            provider_revision,
            binding_digest,
        )?;
        let serialized = serde_json::to_string(&record)
            .map_err(|_| ProviderCredentialStoreError::InvalidRecord)?;
        self.store.save(&account, &serialized)
    }

    pub(super) fn load(
        &self,
        tenant_id: &str,
        provider_id: &str,
        provider_revision: u64,
        binding_digest: &str,
    ) -> Result<Option<String>, ProviderCredentialStoreError> {
        let _operation = self.lock_operations()?;
        let account = provider_credential_account(
            &self.installation_id,
            tenant_id,
            provider_id,
            provider_revision,
            binding_digest,
        )?;
        let Some(serialized) = self.store.load(&account)? else {
            return Ok(None);
        };
        let record = match serde_json::from_str::<ProviderCredentialRecord>(&serialized) {
            Ok(record) => record,
            Err(_) => {
                return self.discard_invalid(&account, ProviderCredentialStoreError::CorruptRecord)
            }
        };
        if let Err(error) = validate_record(
            &record,
            &self.installation_id,
            tenant_id,
            provider_id,
            provider_revision,
            binding_digest,
        ) {
            return self.discard_invalid(&account, error);
        }
        Ok(Some(record.credential))
    }

    pub(super) fn clear(
        &self,
        tenant_id: &str,
        provider_id: &str,
        provider_revision: u64,
        binding_digest: &str,
    ) -> Result<(), ProviderCredentialStoreError> {
        let _operation = self.lock_operations()?;
        let account = provider_credential_account(
            &self.installation_id,
            tenant_id,
            provider_id,
            provider_revision,
            binding_digest,
        )?;
        self.store.clear(&account)
    }

    fn lock_operations(&self) -> Result<MutexGuard<'_, ()>, ProviderCredentialStoreError> {
        self.operations
            .lock()
            .map_err(|_| ProviderCredentialStoreError::Unavailable)
    }

    fn discard_invalid<T>(
        &self,
        account: &str,
        error: ProviderCredentialStoreError,
    ) -> Result<T, ProviderCredentialStoreError> {
        self.store.clear(account)?;
        Err(error)
    }
}

pub(super) fn provider_credential_binding_digest(
    provider_type: &str,
    base_url: &str,
    auth_method: &str,
) -> String {
    let mut digest = Sha256::new();
    digest.update(b"memstack-llm-provider-binding-v1\0");
    digest.update(provider_type.as_bytes());
    digest.update(b"\0");
    digest.update(base_url.as_bytes());
    digest.update(b"\0");
    digest.update(auth_method.as_bytes());
    format!("{:x}", digest.finalize())
}

fn validate_record(
    record: &ProviderCredentialRecord,
    installation_id: &str,
    tenant_id: &str,
    provider_id: &str,
    provider_revision: u64,
    binding_digest: &str,
) -> Result<(), ProviderCredentialStoreError> {
    if record.version != PROVIDER_CREDENTIAL_RECORD_VERSION {
        return Err(ProviderCredentialStoreError::UnsupportedVersion);
    }
    if record.installation_id != installation_id
        || record.tenant_id != tenant_id
        || record.provider_id != provider_id
        || record.provider_revision != provider_revision
        || record.binding_digest != binding_digest
        || record.credential.trim().is_empty()
        || binding_digest.len() != 64
        || !binding_digest.bytes().all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(ProviderCredentialStoreError::InvalidRecord);
    }
    Ok(())
}

fn provider_credential_account(
    installation_id: &str,
    tenant_id: &str,
    provider_id: &str,
    provider_revision: u64,
    binding_digest: &str,
) -> Result<String, ProviderCredentialStoreError> {
    if uuid::Uuid::parse_str(installation_id).is_err()
        || tenant_id.trim().is_empty()
        || provider_id.trim().is_empty()
        || binding_digest.len() != 64
        || !binding_digest.bytes().all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(ProviderCredentialStoreError::InvalidKey);
    }
    let mut digest = Sha256::new();
    digest.update(b"memstack-llm-provider-credential-v2\0");
    digest.update(installation_id.as_bytes());
    digest.update(b"\0");
    digest.update(tenant_id.as_bytes());
    digest.update(b"\0");
    digest.update(provider_id.as_bytes());
    digest.update(b"\0");
    digest.update(provider_revision.to_be_bytes());
    digest.update(b"\0");
    digest.update(binding_digest.as_bytes());
    Ok(format!("{KEYRING_ACCOUNT_PREFIX}.{:x}", digest.finalize()))
}

struct NativeProviderCredentialStore;

impl NativeProviderCredentialStore {
    fn entry(account: &str) -> Result<keyring::Entry, ProviderCredentialStoreError> {
        keyring::Entry::new(KEYRING_SERVICE, account)
            .map_err(|_| ProviderCredentialStoreError::Unavailable)
    }
}

impl ProviderCredentialStore for NativeProviderCredentialStore {
    fn save(&self, account: &str, credential: &str) -> Result<(), ProviderCredentialStoreError> {
        Self::entry(account)?
            .set_password(credential)
            .map_err(|_| ProviderCredentialStoreError::Unavailable)
    }

    fn load(&self, account: &str) -> Result<Option<String>, ProviderCredentialStoreError> {
        match Self::entry(account)?.get_password() {
            Ok(credential) => Ok(Some(credential)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(_) => Err(ProviderCredentialStoreError::Unavailable),
        }
    }

    fn clear(&self, account: &str) -> Result<(), ProviderCredentialStoreError> {
        match Self::entry(account)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(_) => Err(ProviderCredentialStoreError::Unavailable),
        }
    }
}

#[cfg(test)]
#[derive(Default)]
struct InMemoryProviderCredentialStore {
    values: Mutex<std::collections::HashMap<String, String>>,
}

#[cfg(test)]
impl ProviderCredentialStore for InMemoryProviderCredentialStore {
    fn save(&self, account: &str, credential: &str) -> Result<(), ProviderCredentialStoreError> {
        self.values
            .lock()
            .expect("provider credential test store")
            .insert(account.to_string(), credential.to_string());
        Ok(())
    }

    fn load(&self, account: &str) -> Result<Option<String>, ProviderCredentialStoreError> {
        Ok(self
            .values
            .lock()
            .expect("provider credential test store")
            .get(account)
            .cloned())
    }

    fn clear(&self, account: &str) -> Result<(), ProviderCredentialStoreError> {
        self.values
            .lock()
            .expect("provider credential test store")
            .remove(account);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const INSTALLATION_A: &str = "11111111-1111-4111-8111-111111111111";
    const INSTALLATION_B: &str = "22222222-2222-4222-8222-222222222222";

    fn test_broker() -> ProviderCredentialBroker {
        ProviderCredentialBroker::in_memory(INSTALLATION_A).expect("test credential broker")
    }

    #[test]
    fn credentials_round_trip_without_exposing_scope_in_the_account() {
        let broker = test_broker();
        let binding_digest =
            provider_credential_binding_digest("openai", "https://api.example.test/v1", "api_key");
        broker
            .save("tenant-a", "provider-a", 3, &binding_digest, "secret-a")
            .expect("save credential");

        assert_eq!(
            broker
                .load("tenant-a", "provider-a", 3, &binding_digest)
                .expect("load credential")
                .as_deref(),
            Some("secret-a")
        );
        assert_eq!(
            broker
                .load("tenant-b", "provider-a", 3, &binding_digest)
                .expect("load other tenant credential"),
            None
        );

        let account = provider_credential_account(
            INSTALLATION_A,
            "tenant-a",
            "provider-a",
            3,
            &binding_digest,
        )
        .expect("credential account");
        assert!(account.starts_with(KEYRING_ACCOUNT_PREFIX));
        assert!(!account.contains(INSTALLATION_A));
        assert!(!account.contains("tenant-a"));
        assert!(!account.contains("provider-a"));
    }

    #[test]
    fn clearing_one_provider_preserves_other_scopes() {
        let broker = test_broker();
        let binding_digest = provider_credential_binding_digest(
            "openai_compatible",
            "https://gateway.example.test/v1",
            "api_key",
        );
        broker
            .save("tenant-a", "provider-a", 1, &binding_digest, "secret-a")
            .expect("save first credential");
        broker
            .save("tenant-a", "provider-b", 1, &binding_digest, "secret-b")
            .expect("save second credential");

        broker
            .clear("tenant-a", "provider-a", 1, &binding_digest)
            .expect("clear first credential");

        assert_eq!(
            broker
                .load("tenant-a", "provider-a", 1, &binding_digest)
                .expect("load cleared credential"),
            None
        );
        assert_eq!(
            broker
                .load("tenant-a", "provider-b", 1, &binding_digest)
                .expect("load preserved credential")
                .as_deref(),
            Some("secret-b")
        );
    }

    #[test]
    fn empty_keys_and_credentials_are_rejected() {
        let broker = test_broker();
        let binding_digest =
            provider_credential_binding_digest("openai", "https://api.example.test/v1", "api_key");
        assert_eq!(
            broker.save("", "provider", 1, &binding_digest, "secret"),
            Err(ProviderCredentialStoreError::InvalidKey)
        );
        assert_eq!(
            broker.save("tenant", "provider", 1, &binding_digest, "  "),
            Err(ProviderCredentialStoreError::InvalidRecord)
        );
    }

    #[test]
    fn versioned_accounts_preserve_the_committed_revision_during_precommit() {
        let broker = test_broker();
        let binding_digest =
            provider_credential_binding_digest("openai", "https://api.example.test/v1", "api_key");
        broker
            .save("tenant", "provider", 4, &binding_digest, "committed")
            .expect("save committed credential");
        broker
            .save("tenant", "provider", 5, &binding_digest, "precommitted")
            .expect("save precommitted credential");

        assert_eq!(
            broker
                .load("tenant", "provider", 4, &binding_digest)
                .expect("load committed credential")
                .as_deref(),
            Some("committed")
        );
        assert_eq!(
            broker
                .load("tenant", "provider", 5, &binding_digest)
                .expect("load precommitted credential")
                .as_deref(),
            Some("precommitted")
        );

        broker
            .clear("tenant", "provider", 5, &binding_digest)
            .expect("rollback precommitted credential");
        assert_eq!(
            broker
                .load("tenant", "provider", 4, &binding_digest)
                .expect("committed credential remains")
                .as_deref(),
            Some("committed")
        );
    }

    #[test]
    fn installation_namespaces_isolate_shared_operating_system_storage() {
        let store = Arc::new(InMemoryProviderCredentialStore::default());
        let installation_a = ProviderCredentialBroker::new(store.clone(), INSTALLATION_A)
            .expect("first installation broker");
        let installation_b = ProviderCredentialBroker::new(store, INSTALLATION_B)
            .expect("second installation broker");
        let binding_digest =
            provider_credential_binding_digest("openai", "https://api.example.test/v1", "api_key");
        installation_a
            .save(
                "tenant",
                "provider",
                1,
                &binding_digest,
                "installation-a-secret",
            )
            .expect("save first installation credential");

        assert_eq!(
            installation_b
                .load("tenant", "provider", 1, &binding_digest)
                .expect("load second installation credential"),
            None
        );
        assert_ne!(
            provider_credential_account(INSTALLATION_A, "tenant", "provider", 1, &binding_digest,)
                .expect("first account"),
            provider_credential_account(INSTALLATION_B, "tenant", "provider", 1, &binding_digest,)
                .expect("second account")
        );
    }

    #[test]
    fn corrupt_generation_is_discarded_without_deleting_another_revision() {
        let store = Arc::new(InMemoryProviderCredentialStore::default());
        let broker = ProviderCredentialBroker::new(store.clone(), INSTALLATION_A)
            .expect("test credential broker");
        let binding_digest =
            provider_credential_binding_digest("openai", "https://api.example.test/v1", "api_key");
        broker
            .save("tenant", "provider", 4, &binding_digest, "committed")
            .expect("save committed credential");
        broker
            .save("tenant", "provider", 5, &binding_digest, "candidate")
            .expect("save candidate credential");
        let candidate_account =
            provider_credential_account(INSTALLATION_A, "tenant", "provider", 5, &binding_digest)
                .expect("candidate account");
        store
            .values
            .lock()
            .expect("credential test store")
            .insert(candidate_account, "not-json".to_string());

        assert_eq!(
            broker.load("tenant", "provider", 5, &binding_digest),
            Err(ProviderCredentialStoreError::CorruptRecord)
        );
        assert_eq!(
            broker
                .load("tenant", "provider", 4, &binding_digest)
                .expect("committed credential remains")
                .as_deref(),
            Some("committed")
        );
    }

    #[test]
    fn record_debug_output_redacts_secret_and_scope() {
        let record = ProviderCredentialRecord {
            version: PROVIDER_CREDENTIAL_RECORD_VERSION,
            installation_id: INSTALLATION_A.to_string(),
            tenant_id: "sensitive-tenant".to_string(),
            provider_id: "sensitive-provider".to_string(),
            provider_revision: 1,
            binding_digest: "sensitive-digest".to_string(),
            credential: "sensitive-secret".to_string(),
        };
        let debug = format!("{record:?}");
        assert!(!debug.contains(INSTALLATION_A));
        assert!(!debug.contains("sensitive-tenant"));
        assert!(!debug.contains("sensitive-provider"));
        assert!(!debug.contains("sensitive-digest"));
        assert!(!debug.contains("sensitive-secret"));
    }
}
