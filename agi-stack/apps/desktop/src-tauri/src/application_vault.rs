//! Application-managed encrypted storage for desktop credentials.
//!
//! Ciphertext lives in SQLite while a random per-installation master key is kept in a separate
//! user-private file. This deliberately avoids operating-system credential APIs. It protects a
//! copied database, but cannot defend against malware already running as the same operating-system
//! user because that process can potentially read both files.

use std::{
    fmt,
    fs::{self, File, OpenOptions},
    io::{ErrorKind, Read, Write},
    path::Path,
    sync::{Arc, Mutex, MutexGuard},
};

use aes_gcm::{
    aead::{Aead, KeyInit, Payload},
    Aes256Gcm, Nonce,
};
use base64::{engine::general_purpose::STANDARD_NO_PAD, Engine as _};
use rusqlite::{params, Connection, OptionalExtension};
use zeroize::Zeroize;

const VAULT_DIRECTORY: &str = "credential-vault";
const MASTER_KEY_FILE: &str = "master.key";
const DATABASE_FILE: &str = "records.db";
const MASTER_KEY_LENGTH: usize = 32;
const NONCE_LENGTH: usize = 12;
const MAX_RECORD_KEY_LENGTH: usize = 512;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ApplicationVaultError {
    InvalidKey,
    InvalidRecord,
    CorruptRecord,
    Unavailable,
}

impl fmt::Display for ApplicationVaultError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidKey => formatter.write_str("application vault record key is invalid"),
            Self::InvalidRecord => formatter.write_str("application vault record is invalid"),
            Self::CorruptRecord => formatter.write_str("application vault record is corrupt"),
            Self::Unavailable => formatter.write_str("application credential vault is unavailable"),
        }
    }
}

struct ApplicationVaultState {
    connection: Mutex<Connection>,
    master_key: [u8; MASTER_KEY_LENGTH],
}

impl Drop for ApplicationVaultState {
    fn drop(&mut self) {
        self.master_key.zeroize();
    }
}

#[derive(Clone)]
pub(crate) struct ApplicationCredentialVault {
    state: Arc<ApplicationVaultState>,
}

impl ApplicationCredentialVault {
    pub(crate) fn open(app_data_dir: &Path) -> Result<Self, ApplicationVaultError> {
        let vault_directory = app_data_dir.join(VAULT_DIRECTORY);
        fs::create_dir_all(&vault_directory).map_err(|_| ApplicationVaultError::Unavailable)?;
        set_private_directory_permissions(&vault_directory)?;

        let master_key = load_or_create_master_key(&vault_directory.join(MASTER_KEY_FILE))?;
        let database_path = vault_directory.join(DATABASE_FILE);
        ensure_private_database_file(&database_path)?;
        let connection =
            Connection::open(&database_path).map_err(|_| ApplicationVaultError::Unavailable)?;
        connection
            .execute_batch(
                "PRAGMA trusted_schema = OFF;
                 PRAGMA secure_delete = ON;
                 CREATE TABLE IF NOT EXISTS application_vault_records (
                     record_key TEXT PRIMARY KEY NOT NULL,
                     encrypted_value TEXT NOT NULL
                 );",
            )
            .map_err(|_| ApplicationVaultError::Unavailable)?;

        Ok(Self {
            state: Arc::new(ApplicationVaultState {
                connection: Mutex::new(connection),
                master_key,
            }),
        })
    }

    pub(crate) fn put(
        &self,
        record_key: &str,
        plaintext: &str,
    ) -> Result<(), ApplicationVaultError> {
        validate_record_key(record_key)?;
        if plaintext.is_empty() {
            return Err(ApplicationVaultError::InvalidRecord);
        }

        let encrypted_value = self.encrypt(record_key, plaintext)?;
        self.connection()?
            .execute(
                "INSERT INTO application_vault_records (record_key, encrypted_value)
                 VALUES (?1, ?2)
                 ON CONFLICT(record_key) DO UPDATE SET encrypted_value = excluded.encrypted_value",
                params![record_key, encrypted_value],
            )
            .map_err(|_| ApplicationVaultError::Unavailable)?;
        Ok(())
    }

    pub(crate) fn get(&self, record_key: &str) -> Result<Option<String>, ApplicationVaultError> {
        validate_record_key(record_key)?;
        let encrypted_value = self
            .connection()?
            .query_row(
                "SELECT encrypted_value FROM application_vault_records WHERE record_key = ?1",
                params![record_key],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|_| ApplicationVaultError::Unavailable)?;
        let Some(encrypted_value) = encrypted_value else {
            return Ok(None);
        };

        match self.decrypt(record_key, &encrypted_value) {
            Ok(plaintext) => Ok(Some(plaintext)),
            Err(ApplicationVaultError::CorruptRecord) => {
                self.clear(record_key)?;
                Err(ApplicationVaultError::CorruptRecord)
            }
            Err(error) => Err(error),
        }
    }

    pub(crate) fn clear(&self, record_key: &str) -> Result<(), ApplicationVaultError> {
        validate_record_key(record_key)?;
        self.connection()?
            .execute(
                "DELETE FROM application_vault_records WHERE record_key = ?1",
                params![record_key],
            )
            .map_err(|_| ApplicationVaultError::Unavailable)?;
        Ok(())
    }

    fn encrypt(&self, record_key: &str, plaintext: &str) -> Result<String, ApplicationVaultError> {
        let cipher = Aes256Gcm::new_from_slice(&self.state.master_key)
            .map_err(|_| ApplicationVaultError::Unavailable)?;
        let mut nonce_bytes = [0_u8; NONCE_LENGTH];
        getrandom::getrandom(&mut nonce_bytes).map_err(|_| ApplicationVaultError::Unavailable)?;
        let ciphertext = cipher
            .encrypt(
                Nonce::from_slice(&nonce_bytes),
                Payload {
                    msg: plaintext.as_bytes(),
                    aad: record_key.as_bytes(),
                },
            )
            .map_err(|_| ApplicationVaultError::Unavailable)?;
        let mut encoded_record = Vec::with_capacity(NONCE_LENGTH + ciphertext.len());
        encoded_record.extend_from_slice(&nonce_bytes);
        encoded_record.extend_from_slice(&ciphertext);
        Ok(STANDARD_NO_PAD.encode(encoded_record))
    }

    fn decrypt(
        &self,
        record_key: &str,
        encrypted_value: &str,
    ) -> Result<String, ApplicationVaultError> {
        let encoded_record = STANDARD_NO_PAD
            .decode(encrypted_value)
            .map_err(|_| ApplicationVaultError::CorruptRecord)?;
        if encoded_record.len() <= NONCE_LENGTH {
            return Err(ApplicationVaultError::CorruptRecord);
        }
        let (nonce_bytes, ciphertext) = encoded_record.split_at(NONCE_LENGTH);
        let cipher = Aes256Gcm::new_from_slice(&self.state.master_key)
            .map_err(|_| ApplicationVaultError::Unavailable)?;
        let plaintext = cipher
            .decrypt(
                Nonce::from_slice(nonce_bytes),
                Payload {
                    msg: ciphertext,
                    aad: record_key.as_bytes(),
                },
            )
            .map_err(|_| ApplicationVaultError::CorruptRecord)?;
        String::from_utf8(plaintext).map_err(|_| ApplicationVaultError::CorruptRecord)
    }

    fn connection(&self) -> Result<MutexGuard<'_, Connection>, ApplicationVaultError> {
        self.state
            .connection
            .lock()
            .map_err(|_| ApplicationVaultError::Unavailable)
    }

    #[cfg(test)]
    fn replace_encrypted_value_for_test(
        &self,
        record_key: &str,
        encrypted_value: &str,
    ) -> Result<(), ApplicationVaultError> {
        self.connection()?
            .execute(
                "UPDATE application_vault_records SET encrypted_value = ?2 WHERE record_key = ?1",
                params![record_key, encrypted_value],
            )
            .map_err(|_| ApplicationVaultError::Unavailable)?;
        Ok(())
    }

    #[cfg(test)]
    fn swap_encrypted_values_for_test(
        &self,
        first_key: &str,
        second_key: &str,
    ) -> Result<(), ApplicationVaultError> {
        let connection = self.connection()?;
        connection
            .execute(
                "UPDATE application_vault_records
                 SET encrypted_value = CASE record_key
                     WHEN ?1 THEN (SELECT encrypted_value FROM application_vault_records WHERE record_key = ?2)
                     WHEN ?2 THEN (SELECT encrypted_value FROM application_vault_records WHERE record_key = ?1)
                 END
                 WHERE record_key IN (?1, ?2)",
                params![first_key, second_key],
            )
            .map_err(|_| ApplicationVaultError::Unavailable)?;
        Ok(())
    }
}

fn validate_record_key(record_key: &str) -> Result<(), ApplicationVaultError> {
    if record_key.is_empty()
        || record_key.len() > MAX_RECORD_KEY_LENGTH
        || record_key.chars().any(char::is_control)
    {
        return Err(ApplicationVaultError::InvalidKey);
    }
    Ok(())
}

fn load_or_create_master_key(
    master_key_path: &Path,
) -> Result<[u8; MASTER_KEY_LENGTH], ApplicationVaultError> {
    match File::open(master_key_path) {
        Ok(_) => read_master_key(master_key_path),
        Err(error) if error.kind() == ErrorKind::NotFound => {
            let mut master_key = [0_u8; MASTER_KEY_LENGTH];
            getrandom::getrandom(&mut master_key)
                .map_err(|_| ApplicationVaultError::Unavailable)?;
            match open_new_private_file(master_key_path) {
                Ok(mut file) => {
                    if file
                        .write_all(&master_key)
                        .and_then(|()| file.sync_all())
                        .is_err()
                    {
                        drop(file);
                        let _ = fs::remove_file(master_key_path);
                        master_key.zeroize();
                        return Err(ApplicationVaultError::Unavailable);
                    }
                    if set_private_file_permissions(master_key_path).is_err() {
                        master_key.zeroize();
                        return Err(ApplicationVaultError::Unavailable);
                    }
                    Ok(master_key)
                }
                Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                    master_key.zeroize();
                    read_master_key(master_key_path)
                }
                Err(_) => {
                    master_key.zeroize();
                    Err(ApplicationVaultError::Unavailable)
                }
            }
        }
        Err(_) => Err(ApplicationVaultError::Unavailable),
    }
}

fn ensure_private_database_file(path: &Path) -> Result<(), ApplicationVaultError> {
    match open_new_private_file(path) {
        Ok(file) => drop(file),
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {}
        Err(_) => return Err(ApplicationVaultError::Unavailable),
    }
    set_private_file_permissions(path)
}

fn open_new_private_file(path: &Path) -> std::io::Result<File> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;

        options.mode(0o600);
    }
    options.open(path)
}

fn read_master_key(path: &Path) -> Result<[u8; MASTER_KEY_LENGTH], ApplicationVaultError> {
    set_private_file_permissions(path)?;
    let mut bytes = Vec::new();
    if File::open(path)
        .and_then(|mut file| file.read_to_end(&mut bytes))
        .is_err()
    {
        bytes.zeroize();
        return Err(ApplicationVaultError::Unavailable);
    }
    if bytes.len() != MASTER_KEY_LENGTH {
        bytes.zeroize();
        return Err(ApplicationVaultError::Unavailable);
    }
    let mut master_key = [0_u8; MASTER_KEY_LENGTH];
    master_key.copy_from_slice(&bytes);
    bytes.zeroize();
    Ok(master_key)
}

#[cfg(unix)]
fn set_private_directory_permissions(path: &Path) -> Result<(), ApplicationVaultError> {
    use std::os::unix::fs::PermissionsExt;

    fs::set_permissions(path, fs::Permissions::from_mode(0o700))
        .map_err(|_| ApplicationVaultError::Unavailable)
}

#[cfg(not(unix))]
fn set_private_directory_permissions(_path: &Path) -> Result<(), ApplicationVaultError> {
    Ok(())
}

#[cfg(unix)]
fn set_private_file_permissions(path: &Path) -> Result<(), ApplicationVaultError> {
    use std::os::unix::fs::PermissionsExt;

    fs::set_permissions(path, fs::Permissions::from_mode(0o600))
        .map_err(|_| ApplicationVaultError::Unavailable)
}

#[cfg(not(unix))]
fn set_private_file_permissions(_path: &Path) -> Result<(), ApplicationVaultError> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::{fs, path::PathBuf};

    use super::{ApplicationCredentialVault, ApplicationVaultError};

    fn test_root(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "agistack-application-vault-{name}-{}",
            uuid::Uuid::new_v4()
        ))
    }

    #[test]
    fn encrypted_records_survive_reopen_without_plaintext_in_database() {
        let root = test_root("reopen");
        let secret = "cloud-bearer-secret-that-must-not-appear-on-disk";
        let vault = ApplicationCredentialVault::open(&root).expect("open application vault");
        vault
            .put("trusted-session.v1", secret)
            .expect("store encrypted record");
        drop(vault);

        let database = fs::read(root.join("credential-vault/records.db"))
            .expect("read encrypted vault database");
        assert!(!database
            .windows(secret.len())
            .any(|window| window == secret.as_bytes()));

        let reopened = ApplicationCredentialVault::open(&root).expect("reopen application vault");
        assert_eq!(
            reopened
                .get("trusted-session.v1")
                .expect("load encrypted record"),
            Some(secret.to_string())
        );
        fs::remove_dir_all(root).expect("remove application vault test root");
    }

    #[test]
    fn ciphertext_cannot_be_swapped_between_record_keys() {
        let root = test_root("aad");
        let vault = ApplicationCredentialVault::open(&root).expect("open application vault");
        vault.put("record-a", "secret-a").expect("store record a");
        vault.put("record-b", "secret-b").expect("store record b");
        vault
            .swap_encrypted_values_for_test("record-a", "record-b")
            .expect("swap encrypted test values");

        assert_eq!(
            vault.get("record-a"),
            Err(ApplicationVaultError::CorruptRecord)
        );
        assert_eq!(
            vault.get("record-a").expect("reload discarded record"),
            None
        );
        fs::remove_dir_all(root).expect("remove application vault test root");
    }

    #[test]
    fn corrupt_record_is_removed_after_detection() {
        let root = test_root("corrupt");
        let vault = ApplicationCredentialVault::open(&root).expect("open application vault");
        vault.put("record", "secret").expect("store record");
        vault
            .replace_encrypted_value_for_test("record", "not-valid-base64")
            .expect("corrupt encrypted test value");

        assert_eq!(
            vault.get("record"),
            Err(ApplicationVaultError::CorruptRecord)
        );
        assert_eq!(vault.get("record").expect("reload discarded record"), None);
        fs::remove_dir_all(root).expect("remove application vault test root");
    }

    #[test]
    fn clear_is_idempotent() {
        let root = test_root("clear");
        let vault = ApplicationCredentialVault::open(&root).expect("open application vault");
        vault.put("record", "secret").expect("store record");

        vault.clear("record").expect("clear stored record");
        vault.clear("record").expect("clear missing record");
        assert_eq!(vault.get("record").expect("load cleared record"), None);
        fs::remove_dir_all(root).expect("remove application vault test root");
    }

    #[cfg(unix)]
    #[test]
    fn vault_files_use_private_unix_permissions() {
        use std::os::unix::fs::PermissionsExt;

        let root = test_root("permissions");
        let vault = ApplicationCredentialVault::open(&root).expect("open application vault");
        vault.put("record", "secret").expect("store record");

        let directory_mode = fs::metadata(root.join("credential-vault"))
            .expect("read vault directory metadata")
            .permissions()
            .mode()
            & 0o777;
        let key_mode = fs::metadata(root.join("credential-vault/master.key"))
            .expect("read vault key metadata")
            .permissions()
            .mode()
            & 0o777;
        let database_mode = fs::metadata(root.join("credential-vault/records.db"))
            .expect("read vault database metadata")
            .permissions()
            .mode()
            & 0o777;
        assert_eq!(directory_mode, 0o700);
        assert_eq!(key_mode, 0o600);
        assert_eq!(database_mode, 0o600);
        fs::remove_dir_all(root).expect("remove application vault test root");
    }
}
