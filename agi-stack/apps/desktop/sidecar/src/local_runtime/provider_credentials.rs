//! Application-encrypted credential storage for local LLM providers.

use std::{
    fmt,
    sync::{Arc, Mutex, MutexGuard},
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::application_vault::{ApplicationCredentialVault, ApplicationVaultError};

const PROVIDER_CREDENTIAL_RECORD_VERSION: u16 = 2;
const APPLICATION_VAULT_KEY_PREFIX: &str = "llm-provider-credential.v2";

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
            Self::Unavailable => formatter.write_str("application credential vault is unavailable"),
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

    pub(super) fn native(
        vault: ApplicationCredentialVault,
        installation_id: &str,
    ) -> Result<Self, ProviderCredentialStoreError> {
        Self::new(Arc::new(vault), installation_id)
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

    /// The site-credential broker sharing this broker's vault store and
    /// installation binding (M3 browser credential brokering: site passwords
    /// live in the same application vault, keyed under their own prefix).
    pub(super) fn site_credential_broker(&self) -> SiteCredentialBroker {
        SiteCredentialBroker {
            store: Arc::clone(&self.store),
            installation_id: Arc::clone(&self.installation_id),
            operations: Arc::clone(&self.operations),
        }
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
                return self.discard_invalid(&account, ProviderCredentialStoreError::CorruptRecord);
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
    Ok(format!(
        "{APPLICATION_VAULT_KEY_PREFIX}.{:x}",
        digest.finalize()
    ))
}

fn map_application_vault_error(error: ApplicationVaultError) -> ProviderCredentialStoreError {
    match error {
        ApplicationVaultError::InvalidKey => ProviderCredentialStoreError::InvalidKey,
        ApplicationVaultError::InvalidRecord => ProviderCredentialStoreError::InvalidRecord,
        ApplicationVaultError::CorruptRecord => ProviderCredentialStoreError::CorruptRecord,
        ApplicationVaultError::Unavailable => ProviderCredentialStoreError::Unavailable,
    }
}

const SITE_CREDENTIAL_RECORD_VERSION: u16 = 1;
const SITE_CREDENTIAL_VAULT_KEY_PREFIX: &str = "site-credential.v1";

/// The vault record for one brokered site credential. Serialized as
/// `{version: 1, origin, username, password, created_at}`; the password
/// never leaves the sidecar (tool results carry metadata only).
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SiteCredentialRecord {
    version: u16,
    origin: String,
    username: String,
    password: String,
    created_at: String,
}

impl fmt::Debug for SiteCredentialRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SiteCredentialRecord")
            .field("version", &self.version)
            .field("origin", &self.origin)
            .field("username", &self.username)
            .field("password", &"[REDACTED]")
            .field("created_at", &self.created_at)
            .finish()
    }
}

/// A decrypted site credential loaded from the vault for a fill. `Debug`
/// redacts the password so it cannot leak into logs.
#[derive(Clone, PartialEq, Eq)]
pub(super) struct SiteCredentialSecret {
    pub origin: String,
    pub username: String,
    pub password: String,
}

impl fmt::Debug for SiteCredentialSecret {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SiteCredentialSecret")
            .field("origin", &self.origin)
            .field("username", &self.username)
            .field("password", &"[REDACTED]")
            .finish()
    }
}

/// Broker for browser site credentials (M3): the session store keeps only
/// metadata rows (`desktop_browser_site_credentials`); the password lives in
/// the application vault under a deterministic, installation-bound key.
#[derive(Clone)]
pub(super) struct SiteCredentialBroker {
    store: Arc<dyn ProviderCredentialStore>,
    installation_id: Arc<str>,
    operations: Arc<Mutex<()>>,
}

impl SiteCredentialBroker {
    /// Persist (upsert) the password for (origin, username), returning the
    /// credential reference the metadata row stores. The key is deterministic
    /// per (installation, origin, username), so an upsert overwrites the same
    /// vault record.
    pub(super) fn save(
        &self,
        origin: &str,
        username: &str,
        password: &str,
        created_at: &str,
    ) -> Result<String, ProviderCredentialStoreError> {
        let _operation = self.lock_operations()?;
        let credential_ref = site_credential_ref(&self.installation_id, origin, username)?;
        let record = SiteCredentialRecord {
            version: SITE_CREDENTIAL_RECORD_VERSION,
            origin: origin.to_string(),
            username: username.to_string(),
            password: password.to_string(),
            created_at: created_at.to_string(),
        };
        validate_site_credential_record(&record, origin, username)?;
        let serialized = serde_json::to_string(&record)
            .map_err(|_| ProviderCredentialStoreError::InvalidRecord)?;
        self.store.save(&credential_ref, &serialized)?;
        Ok(credential_ref)
    }

    /// Load the credential behind `credential_ref`, verifying the record is
    /// bound to the expected origin (and username, when given). Corrupt or
    /// mismatched records are discarded, mirroring the provider broker.
    pub(super) fn load(
        &self,
        credential_ref: &str,
        origin: &str,
        username: Option<&str>,
    ) -> Result<Option<SiteCredentialSecret>, ProviderCredentialStoreError> {
        let _operation = self.lock_operations()?;
        let Some(serialized) = self.store.load(credential_ref)? else {
            return Ok(None);
        };
        let record = match serde_json::from_str::<SiteCredentialRecord>(&serialized) {
            Ok(record) => record,
            Err(_) => {
                self.store.clear(credential_ref)?;
                return Err(ProviderCredentialStoreError::CorruptRecord);
            }
        };
        if let Err(error) = validate_site_credential_record(&record, origin, &record.username) {
            self.store.clear(credential_ref)?;
            return Err(error);
        }
        if !username.map_or(true, |username| username == record.username) {
            self.store.clear(credential_ref)?;
            return Err(ProviderCredentialStoreError::InvalidRecord);
        }
        Ok(Some(SiteCredentialSecret {
            origin: record.origin,
            username: record.username,
            password: record.password,
        }))
    }

    pub(super) fn clear(&self, credential_ref: &str) -> Result<(), ProviderCredentialStoreError> {
        let _operation = self.lock_operations()?;
        if credential_ref.trim().is_empty() {
            return Err(ProviderCredentialStoreError::InvalidKey);
        }
        self.store.clear(credential_ref)
    }

    fn lock_operations(&self) -> Result<MutexGuard<'_, ()>, ProviderCredentialStoreError> {
        self.operations
            .lock()
            .map_err(|_| ProviderCredentialStoreError::Unavailable)
    }
}

/// The vault record key for one site credential:
/// `site-credential.v1.<sha256(installation_id ‖ origin ‖ username)>`.
pub(super) fn site_credential_ref(
    installation_id: &str,
    origin: &str,
    username: &str,
) -> Result<String, ProviderCredentialStoreError> {
    if uuid::Uuid::parse_str(installation_id).is_err()
        || origin.trim().is_empty()
        || username.trim().is_empty()
    {
        return Err(ProviderCredentialStoreError::InvalidKey);
    }
    let mut digest = Sha256::new();
    digest.update(b"memstack-browser-site-credential-v1\0");
    digest.update(installation_id.as_bytes());
    digest.update(b"\0");
    digest.update(origin.as_bytes());
    digest.update(b"\0");
    digest.update(username.as_bytes());
    Ok(format!(
        "{SITE_CREDENTIAL_VAULT_KEY_PREFIX}.{:x}",
        digest.finalize()
    ))
}

fn validate_site_credential_record(
    record: &SiteCredentialRecord,
    origin: &str,
    username: &str,
) -> Result<(), ProviderCredentialStoreError> {
    if record.version != SITE_CREDENTIAL_RECORD_VERSION {
        return Err(ProviderCredentialStoreError::UnsupportedVersion);
    }
    if record.origin != origin
        || record.username != username
        || record.password.is_empty()
        || record.created_at.trim().is_empty()
    {
        return Err(ProviderCredentialStoreError::InvalidRecord);
    }
    Ok(())
}

impl ProviderCredentialStore for ApplicationCredentialVault {
    fn save(&self, account: &str, credential: &str) -> Result<(), ProviderCredentialStoreError> {
        self.put(account, credential)
            .map_err(map_application_vault_error)
    }

    fn load(&self, account: &str) -> Result<Option<String>, ProviderCredentialStoreError> {
        self.get(account).map_err(map_application_vault_error)
    }

    fn clear(&self, account: &str) -> Result<(), ProviderCredentialStoreError> {
        ApplicationCredentialVault::clear(self, account).map_err(map_application_vault_error)
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
        assert!(account.starts_with(APPLICATION_VAULT_KEY_PREFIX));
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
    fn installation_namespaces_isolate_shared_application_vault_storage() {
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

    #[test]
    fn site_credentials_round_trip_and_upsert_under_one_vault_key() {
        let broker = ProviderCredentialBroker::in_memory(INSTALLATION_A)
            .expect("provider broker")
            .site_credential_broker();
        let first_ref = broker
            .save(
                "example.com",
                "alice",
                "first-secret",
                "2026-08-09T00:00:01Z",
            )
            .expect("save credential");
        assert!(first_ref.starts_with(SITE_CREDENTIAL_VAULT_KEY_PREFIX));
        assert!(!first_ref.contains("example.com"));
        assert!(!first_ref.contains("alice"));

        let secret = broker
            .load(&first_ref, "example.com", Some("alice"))
            .expect("load credential")
            .expect("credential present");
        assert_eq!(secret.origin, "example.com");
        assert_eq!(secret.username, "alice");
        assert_eq!(secret.password, "first-secret");

        // Upsert: same (origin, username) reuses the deterministic vault key
        // and overwrites the password.
        let second_ref = broker
            .save(
                "example.com",
                "alice",
                "second-secret",
                "2026-08-09T00:00:02Z",
            )
            .expect("upsert credential");
        assert_eq!(first_ref, second_ref);
        let secret = broker
            .load(&first_ref, "example.com", Some("alice"))
            .expect("load upserted credential")
            .expect("credential present");
        assert_eq!(secret.password, "second-secret");

        broker.clear(&first_ref).expect("clear credential");
        assert!(broker
            .load(&first_ref, "example.com", Some("alice"))
            .expect("load cleared credential")
            .is_none());
    }

    #[test]
    fn site_credential_load_revalidates_scope_and_discards_mismatches() {
        let store = Arc::new(InMemoryProviderCredentialStore::default());
        let broker = ProviderCredentialBroker::new(store.clone(), INSTALLATION_A)
            .expect("provider broker")
            .site_credential_broker();
        let credential_ref = broker
            .save("example.com", "alice", "secret-a", "2026-08-09T00:00:01Z")
            .expect("save credential");

        // Wrong origin / username scopes fail and discard the record.
        assert_eq!(
            broker.load(&credential_ref, "other.test", Some("alice")),
            Err(ProviderCredentialStoreError::InvalidRecord)
        );
        assert!(store
            .values
            .lock()
            .expect("credential test store")
            .get(&credential_ref)
            .is_none());

        let credential_ref = broker
            .save("example.com", "alice", "secret-a", "2026-08-09T00:00:02Z")
            .expect("resave credential");
        assert_eq!(
            broker.load(&credential_ref, "example.com", Some("bob")),
            Err(ProviderCredentialStoreError::InvalidRecord)
        );

        // A corrupt record is reported and discarded.
        let credential_ref = broker
            .save("example.com", "alice", "secret-a", "2026-08-09T00:00:03Z")
            .expect("resave credential");
        store
            .values
            .lock()
            .expect("credential test store")
            .insert(credential_ref.clone(), "not-json".to_string());
        assert_eq!(
            broker.load(&credential_ref, "example.com", Some("alice")),
            Err(ProviderCredentialStoreError::CorruptRecord)
        );

        // Empty secrets and scopes are rejected outright.
        assert_eq!(
            broker.save("example.com", "alice", "", "2026-08-09T00:00:04Z"),
            Err(ProviderCredentialStoreError::InvalidRecord)
        );
        assert_eq!(
            broker.save("", "alice", "secret", "2026-08-09T00:00:04Z"),
            Err(ProviderCredentialStoreError::InvalidKey)
        );
    }

    #[test]
    fn site_credential_debug_output_redacts_password() {
        let record = SiteCredentialRecord {
            version: SITE_CREDENTIAL_RECORD_VERSION,
            origin: "example.com".to_string(),
            username: "alice".to_string(),
            password: "sensitive-password".to_string(),
            created_at: "2026-08-09T00:00:01Z".to_string(),
        };
        let debug = format!("{record:?}");
        assert!(!debug.contains("sensitive-password"));
        let secret = SiteCredentialSecret {
            origin: "example.com".to_string(),
            username: "alice".to_string(),
            password: "sensitive-password".to_string(),
        };
        assert!(!format!("{secret:?}").contains("sensitive-password"));
    }
}
