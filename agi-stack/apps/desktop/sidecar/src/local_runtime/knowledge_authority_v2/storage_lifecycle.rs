//! Filesystem work happens only when an admitted knowledge generation activates.
//! Upgrade backups use SQLite's online backup API, including committed WAL data.

use std::{
    fs,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};

use agistack_adapters_device::knowledge::{SqliteKnowledgeRepository, KNOWLEDGE_SCHEMA_VERSION};
use rusqlite::{backup::Backup, Connection, OpenFlags, OptionalExtension};
use uuid::Uuid;

use crate::private_file_permissions::{
    set_private_directory_permissions, set_private_file_permissions,
};

const SCHEMA_VERSION: i64 = KNOWLEDGE_SCHEMA_VERSION;

pub(super) fn open(app_data_dir: &Path) -> Result<Arc<SqliteKnowledgeRepository>, String> {
    let directory = app_data_dir.join("knowledge");
    ensure_directory(&directory)?;
    let database = directory.join("memories.db");
    let existed = database.try_exists().map_err(message)?;
    if existed {
        ensure_regular_file(&database)?;
        let connection = read_only(&database)?;
        verify(&connection)?;
        let version = schema_version(&connection)?;
        if version > SCHEMA_VERSION {
            return Err("knowledge database uses an unsupported schema version".into());
        }
        if version < SCHEMA_VERSION {
            backup(&connection, &directory, version)?;
        }
    } else {
        let file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&database)
            .map_err(message)?;
        set_private_file_permissions(&database).map_err(message)?;
        file.sync_all().map_err(message)?;
    }
    let path = database
        .to_str()
        .ok_or_else(|| "knowledge database path is not valid UTF-8".to_owned())?;
    let repository = SqliteKnowledgeRepository::open(path).map_err(message)?;
    set_private_file_permissions(&database).map_err(message)?;
    let connection = read_only(&database)?;
    verify(&connection)?;
    if schema_version(&connection)? != SCHEMA_VERSION {
        return Err("knowledge database migration did not reach the required version".into());
    }
    Ok(Arc::new(repository))
}

fn ensure_directory(path: &Path) -> Result<(), String> {
    if let Ok(metadata) = fs::symlink_metadata(path) {
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err("knowledge directory is not a regular directory".into());
        }
    }
    fs::create_dir_all(path).map_err(message)?;
    set_private_directory_permissions(path).map_err(message)
}

fn ensure_regular_file(path: &Path) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path).map_err(message)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("knowledge database is not a regular file".into());
    }
    Ok(())
}

fn read_only(path: &Path) -> Result<Connection, String> {
    Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(message)
}

fn verify(connection: &Connection) -> Result<(), String> {
    let mut statement = connection.prepare("PRAGMA quick_check").map_err(message)?;
    let checks = statement
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(message)?;
    let mut checked = false;
    for check in checks {
        if check.map_err(message)? != "ok" {
            return Err("knowledge database integrity validation failed".into());
        }
        checked = true;
    }
    if !checked {
        return Err("knowledge database integrity validation returned no result".into());
    }
    Ok(())
}

fn schema_version(connection: &Connection) -> Result<i64, String> {
    let exists: Option<i64> = connection
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_schema'",
            [],
            |row| row.get(0),
        )
        .optional()
        .map_err(message)?;
    if exists.is_none() {
        return Ok(0);
    }
    let (count, minimum, maximum): (i64, Option<i64>, Option<i64>) = connection
        .query_row(
            "SELECT count(*),min(version),max(version) FROM knowledge_schema",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .map_err(message)?;
    match (count, minimum, maximum) {
        (1, Some(version), Some(same)) if version == same && version > 0 => Ok(version),
        _ => Err("knowledge database schema metadata is invalid".into()),
    }
}

fn backup(source: &Connection, directory: &Path, version: i64) -> Result<PathBuf, String> {
    let path = directory.join(format!(
        "memories.pre-v{version}-{}.backup.db",
        Uuid::new_v4()
    ));
    let file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
        .map_err(message)?;
    set_private_file_permissions(&path).map_err(message)?;
    let result: Result<(), String> = (|| {
        let mut destination = Connection::open(&path).map_err(message)?;
        Backup::new(source, &mut destination)
            .map_err(message)?
            .run_to_completion(64, Duration::from_millis(10), None)
            .map_err(message)?;
        destination
            .execute_batch("PRAGMA journal_mode=DELETE;")
            .map_err(message)?;
        verify(&destination)?;
        if schema_version(&destination)? != version {
            return Err("knowledge upgrade backup schema does not match the source".into());
        }
        drop(destination);
        file.sync_all().map_err(message)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&path);
    }
    result?;
    Ok(path)
}

fn message(error: impl std::fmt::Display) -> String {
    error.to_string()
}
