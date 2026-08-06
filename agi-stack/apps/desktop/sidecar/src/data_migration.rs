//! One-time migration of the legacy Tauri data directory.

use std::{
    fs::{self, File, OpenOptions},
    io::{self, Write},
    path::{Path, PathBuf},
    time::Duration,
};

use rusqlite::{backup::Backup, Connection, OpenFlags};
use serde::Serialize;
use uuid::Uuid;

use crate::private_file_permissions;

const VAULT_DIRECTORY: &str = "credential-vault";
const VAULT_MASTER_KEY: &str = "master.key";
const VAULT_DATABASE: &str = "records.db";
const RUNTIME_DATABASES: &[&str] = &[
    "agistack-local-agent-checkpoints.db",
    "agistack-desktop-sessions.db",
];
const MIGRATION_MARKER: &str = ".tauri-data-migration-v1.json";

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct MigrationMarker {
    version: u8,
    source: PathBuf,
}

/// Copies missing credential and runtime databases from the first legacy data
/// directory that contains MemStack desktop state.
pub(crate) fn migrate_legacy_data(
    destination: &Path,
    legacy_candidates: &[PathBuf],
) -> Result<Option<PathBuf>, String> {
    fs::create_dir_all(destination).map_err(|error| error.to_string())?;
    set_private_directory_permissions(destination).map_err(|error| error.to_string())?;

    let Some(source) = legacy_candidates.iter().find(|candidate| {
        candidate.as_path() != destination
            && (candidate.join(VAULT_DIRECTORY).exists()
                || RUNTIME_DATABASES
                    .iter()
                    .any(|name| candidate.join(name).exists()))
    }) else {
        return Ok(None);
    };

    migrate_vault(source, destination)?;
    for database in RUNTIME_DATABASES {
        copy_sqlite_if_missing(&source.join(database), &destination.join(database))?;
    }
    write_marker(destination, source)?;
    Ok(Some(source.clone()))
}

fn migrate_vault(source: &Path, destination: &Path) -> Result<(), String> {
    let source_vault = source.join(VAULT_DIRECTORY);
    let destination_vault = destination.join(VAULT_DIRECTORY);
    if destination_vault.exists() || !source_vault.exists() {
        return Ok(());
    }

    let source_key = source_vault.join(VAULT_MASTER_KEY);
    let source_database = source_vault.join(VAULT_DATABASE);
    if !source_key.is_file() || !source_database.is_file() {
        return Err("legacy credential vault is incomplete".to_string());
    }

    let staged_vault = destination.join(format!(".credential-vault-{}.tmp", Uuid::new_v4()));
    fs::create_dir(&staged_vault).map_err(|error| error.to_string())?;
    set_private_directory_permissions(&staged_vault).map_err(|error| error.to_string())?;
    let result = (|| {
        copy_private_file(&source_key, &staged_vault.join(VAULT_MASTER_KEY))?;
        copy_sqlite_database(&source_database, &staged_vault.join(VAULT_DATABASE))?;
        fs::rename(&staged_vault, &destination_vault).map_err(|error| error.to_string())
    })();
    if result.is_err() {
        let _ = fs::remove_dir_all(&staged_vault);
    }
    result
}

fn copy_sqlite_if_missing(source: &Path, destination: &Path) -> Result<(), String> {
    if destination.exists() || !source.exists() {
        return Ok(());
    }
    let temporary = destination.with_extension(format!("migration-{}.tmp", Uuid::new_v4()));
    let result = (|| {
        copy_sqlite_database(source, &temporary)?;
        fs::rename(&temporary, destination).map_err(|error| error.to_string())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn copy_sqlite_database(source: &Path, destination: &Path) -> Result<(), String> {
    let source_connection = Connection::open_with_flags(
        source,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|error| error.to_string())?;
    let mut destination_connection =
        Connection::open(destination).map_err(|error| error.to_string())?;
    {
        let backup = Backup::new(&source_connection, &mut destination_connection)
            .map_err(|error| format!("failed to initialize legacy SQLite backup: {error}"))?;
        backup
            .run_to_completion(64, Duration::from_millis(10), None)
            .map_err(|error| format!("failed to migrate legacy SQLite database: {error}"))?;
    }
    destination_connection
        .execute_batch("PRAGMA wal_checkpoint(TRUNCATE);")
        .map_err(|error| error.to_string())?;
    drop(destination_connection);
    set_private_file_permissions(destination).map_err(|error| error.to_string())
}

fn copy_private_file(source: &Path, destination: &Path) -> Result<(), String> {
    let bytes = fs::read(source).map_err(|error| error.to_string())?;
    let mut file = open_new_private_file(destination).map_err(|error| error.to_string())?;
    file.write_all(&bytes).map_err(|error| error.to_string())?;
    file.sync_all().map_err(|error| error.to_string())?;
    set_private_file_permissions(destination).map_err(|error| error.to_string())
}

fn write_marker(destination: &Path, source: &Path) -> Result<(), String> {
    let marker_path = destination.join(MIGRATION_MARKER);
    if marker_path.exists() {
        return Ok(());
    }
    let serialized = serde_json::to_vec(&MigrationMarker {
        version: 1,
        source: source.to_path_buf(),
    })
    .map_err(|error| error.to_string())?;
    let mut file = open_new_private_file(&marker_path).map_err(|error| error.to_string())?;
    file.write_all(&serialized)
        .and_then(|()| file.sync_all())
        .map_err(|error| error.to_string())?;
    set_private_file_permissions(&marker_path).map_err(|error| error.to_string())
}

fn open_new_private_file(path: &Path) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;

        options.mode(0o600);
    }
    options.open(path)
}

fn set_private_directory_permissions(path: &Path) -> io::Result<()> {
    private_file_permissions::set_private_directory_permissions(path)
}

fn set_private_file_permissions(path: &Path) -> io::Result<()> {
    private_file_permissions::set_private_file_permissions(path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application_vault::ApplicationCredentialVault;

    struct TestDirectory(PathBuf);

    impl TestDirectory {
        fn create(label: &str) -> Self {
            let path = std::env::temp_dir().join(format!("{label}-{}", Uuid::new_v4()));
            fs::create_dir_all(&path).expect("create test directory");
            Self(path)
        }
    }

    impl Drop for TestDirectory {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn create_database(path: &Path, value: &str) {
        let connection = Connection::open(path).expect("open fixture database");
        connection
            .execute_batch("CREATE TABLE fixture(value TEXT NOT NULL);")
            .expect("create fixture schema");
        connection
            .execute("INSERT INTO fixture(value) VALUES (?1)", [value])
            .expect("insert fixture value");
    }

    fn read_database(path: &Path) -> String {
        Connection::open(path)
            .expect("open migrated database")
            .query_row("SELECT value FROM fixture", [], |row| row.get(0))
            .expect("read migrated value")
    }

    #[test]
    fn migration_preserves_vault_and_runtime_databases() {
        let root = TestDirectory::create("agistack-sidecar-migration");
        let legacy = root.0.join("legacy");
        let destination = root.0.join("electron");
        fs::create_dir_all(&legacy).expect("create legacy data");
        let legacy_vault =
            ApplicationCredentialVault::open(&legacy).expect("open legacy credential vault");
        legacy_vault
            .put("trusted-session.v1", "secret-session-record")
            .expect("store legacy secret");
        create_database(
            &legacy.join("agistack-local-agent-checkpoints.db"),
            "checkpoint",
        );
        create_database(&legacy.join("agistack-desktop-sessions.db"), "session");

        let migrated =
            migrate_legacy_data(&destination, std::slice::from_ref(&legacy)).expect("migrate");

        assert_eq!(migrated, Some(legacy));
        let migrated_vault =
            ApplicationCredentialVault::open(&destination).expect("open migrated vault");
        assert_eq!(
            migrated_vault
                .get("trusted-session.v1")
                .expect("read migrated secret"),
            Some("secret-session-record".to_string())
        );
        assert_eq!(
            read_database(&destination.join("agistack-local-agent-checkpoints.db")),
            "checkpoint"
        );
        assert_eq!(
            read_database(&destination.join("agistack-desktop-sessions.db")),
            "session"
        );
        assert!(destination.join(MIGRATION_MARKER).is_file());
    }

    #[test]
    fn migration_never_overwrites_existing_destination_state() {
        let root = TestDirectory::create("agistack-sidecar-no-overwrite");
        let legacy = root.0.join("legacy");
        let destination = root.0.join("electron");
        fs::create_dir_all(&legacy).expect("create legacy data");
        fs::create_dir_all(&destination).expect("create destination data");
        create_database(&legacy.join("agistack-desktop-sessions.db"), "legacy");
        create_database(
            &destination.join("agistack-desktop-sessions.db"),
            "electron",
        );

        migrate_legacy_data(&destination, &[legacy]).expect("migrate missing state");

        assert_eq!(
            read_database(&destination.join("agistack-desktop-sessions.db")),
            "electron"
        );
    }

    #[cfg(windows)]
    #[test]
    fn migrated_windows_vault_files_use_current_user_only_acl() {
        use crate::private_file_permissions::path_has_current_user_only_acl;

        let root = TestDirectory::create("agistack-sidecar-windows-vault-migration");
        let legacy = root.0.join("legacy");
        let destination = root.0.join("electron");
        fs::create_dir_all(&legacy).expect("create legacy data");
        let legacy_vault =
            ApplicationCredentialVault::open(&legacy).expect("open legacy credential vault");
        legacy_vault
            .put("trusted-session.v1", "secret-session-record")
            .expect("store legacy secret");
        drop(legacy_vault);

        migrate_legacy_data(&destination, &[legacy]).expect("migrate vault");

        assert!(
            path_has_current_user_only_acl(&destination.join(VAULT_DIRECTORY), true)
                .expect("inspect migrated vault directory ACL")
        );
        assert!(path_has_current_user_only_acl(
            &destination.join(VAULT_DIRECTORY).join(VAULT_MASTER_KEY),
            false,
        )
        .expect("inspect migrated vault key ACL"));
        assert!(path_has_current_user_only_acl(
            &destination.join(VAULT_DIRECTORY).join(VAULT_DATABASE),
            false,
        )
        .expect("inspect migrated vault database ACL"));
    }
}
