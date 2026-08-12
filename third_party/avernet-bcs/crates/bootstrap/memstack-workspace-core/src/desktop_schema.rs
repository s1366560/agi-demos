//! Versioned SQLite schema for the Desktop Local Workspace extension.

use bcs_db_api::{
    DbError, DbPlugin, DbResult, DbStatement, DbTransactionStep, DbValue, db_get_column,
};

const DESKTOP_SCHEMA_NAME: &str = "memstack_workspace_extension";
const DESKTOP_SCHEMA_MIGRATIONS: &[DesktopSchemaMigration] = &[
    DesktopSchemaMigration {
        version: 1,
        checksum: "0769cf329066d77eb109511da70e23a84c8f7546646cab3ccb03f9885d952822",
        ddl: include_str!("desktop_workspace_schema.sql"),
    },
    DesktopSchemaMigration {
        version: 2,
        checksum: "1bccb0c64aedf17d7edb722f319ae5cbcdff508ec4bb20d33740f0f91300a10e",
        ddl: include_str!("desktop_workspace_schema_v2.sql"),
    },
];

struct DesktopSchemaMigration {
    version: i64,
    checksum: &'static str,
    ddl: &'static str,
}

/// Create and verify the formal Workspace extension schema in Desktop Local SQLite.
///
/// The checked-in DDL is generated from the Alembic-managed PostgreSQL schema.
/// Cloud startup never calls this function and therefore never executes DDL.
pub async fn run_desktop_workspace_schema_migrations(db: &dyn DbPlugin) -> DbResult<()> {
    db.execute(DbStatement::new(
        "CREATE TABLE IF NOT EXISTS workspace_sqlite_schema_migrations (\
         version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, \
         applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    ))
    .await?;
    for migration in DESKTOP_SCHEMA_MIGRATIONS {
        apply_migration(db, migration).await?;
    }
    Ok(())
}

async fn apply_migration(db: &dyn DbPlugin, migration: &DesktopSchemaMigration) -> DbResult<()> {
    let rows = db
        .query(DbStatement::with_params(
            "SELECT name, checksum FROM workspace_sqlite_schema_migrations WHERE version = ?",
            vec![DbValue::from(migration.version)],
        ))
        .await?;
    if let Some(row) = rows.first() {
        let name = db_get_column::<String>(row, "name")?;
        let checksum = db_get_column::<String>(row, "checksum")?;
        if name != DESKTOP_SCHEMA_NAME || checksum != migration.checksum {
            return Err(DbError::InvalidInput(format!(
                "Desktop Workspace SQLite migration checksum mismatch for version {}: \
                 applied={checksum}, current={}",
                migration.version, migration.checksum
            )));
        }
        return Ok(());
    }

    let mut steps = migration
        .ddl
        .split(';')
        .map(str::trim)
        .filter(|statement| !statement.is_empty())
        .filter(|statement| {
            !statement.starts_with("CREATE TABLE IF NOT EXISTS workspace_sqlite_schema_migrations")
        })
        .map(|statement| DbTransactionStep::Execute(DbStatement::new(statement)))
        .collect::<Vec<_>>();
    steps.push(DbTransactionStep::Execute(DbStatement::with_params(
        "INSERT INTO workspace_sqlite_schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
        vec![
            DbValue::from(migration.version),
            DbValue::from(DESKTOP_SCHEMA_NAME),
            DbValue::from(migration.checksum),
        ],
    )));
    db.transaction(steps).await?;
    Ok(())
}
