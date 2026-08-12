//! BCS database plugin contract.
//!
//! This crate defines the infrastructure-facing database extension point used
//! by BCS services. Version 1 is intentionally a SQL-compatible plugin API:
//! it abstracts driver, connection, transaction, health, and row conversion
//! concerns, but it does not promise cross-database query portability. Table
//! names, SQL text, row-to-domain mapping, and persistence semantics remain
//! owned by services.
//!
//! This is a deliberate tradeoff for the current BCS migration because the
//! existing storage code uses MySQL-compatible tables, joins, and upserts.
//! A non-SQL backend or query-id based persistence port should be introduced
//! above this driver-level API, for example as service repositories or an
//! ORM-style layer. Stores that target multiple SQL backends should use
//! [`DbStatementBuilder`] so placeholders are emitted for the selected dialect
//! as parameters are bound. The builder never scans or rewrites raw SQL text.
//!
//! Services that want the same store implementation to run on both local SQLite
//! and MySQL-compatible backends must choose SQL supported by both targets. The shared
//! `db_plugin_contract_tests` in `bcs-test-support` show the small common subset
//! this contract itself relies on: positional `?` parameters, basic
//! `CREATE TABLE`, `INSERT`, `DELETE`, and `SELECT` statements. Backend-specific
//! UPSERTs, joins, and DDL belong in service-owned stores or repository code.

use async_trait::async_trait;
use std::collections::BTreeMap;
use std::fmt::{self, Write as _};
use thiserror::Error;

/// Result type for database plugin operations.
pub type DbResult<T> = Result<T, DbError>;

/// Database plugin failures.
#[derive(Debug, Error)]
pub enum DbError {
    /// The caller provided invalid SQL, parameters, or transaction steps.
    #[error("invalid database input: {0}")]
    InvalidInput(String),

    /// A checked transaction step observed an unexpected row count.
    #[error(
        "transaction step {step_index} expected {expectation} {result_kind} but observed {actual}"
    )]
    TransactionExpectation {
        step_index: usize,
        result_kind: DbTransactionResultKind,
        expectation: DbCountExpectation,
        actual: u64,
    },

    /// The operation is valid for the contract but unsupported by this backend.
    #[error("unsupported database operation: {0}")]
    Unsupported(String),

    /// A returned column could not be converted to the requested type.
    #[error("database value conversion failed: {0}")]
    Conversion(String),

    /// Backend-specific failure.
    #[error("database backend error: {0}")]
    Backend(String),
}

impl DbError {
    /// Returns true if this error represents a unique constraint violation.
    /// Checks MySQL error code 1062 and SQLite "UNIQUE constraint failed".
    pub fn is_duplicate_key(&self) -> bool {
        match self {
            Self::Backend(msg) => {
                msg.contains("1062")
                    || msg.contains("UNIQUE constraint failed")
                    || msg.contains("[23505]")
            }
            _ => false,
        }
    }
}

/// Database scalar value used for SQL parameters and row columns.
#[derive(Debug, Clone, PartialEq)]
pub enum DbValue {
    Null,
    Bool(bool),
    I64(i64),
    U64(u64),
    F64(f64),
    String(String),
    Bytes(Vec<u8>),
}

/// SQL syntax flavor selected by service-owned stores.
///
/// This is not a backend capability negotiation mechanism. `DbPlugin` still
/// receives raw SQL as-is; services use this enum only to choose their own SQL
/// branch when they intentionally support MySQL, local SQLite, and PostgreSQL.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DbSqlFlavor {
    Mysql,
    Sqlite,
    Postgres,
}

impl DbSqlFlavor {
    /// Current timestamp expression for the selected SQL flavor.
    pub fn now(&self) -> &'static str {
        match self {
            Self::Mysql => "NOW()",
            Self::Sqlite | Self::Postgres => "CURRENT_TIMESTAMP",
        }
    }

    /// Convert a source-owned column expression to Unix epoch seconds.
    pub fn unix_ts(&self, col: &str) -> String {
        match self {
            Self::Mysql => format!("UNIX_TIMESTAMP({})", col),
            Self::Sqlite => format!("CAST(strftime('%s',{}) AS INTEGER)", col),
            Self::Postgres => format!("CAST(EXTRACT(EPOCH FROM {}) AS BIGINT)", col),
        }
    }

    /// Legacy first-parameter Unix timestamp conversion expression.
    ///
    /// PostgreSQL callers composing more than one parameter must use
    /// [`DbStatementBuilder`] so bind positions remain correct.
    pub fn from_unix_param(&self) -> &'static str {
        match self {
            Self::Mysql => "FROM_UNIXTIME(?)",
            Self::Sqlite => "datetime(?,'unixepoch')",
            Self::Postgres => "TO_TIMESTAMP($1)",
        }
    }

    /// Ignore-capable INSERT prefix, or plain `INSERT` for PostgreSQL.
    pub fn insert_or_ignore(&self) -> &'static str {
        match self {
            Self::Mysql => "INSERT IGNORE",
            Self::Sqlite => "INSERT OR IGNORE",
            Self::Postgres => "INSERT",
        }
    }

    /// MySQL: "ON DUPLICATE KEY UPDATE col=VALUES(col), extra=val, ..."
    /// SQLite/PostgreSQL: "ON CONFLICT(keys) DO UPDATE SET col=excluded.col, ..."
    pub fn on_conflict_update(
        &self,
        conflict_keys: &[&str],
        update_cols: &[&str],
        extras: &[(&str, &str)],
    ) -> String {
        match self {
            Self::Mysql => {
                let mut parts: Vec<String> = update_cols
                    .iter()
                    .map(|col| format!("{}=VALUES({})", col, col))
                    .collect();
                for (col, val) in extras {
                    parts.push(format!("{}={}", col, val));
                }
                format!("ON DUPLICATE KEY UPDATE {}", parts.join(", "))
            }
            Self::Sqlite | Self::Postgres => {
                let mut parts: Vec<String> = update_cols
                    .iter()
                    .map(|col| format!("{}=excluded.{}", col, col))
                    .collect();
                for (col, val) in extras {
                    parts.push(format!("{}={}", col, val));
                }
                format!(
                    "ON CONFLICT({}) DO UPDATE SET {}",
                    conflict_keys.join(", "),
                    parts.join(", ")
                )
            }
        }
    }

    /// MySQL: "ON DUPLICATE KEY UPDATE <first_key>=<first_key>" (no-op)
    /// SQLite/PostgreSQL: "ON CONFLICT(keys) DO NOTHING"
    pub fn on_conflict_nothing(&self, conflict_keys: &[&str]) -> String {
        match self {
            Self::Mysql => {
                let col = conflict_keys.first().copied().unwrap_or("id");
                format!("ON DUPLICATE KEY UPDATE {}={}", col, col)
            }
            Self::Sqlite | Self::Postgres => {
                format!("ON CONFLICT({}) DO NOTHING", conflict_keys.join(", "))
            }
        }
    }

    /// Conditional expression for the selected SQL flavor.
    pub fn iif(&self, cond: &str, t: &str, f: &str) -> String {
        match self {
            Self::Mysql => format!("IF({}, {}, {})", cond, t, f),
            Self::Sqlite => format!("IIF({}, {}, {})", cond, t, f),
            Self::Postgres => format!("CASE WHEN {} THEN {} ELSE {} END", cond, t, f),
        }
    }

    /// Update the conventional modified-time column to the current timestamp.
    pub fn set_modified_now(&self) -> &'static str {
        match self {
            Self::Mysql => "gmt_modified = NOW()",
            Self::Sqlite | Self::Postgres => "gmt_modified = CURRENT_TIMESTAMP",
        }
    }
}

impl DbValue {
    pub fn as_str(&self) -> Option<&str> {
        match self {
            Self::String(value) => Some(value),
            _ => None,
        }
    }

    pub fn as_i64(&self) -> Option<i64> {
        match self {
            Self::I64(value) => Some(*value),
            Self::U64(value) => i64::try_from(*value).ok(),
            _ => None,
        }
    }

    pub fn as_u64(&self) -> Option<u64> {
        match self {
            Self::U64(value) => Some(*value),
            Self::I64(value) => u64::try_from(*value).ok(),
            _ => None,
        }
    }

    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Self::Bool(value) => Some(*value),
            // SQL backends commonly expose boolean columns as integer values,
            // e.g. MySQL TINYINT(1). Treat zero as false and non-zero as true.
            Self::I64(value) => Some(*value != 0),
            Self::U64(value) => Some(*value != 0),
            _ => None,
        }
    }
}

impl From<&str> for DbValue {
    fn from(value: &str) -> Self {
        Self::String(value.to_string())
    }
}

impl From<String> for DbValue {
    fn from(value: String) -> Self {
        Self::String(value)
    }
}

impl From<bool> for DbValue {
    fn from(value: bool) -> Self {
        Self::Bool(value)
    }
}

impl From<i64> for DbValue {
    fn from(value: i64) -> Self {
        Self::I64(value)
    }
}

impl From<i32> for DbValue {
    fn from(value: i32) -> Self {
        Self::I64(i64::from(value))
    }
}

impl From<u64> for DbValue {
    fn from(value: u64) -> Self {
        Self::U64(value)
    }
}

impl From<u32> for DbValue {
    fn from(value: u32) -> Self {
        Self::U64(u64::from(value))
    }
}

impl From<f64> for DbValue {
    fn from(value: f64) -> Self {
        Self::F64(value)
    }
}

impl From<Vec<u8>> for DbValue {
    fn from(value: Vec<u8>) -> Self {
        Self::Bytes(value)
    }
}

impl From<Option<&str>> for DbValue {
    fn from(value: Option<&str>) -> Self {
        value.map(Self::from).unwrap_or(Self::Null)
    }
}

impl From<Option<String>> for DbValue {
    fn from(value: Option<String>) -> Self {
        value.map(Self::from).unwrap_or(Self::Null)
    }
}

/// One database row keyed by column name.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct DbRow {
    columns: BTreeMap<String, DbValue>,
}

impl DbRow {
    pub fn new(columns: BTreeMap<String, DbValue>) -> Self {
        Self { columns }
    }

    pub fn empty() -> Self {
        Self::default()
    }

    pub fn columns(&self) -> &BTreeMap<String, DbValue> {
        &self.columns
    }

    pub fn get(&self, column: &str) -> Option<&DbValue> {
        self.columns.get(column)
    }

    pub fn get_string(&self, column: &str) -> DbResult<Option<String>> {
        self.get(column)
            .map(|value| match value {
                DbValue::Null => Ok(None),
                DbValue::String(value) => Ok(Some(value.clone())),
                other => Err(DbError::Conversion(format!(
                    "column '{}' is not a string: {:?}",
                    column, other
                ))),
            })
            .unwrap_or(Ok(None))
    }

    pub fn get_i64(&self, column: &str) -> DbResult<Option<i64>> {
        self.get(column)
            .map(|value| {
                if matches!(value, DbValue::Null) {
                    Ok(None)
                } else {
                    value.as_i64().map(Some).ok_or_else(|| {
                        DbError::Conversion(format!(
                            "column '{}' is not an i64: {:?}",
                            column, value
                        ))
                    })
                }
            })
            .unwrap_or(Ok(None))
    }

    pub fn get_bool(&self, column: &str) -> DbResult<Option<bool>> {
        self.get(column)
            .map(|value| {
                if matches!(value, DbValue::Null) {
                    Ok(None)
                } else {
                    value.as_bool().map(Some).ok_or_else(|| {
                        DbError::Conversion(format!(
                            "column '{}' is not a bool: {:?}",
                            column, value
                        ))
                    })
                }
            })
            .unwrap_or(Ok(None))
    }

    pub fn get_bytes(&self, column: &str) -> DbResult<Option<Vec<u8>>> {
        self.get(column)
            .map(|value| match value {
                DbValue::Null => Ok(None),
                DbValue::Bytes(value) => Ok(Some(value.clone())),
                other => Err(DbError::Conversion(format!(
                    "column '{}' is not bytes: {:?}",
                    column, other
                ))),
            })
            .unwrap_or(Ok(None))
    }
}

/// SQL statement plus positional parameters.
#[derive(Debug, Clone, PartialEq)]
pub struct DbStatement {
    sql: String,
    params: Vec<DbValue>,
}

impl DbStatement {
    /// Create a SQL statement without positional parameters.
    ///
    /// The SQL text is passed to the selected backend as-is. Callers are
    /// responsible for using syntax supported by that backend. If the same
    /// caller must run against both local SQLite and MySQL-compatible backends, keep the SQL
    /// to the documented common subset or isolate dialect-specific SQL in a
    /// service-owned store/repository.
    pub fn new(sql: impl Into<String>) -> Self {
        Self {
            sql: sql.into(),
            params: Vec::new(),
        }
    }

    /// Create a SQL statement with positional parameters.
    ///
    /// The SQL text is passed to the selected backend as-is. Callers are
    /// responsible for using syntax supported by that backend. If the same
    /// caller must run against both local SQLite and MySQL-compatible backends, keep the SQL
    /// to the documented common subset or isolate dialect-specific SQL in a
    /// service-owned store/repository.
    pub fn with_params(sql: impl Into<String>, params: Vec<DbValue>) -> Self {
        Self {
            sql: sql.into(),
            params,
        }
    }

    pub fn sql(&self) -> &str {
        &self.sql
    }

    pub fn params(&self) -> &[DbValue] {
        &self.params
    }

    pub fn into_params(self) -> Vec<DbValue> {
        self.params
    }
}

/// A source-owned SQL identifier accepted by [`DbStatementBuilder`].
///
/// Identifiers are restricted to portable unquoted names: an ASCII letter or
/// underscore followed by ASCII letters, digits, or underscores. The
/// constructor requires a static string so request data cannot become SQL
/// structure. Qualified names must be composed from separate identifiers and
/// a static `.` fragment.
///
/// # Examples
///
/// ```
/// use bcs_db_api::DbIdentifier;
///
/// let table = DbIdentifier::new_static("workspace_tasks")?;
/// assert_eq!(table.as_str(), "workspace_tasks");
/// # Ok::<(), bcs_db_api::DbError>(())
/// ```
///
/// Runtime strings are intentionally rejected by the type signature:
///
/// ```compile_fail
/// use bcs_db_api::DbIdentifier;
///
/// let user_supplied = String::from("workspace_tasks");
/// let _ = DbIdentifier::new_static(&user_supplied);
/// ```
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DbIdentifier(&'static str);

impl DbIdentifier {
    /// Validate a source-owned, unquoted SQL identifier.
    ///
    /// # Errors
    ///
    /// Returns [`DbError::InvalidInput`] when `identifier` is empty, starts
    /// with a digit, or contains characters outside ASCII letters, digits,
    /// and underscore.
    pub fn new_static(identifier: &'static str) -> DbResult<Self> {
        let mut bytes = identifier.bytes();
        let Some(first) = bytes.next() else {
            return Err(DbError::InvalidInput(
                "database identifier is empty".to_string(),
            ));
        };
        if !(first.is_ascii_alphabetic() || first == b'_')
            || !bytes.all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
        {
            return Err(DbError::InvalidInput(format!(
                "invalid static database identifier: {}",
                identifier
            )));
        }
        Ok(Self(identifier))
    }

    /// Return the validated identifier text.
    pub fn as_str(&self) -> &'static str {
        self.0
    }
}

/// Builds a [`DbStatement`] without rewriting SQL text.
///
/// Static SQL fragments and validated identifiers define statement structure.
/// [`Self::bind`] emits `$1`, `$2`, ... for PostgreSQL and `?` for MySQL and
/// SQLite while preserving each supplied [`DbValue`].
///
/// # Examples
///
/// ```
/// use bcs_db_api::{DbIdentifier, DbSqlFlavor, DbStatementBuilder, DbValue};
///
/// # fn main() -> Result<(), bcs_db_api::DbError> {
/// let table = DbIdentifier::new_static("workspace_tasks")?;
/// let statement = DbStatementBuilder::new(DbSqlFlavor::Postgres)
///     .push_static("SELECT * FROM ")
///     .push_identifier(table)
///     .push_static(" WHERE task_id = ")
///     .bind("task-1")
///     .build();
/// assert_eq!(statement.sql(), "SELECT * FROM workspace_tasks WHERE task_id = $1");
/// assert_eq!(statement.params(), &[DbValue::String("task-1".to_string())]);
/// # Ok(())
/// # }
/// ```
#[derive(Debug, Clone)]
#[must_use = "statement builders do nothing unless build() is called"]
pub struct DbStatementBuilder {
    flavor: DbSqlFlavor,
    sql: String,
    params: Vec<DbValue>,
}

impl DbStatementBuilder {
    /// Create an empty statement builder for `flavor`.
    pub fn new(flavor: DbSqlFlavor) -> Self {
        Self {
            flavor,
            sql: String::new(),
            params: Vec::new(),
        }
    }

    /// Append a source-owned SQL fragment without inspecting or rewriting it.
    ///
    /// Requiring a static string prevents request data from being appended as
    /// SQL structure. Dynamic values must use [`Self::bind`].
    #[must_use = "builder methods return a modified builder"]
    pub fn push_static(mut self, fragment: &'static str) -> Self {
        self.sql.push_str(fragment);
        self
    }

    /// Append a validated, source-owned identifier.
    #[must_use = "builder methods return a modified builder"]
    pub fn push_identifier(mut self, identifier: DbIdentifier) -> Self {
        self.sql.push_str(identifier.as_str());
        self
    }

    /// Append the next dialect-specific placeholder and its typed value.
    #[must_use = "builder methods return a modified builder"]
    pub fn bind(mut self, value: impl Into<DbValue>) -> Self {
        self.params.push(value.into());
        match self.flavor {
            DbSqlFlavor::Mysql | DbSqlFlavor::Sqlite => self.sql.push('?'),
            DbSqlFlavor::Postgres => {
                let result = write!(&mut self.sql, "${}", self.params.len());
                debug_assert!(result.is_ok(), "writing to a String cannot fail");
            }
        }
        self
    }

    /// Finish the builder and return the SQL statement with its parameters.
    #[must_use]
    pub fn build(self) -> DbStatement {
        DbStatement::with_params(self.sql, self.params)
    }
}

/// Result of an INSERT/UPDATE/DELETE statement.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct DbExecuteResult {
    /// Number of rows affected using the backend's native semantics.
    ///
    /// MySQL-compatible backends preserve `INSERT ... ON DUPLICATE KEY UPDATE`
    /// affected-row behavior (`1` inserted, `2` updated, `0` no change unless
    /// the connection is configured with found-rows semantics).
    pub affected_rows: u64,
    /// Last auto-increment id when the backend can report it for this
    /// statement. Backends that only expose connection-scoped stale values
    /// should return `None`.
    pub last_insert_id: Option<u64>,
}

/// Expected cardinality for a checked transaction step.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DbCountExpectation {
    Exactly(u64),
    AtLeast(u64),
    AtMost(u64),
}

impl DbCountExpectation {
    #[must_use]
    pub const fn exactly(count: u64) -> Self {
        Self::Exactly(count)
    }

    #[must_use]
    pub const fn at_least(count: u64) -> Self {
        Self::AtLeast(count)
    }

    #[must_use]
    pub const fn at_most(count: u64) -> Self {
        Self::AtMost(count)
    }

    #[must_use]
    pub const fn accepts(self, actual: u64) -> bool {
        match self {
            Self::Exactly(expected) => actual == expected,
            Self::AtLeast(expected) => actual >= expected,
            Self::AtMost(expected) => actual <= expected,
        }
    }

    /// Validate an observed transaction result count.
    ///
    /// # Errors
    ///
    /// Returns [`DbError::TransactionExpectation`] when `actual` does not
    /// satisfy this expectation.
    pub fn verify(
        self,
        step_index: usize,
        result_kind: DbTransactionResultKind,
        actual: u64,
    ) -> DbResult<()> {
        if self.accepts(actual) {
            return Ok(());
        }
        Err(DbError::TransactionExpectation {
            step_index,
            result_kind,
            expectation: self,
            actual,
        })
    }

    /// Validate a platform-sized count without a narrowing cast.
    ///
    /// # Errors
    ///
    /// Returns [`DbError::InvalidInput`] when the count cannot be represented
    /// as `u64`, or [`DbError::TransactionExpectation`] when it does not match.
    pub fn verify_usize(
        self,
        step_index: usize,
        result_kind: DbTransactionResultKind,
        actual: usize,
    ) -> DbResult<()> {
        let actual = u64::try_from(actual).map_err(|_| {
            DbError::InvalidInput("transaction result count exceeds u64".to_string())
        })?;
        self.verify(step_index, result_kind, actual)
    }
}

impl fmt::Display for DbCountExpectation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Exactly(count) => write!(formatter, "exactly {count}"),
            Self::AtLeast(count) => write!(formatter, "at least {count}"),
            Self::AtMost(count) => write!(formatter, "at most {count}"),
        }
    }
}

/// Count produced by a checked transaction step.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DbTransactionResultKind {
    Rows,
    AffectedRows,
}

impl fmt::Display for DbTransactionResultKind {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Rows => formatter.write_str("rows"),
            Self::AffectedRows => formatter.write_str("affected rows"),
        }
    }
}

/// A single transaction step.
#[derive(Debug, Clone, PartialEq)]
pub enum DbTransactionStep {
    /// Query within a transaction. Returning zero rows is still success.
    ///
    /// This supports read-before-write and `SELECT ... FOR UPDATE` style flows.
    /// Callers must validate cardinality themselves when "no rows" is a
    /// business failure.
    Query(DbStatement),
    Execute(DbStatement),
    /// Query and roll back the transaction unless the returned row count
    /// satisfies `expected_rows`.
    QueryChecked {
        statement: DbStatement,
        expected_rows: DbCountExpectation,
    },
    /// Execute and roll back the transaction unless the affected-row count
    /// satisfies `expected_affected_rows`.
    ExecuteChecked {
        statement: DbStatement,
        expected_affected_rows: DbCountExpectation,
    },
}

impl DbTransactionStep {
    #[must_use]
    pub fn query_checked(statement: DbStatement, expected_rows: DbCountExpectation) -> Self {
        Self::QueryChecked {
            statement,
            expected_rows,
        }
    }

    #[must_use]
    pub fn execute_checked(
        statement: DbStatement,
        expected_affected_rows: DbCountExpectation,
    ) -> Self {
        Self::ExecuteChecked {
            statement,
            expected_affected_rows,
        }
    }
}

/// Result for a single transaction step.
#[derive(Debug, Clone, PartialEq)]
pub enum DbTransactionStepResult {
    Rows(Vec<DbRow>),
    Executed(DbExecuteResult),
}

/// Database health status.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DbHealth {
    pub healthy: bool,
    pub message: Option<String>,
}

impl DbHealth {
    pub fn healthy() -> Self {
        Self {
            healthy: true,
            message: None,
        }
    }

    pub fn unhealthy(message: impl Into<String>) -> Self {
        Self {
            healthy: false,
            message: Some(message.into()),
        }
    }
}

/// Database plugin contract.
///
/// A `DbPlugin` instance is expected to be bound to one configured logical
/// datasource by the composition root. Services should not know concrete
/// provider-specific backend names or datasource IDs.
#[async_trait]
pub trait DbPlugin: Send + Sync + 'static {
    /// Run a SELECT-like statement and return named rows.
    async fn query(&self, statement: DbStatement) -> DbResult<Vec<DbRow>>;

    /// Run an INSERT/UPDATE/DELETE-like statement.
    async fn execute(&self, statement: DbStatement) -> DbResult<DbExecuteResult>;

    /// Run execute statements in order without transaction semantics.
    ///
    /// Implementations must stop at the first failed statement and return that
    /// error. Statements already executed are not rolled back; callers needing
    /// all-or-nothing behavior must use [`Self::transaction`].
    async fn execute_batch(&self, statements: Vec<DbStatement>) -> DbResult<Vec<DbExecuteResult>> {
        let mut results = Vec::with_capacity(statements.len());
        for statement in statements {
            results.push(self.execute(statement).await?);
        }
        Ok(results)
    }

    /// Run steps inside one backend transaction.
    ///
    /// Implementations must commit only when every step succeeds and must roll
    /// back when any step fails. A query returning zero rows is a successful
    /// step; it is the caller's job to interpret empty result sets.
    async fn transaction(
        &self,
        steps: Vec<DbTransactionStep>,
    ) -> DbResult<Vec<DbTransactionStepResult>>;

    /// Return whether this plugin can reach its backend.
    async fn health_check(&self) -> DbResult<DbHealth>;
}

pub fn db_get_column<T: FromDbColumn>(row: &DbRow, column: &str) -> DbResult<T> {
    db_get_column_opt(row, column)?
        .ok_or_else(|| DbError::Conversion(format!("column '{}' is missing or NULL", column)))
}

pub fn db_get_column_opt<T: FromDbColumn>(row: &DbRow, column: &str) -> DbResult<Option<T>> {
    row.get(column)
        .map(|value| {
            if matches!(value, DbValue::Null) {
                Ok(None)
            } else {
                T::from_db_value(column, value).map(Some)
            }
        })
        .unwrap_or(Ok(None))
}

pub trait FromDbColumn: Sized {
    fn from_db_value(column: &str, value: &DbValue) -> DbResult<Self>;
}

impl FromDbColumn for String {
    fn from_db_value(column: &str, value: &DbValue) -> DbResult<Self> {
        match value {
            DbValue::String(value) => Ok(value.clone()),
            DbValue::Bytes(value) => String::from_utf8(value.clone()).map_err(|err| {
                DbError::Conversion(format!("column '{}' is not valid UTF-8: {}", column, err))
            }),
            other => Err(DbError::Conversion(format!(
                "column '{}' is not a string: {:?}",
                column, other
            ))),
        }
    }
}

impl FromDbColumn for i64 {
    fn from_db_value(column: &str, value: &DbValue) -> DbResult<Self> {
        value.as_i64().ok_or_else(|| {
            DbError::Conversion(format!("column '{}' is not an i64: {:?}", column, value))
        })
    }
}

impl FromDbColumn for i32 {
    fn from_db_value(column: &str, value: &DbValue) -> DbResult<Self> {
        let value = value.as_i64().ok_or_else(|| {
            DbError::Conversion(format!("column '{}' is not an i32: {:?}", column, value))
        })?;
        i32::try_from(value).map_err(|err| {
            DbError::Conversion(format!("column '{}' is out of i32 range: {}", column, err))
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    fn must<T>(result: DbResult<T>) -> T {
        match result {
            Ok(value) => value,
            Err(err) => panic!("expected Ok, got {}", err),
        }
    }

    #[test]
    fn db_plugin_is_object_safe() {
        fn _assert<T: DbPlugin>() {}
        fn _assert_dyn(_: Arc<dyn DbPlugin>) {}
    }

    #[test]
    fn db_row_typed_getters_are_predictable() {
        let row = DbRow::new(BTreeMap::from([
            ("name".to_string(), DbValue::from("alice")),
            ("count".to_string(), DbValue::from(3_i64)),
            ("big".to_string(), DbValue::from(i64::from(i32::MAX) + 1)),
            ("enabled".to_string(), DbValue::from(true)),
            ("payload".to_string(), DbValue::from(b"blob".to_vec())),
        ]));

        assert_eq!(must(row.get_string("name")), Some("alice".to_string()));
        assert_eq!(must(row.get_i64("count")), Some(3));
        assert_eq!(must(row.get_bool("enabled")), Some(true));
        assert_eq!(must(row.get_bytes("payload")), Some(b"blob".to_vec()));
        assert_eq!(must(row.get_string("missing")), None);
        assert_eq!(must(db_get_column::<String>(&row, "name")), "alice");
        assert_eq!(must(db_get_column_opt::<i64>(&row, "count")), Some(3));
        assert_eq!(must(db_get_column::<i32>(&row, "count")), 3);
        assert!(matches!(
            db_get_column::<i32>(&row, "big"),
            Err(DbError::Conversion(_))
        ));
    }

    #[test]
    fn db_sql_flavor_now() {
        assert_eq!(DbSqlFlavor::Mysql.now(), "NOW()");
        assert_eq!(DbSqlFlavor::Sqlite.now(), "CURRENT_TIMESTAMP");
    }

    #[test]
    fn db_sql_flavor_insert_or_ignore() {
        assert_eq!(DbSqlFlavor::Mysql.insert_or_ignore(), "INSERT IGNORE");
        assert_eq!(DbSqlFlavor::Sqlite.insert_or_ignore(), "INSERT OR IGNORE");
    }

    #[test]
    fn db_sql_flavor_on_conflict_update_mysql() {
        let sql = DbSqlFlavor::Mysql.on_conflict_update(
            &["group_id", "env"],
            &["status", "driver_bot"],
            &[("gmt_modified", "NOW()")],
        );
        assert_eq!(
            sql,
            "ON DUPLICATE KEY UPDATE status=VALUES(status), driver_bot=VALUES(driver_bot), gmt_modified=NOW()"
        );
    }

    #[test]
    fn db_sql_flavor_on_conflict_update_sqlite() {
        let sql = DbSqlFlavor::Sqlite.on_conflict_update(
            &["group_id", "env"],
            &["status", "driver_bot"],
            &[("gmt_modified", "CURRENT_TIMESTAMP")],
        );
        assert_eq!(
            sql,
            "ON CONFLICT(group_id, env) DO UPDATE SET status=excluded.status, driver_bot=excluded.driver_bot, gmt_modified=CURRENT_TIMESTAMP"
        );
    }

    #[test]
    fn db_sql_flavor_on_conflict_nothing() {
        assert_eq!(
            DbSqlFlavor::Mysql.on_conflict_nothing(&["group_id", "env"]),
            "ON DUPLICATE KEY UPDATE group_id=group_id"
        );
        assert_eq!(
            DbSqlFlavor::Sqlite.on_conflict_nothing(&["group_id", "env"]),
            "ON CONFLICT(group_id, env) DO NOTHING"
        );
    }

    #[test]
    fn db_sql_flavor_iif() {
        assert_eq!(DbSqlFlavor::Mysql.iif("a", "b", "c"), "IF(a, b, c)");
        assert_eq!(DbSqlFlavor::Sqlite.iif("a", "b", "c"), "IIF(a, b, c)");
    }

    #[test]
    fn db_sql_flavor_unix_ts() {
        assert_eq!(
            DbSqlFlavor::Mysql.unix_ts("gmt_create"),
            "UNIX_TIMESTAMP(gmt_create)"
        );
        assert_eq!(
            DbSqlFlavor::Sqlite.unix_ts("gmt_create"),
            "CAST(strftime('%s',gmt_create) AS INTEGER)"
        );
    }

    #[test]
    fn db_sql_flavor_from_unix_param() {
        assert_eq!(DbSqlFlavor::Mysql.from_unix_param(), "FROM_UNIXTIME(?)");
        assert_eq!(
            DbSqlFlavor::Sqlite.from_unix_param(),
            "datetime(?,'unixepoch')"
        );
    }

    #[test]
    fn db_sql_flavor_set_modified_now() {
        assert_eq!(
            DbSqlFlavor::Mysql.set_modified_now(),
            "gmt_modified = NOW()"
        );
        assert_eq!(
            DbSqlFlavor::Sqlite.set_modified_now(),
            "gmt_modified = CURRENT_TIMESTAMP"
        );
    }

    #[test]
    fn db_error_is_duplicate_key_mysql() {
        let err = DbError::Backend("Error 1062: Duplicate entry".to_string());
        assert!(err.is_duplicate_key());
    }

    #[test]
    fn db_error_is_duplicate_key_sqlite() {
        let err = DbError::Backend("UNIQUE constraint failed: bcs_bots.uk_bot_env".to_string());
        assert!(err.is_duplicate_key());
    }

    #[test]
    fn db_error_is_duplicate_key_false() {
        let err = DbError::Backend("connection refused".to_string());
        assert!(!err.is_duplicate_key());
    }

    #[test]
    fn transaction_count_expectations_accept_only_matching_counts() {
        assert!(DbCountExpectation::exactly(2).accepts(2));
        assert!(!DbCountExpectation::exactly(2).accepts(1));
        assert!(DbCountExpectation::at_least(2).accepts(3));
        assert!(!DbCountExpectation::at_least(2).accepts(1));
        assert!(DbCountExpectation::at_most(2).accepts(1));
        assert!(!DbCountExpectation::at_most(2).accepts(3));
    }

    #[test]
    fn transaction_count_expectation_returns_typed_failure() {
        let result =
            DbCountExpectation::exactly(1).verify(3, DbTransactionResultKind::AffectedRows, 0);

        assert!(matches!(
            result,
            Err(DbError::TransactionExpectation {
                step_index: 3,
                result_kind: DbTransactionResultKind::AffectedRows,
                expectation: DbCountExpectation::Exactly(1),
                actual: 0,
            })
        ));
    }

    #[test]
    fn checked_transaction_step_constructors_preserve_expectations() {
        let query = DbTransactionStep::query_checked(
            DbStatement::new("SELECT 1"),
            DbCountExpectation::exactly(1),
        );
        let execute = DbTransactionStep::execute_checked(
            DbStatement::new("UPDATE items SET active = 1"),
            DbCountExpectation::at_least(1),
        );

        assert!(matches!(
            query,
            DbTransactionStep::QueryChecked {
                expected_rows: DbCountExpectation::Exactly(1),
                ..
            }
        ));
        assert!(matches!(
            execute,
            DbTransactionStep::ExecuteChecked {
                expected_affected_rows: DbCountExpectation::AtLeast(1),
                ..
            }
        ));
    }

    #[test]
    fn db_sql_flavor_postgres_uses_native_syntax() {
        let flavor = DbSqlFlavor::Postgres;

        assert_eq!(flavor.now(), "CURRENT_TIMESTAMP");
        assert_eq!(
            flavor.unix_ts("gmt_create"),
            "CAST(EXTRACT(EPOCH FROM gmt_create) AS BIGINT)"
        );
        assert_eq!(flavor.from_unix_param(), "TO_TIMESTAMP($1)");
        assert_eq!(flavor.insert_or_ignore(), "INSERT");
        assert_eq!(
            flavor.on_conflict_update(
                &["group_id", "env"],
                &["status"],
                &[("gmt_modified", "CURRENT_TIMESTAMP")],
            ),
            "ON CONFLICT(group_id, env) DO UPDATE SET status=excluded.status, gmt_modified=CURRENT_TIMESTAMP"
        );
        assert_eq!(
            flavor.on_conflict_nothing(&["group_id", "env"]),
            "ON CONFLICT(group_id, env) DO NOTHING"
        );
        assert_eq!(
            flavor.iif("ready", "accepted", "rejected"),
            "CASE WHEN ready THEN accepted ELSE rejected END"
        );
        assert_eq!(
            flavor.set_modified_now(),
            "gmt_modified = CURRENT_TIMESTAMP"
        );
    }

    #[test]
    fn statement_builder_numbers_postgres_bind_parameters() {
        let statement = DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("SELECT ")
            .bind("alice")
            .push_static(", ")
            .bind(42_i64)
            .build();

        assert_eq!(statement.sql(), "SELECT $1, $2");
        assert_eq!(
            statement.params(),
            &[DbValue::String("alice".to_string()), DbValue::I64(42)]
        );
    }

    #[test]
    fn statement_builder_uses_question_mark_for_mysql_and_sqlite() {
        for flavor in [DbSqlFlavor::Mysql, DbSqlFlavor::Sqlite] {
            let statement = DbStatementBuilder::new(flavor)
                .push_static("SELECT ")
                .bind(true)
                .push_static(", ")
                .bind(7_u64)
                .build();

            assert_eq!(statement.sql(), "SELECT ?, ?");
            assert_eq!(statement.params(), &[DbValue::Bool(true), DbValue::U64(7)]);
        }
    }

    #[test]
    fn statement_builder_does_not_rewrite_question_mark_literals() {
        let statement = DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("SELECT '?' AS question_mark, ")
            .bind("answer")
            .build();

        assert_eq!(statement.sql(), "SELECT '?' AS question_mark, $1");
        assert_eq!(statement.params(), &[DbValue::String("answer".to_string())]);
    }

    #[test]
    fn statement_builder_preserves_explicit_db_value_variants() {
        let bytes = vec![0_u8, 1, 2];
        let statement = DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("SELECT ")
            .bind(DbValue::Null)
            .push_static(", ")
            .bind(DbValue::Bytes(bytes.clone()))
            .build();

        assert_eq!(statement.params(), &[DbValue::Null, DbValue::Bytes(bytes)]);
    }

    #[test]
    fn statement_builder_composes_validated_static_identifiers() {
        let table = must(DbIdentifier::new_static("workspace_tasks"));
        let column = must(DbIdentifier::new_static("task_id"));
        let statement = DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("SELECT ")
            .push_identifier(column)
            .push_static(" FROM ")
            .push_identifier(table)
            .push_static(" WHERE task_id = ")
            .bind("task-1")
            .build();

        assert_eq!(
            statement.sql(),
            "SELECT task_id FROM workspace_tasks WHERE task_id = $1"
        );
        assert!(matches!(
            DbIdentifier::new_static("workspace_tasks; DROP TABLE workspace_tasks"),
            Err(DbError::InvalidInput(_))
        ));
        assert!(matches!(
            DbIdentifier::new_static("workspace.tasks"),
            Err(DbError::InvalidInput(_))
        ));
    }
}
