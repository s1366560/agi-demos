//! PostgreSQL implementation of the `bcs-db-api` contract.
//!
//! Statements are executed exactly as supplied. Callers must use
//! `DbStatementBuilder` with `DbSqlFlavor::Postgres`; this adapter never scans
//! or rewrites SQL placeholders.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::io;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use bcs_db_api::{
    DbError, DbExecuteResult, DbHealth, DbPlugin, DbResult, DbRow, DbStatement,
    DbTransactionResultKind, DbTransactionStep, DbTransactionStepResult, DbValue,
};
use bytes::BytesMut;
use chrono::{DateTime, NaiveDate, NaiveDateTime, NaiveTime, SecondsFormat, Utc};
use postgres_native_tls::MakeTlsConnector;
use tokio::sync::{Mutex, MutexGuard};
use tokio_postgres::config::SslMode;
use tokio_postgres::types::{FromSqlOwned, IsNull, Json, Kind, ToSql, Type, to_sql_checked};
use tokio_postgres::{Client, Config, NoTls, Row};
use tracing::error;

const DEFAULT_POOL_SIZE: usize = 16;
const WORKSPACE_SEARCH_PATH_OPTIONS: &str = "-c search_path=avernet,public";

#[derive(Clone)]
pub struct PostgresDbPlugin {
    pool: Arc<PostgresClientPool>,
}

struct PostgresClientPool {
    clients: Vec<Mutex<Client>>,
    next: AtomicUsize,
}

impl PostgresDbPlugin {
    /// Connect using the platform TLS trust store.
    ///
    /// `database_url` may select `sslmode=disable` for local development. The
    /// production default should require TLS in deployment configuration.
    pub async fn connect(database_url: &str, max_connections: usize) -> DbResult<Self> {
        let config = parse_config(database_url)?;
        let pool_size = checked_pool_size(max_connections)?;
        let connector = native_tls::TlsConnector::builder()
            .build()
            .map_err(|error| DbError::Backend(format!("build postgres TLS connector: {error}")))?;
        let mut clients = Vec::with_capacity(pool_size);
        for _ in 0..pool_size {
            let tls = MakeTlsConnector::new(connector.clone());
            let (client, connection) = config
                .connect(tls)
                .await
                .map_err(|error| postgres_error("connect", error))?;
            tokio::spawn(async move {
                if let Err(connection_error) = connection.await {
                    error!(error = %connection_error, "PostgreSQL connection task stopped");
                }
            });
            clients.push(Mutex::new(client));
        }
        Ok(Self::from_clients(clients))
    }

    /// Connect without TLS. Intended for isolated local tests only.
    pub async fn connect_no_tls(database_url: &str, max_connections: usize) -> DbResult<Self> {
        let mut config = parse_config(database_url)?;
        config.ssl_mode(SslMode::Disable);
        let pool_size = checked_pool_size(max_connections)?;
        let mut clients = Vec::with_capacity(pool_size);
        for _ in 0..pool_size {
            let (client, connection) = config
                .connect(NoTls)
                .await
                .map_err(|error| postgres_error("connect without TLS", error))?;
            tokio::spawn(async move {
                if let Err(connection_error) = connection.await {
                    error!(error = %connection_error, "PostgreSQL connection task stopped");
                }
            });
            clients.push(Mutex::new(client));
        }
        Ok(Self::from_clients(clients))
    }

    pub async fn connect_default(database_url: &str) -> DbResult<Self> {
        Self::connect(database_url, DEFAULT_POOL_SIZE).await
    }

    fn from_clients(clients: Vec<Mutex<Client>>) -> Self {
        Self {
            pool: Arc::new(PostgresClientPool {
                clients,
                next: AtomicUsize::new(0),
            }),
        }
    }

    async fn client(&self) -> MutexGuard<'_, Client> {
        let index = self.pool.next.fetch_add(1, Ordering::Relaxed) % self.pool.clients.len();
        self.pool.clients[index].lock().await
    }
}

#[async_trait]
impl DbPlugin for PostgresDbPlugin {
    async fn query(&self, statement: DbStatement) -> DbResult<Vec<DbRow>> {
        let client = self.client().await;
        query_with_client(&client, &statement).await
    }

    async fn execute(&self, statement: DbStatement) -> DbResult<DbExecuteResult> {
        let client = self.client().await;
        execute_with_client(&client, &statement).await
    }

    async fn transaction(
        &self,
        steps: Vec<DbTransactionStep>,
    ) -> DbResult<Vec<DbTransactionStepResult>> {
        let mut client = self.client().await;
        let transaction = client
            .transaction()
            .await
            .map_err(|error| postgres_error("begin transaction", error))?;
        let mut results = Vec::with_capacity(steps.len());
        for (step_index, step) in steps.into_iter().enumerate() {
            match step {
                DbTransactionStep::Query(statement) => {
                    let params = postgres_params(statement.params());
                    let refs = postgres_param_refs(&params);
                    let rows = transaction
                        .query(statement.sql(), &refs)
                        .await
                        .map_err(|error| postgres_error("transaction query", error))?;
                    results.push(DbTransactionStepResult::Rows(
                        rows.into_iter()
                            .map(row_to_db_row)
                            .collect::<DbResult<Vec<_>>>()?,
                    ));
                }
                DbTransactionStep::Execute(statement) => {
                    let params = postgres_params(statement.params());
                    let refs = postgres_param_refs(&params);
                    let affected_rows = transaction
                        .execute(statement.sql(), &refs)
                        .await
                        .map_err(|error| postgres_error("transaction execute", error))?;
                    results.push(DbTransactionStepResult::Executed(DbExecuteResult {
                        affected_rows,
                        last_insert_id: None,
                    }));
                }
                DbTransactionStep::QueryChecked {
                    statement,
                    expected_rows,
                } => {
                    let params = postgres_params(statement.params());
                    let refs = postgres_param_refs(&params);
                    let rows = transaction
                        .query(statement.sql(), &refs)
                        .await
                        .map_err(|error| postgres_error("transaction checked query", error))?;
                    expected_rows.verify_usize(
                        step_index,
                        DbTransactionResultKind::Rows,
                        rows.len(),
                    )?;
                    results.push(DbTransactionStepResult::Rows(
                        rows.into_iter()
                            .map(row_to_db_row)
                            .collect::<DbResult<Vec<_>>>()?,
                    ));
                }
                DbTransactionStep::ExecuteChecked {
                    statement,
                    expected_affected_rows,
                } => {
                    let params = postgres_params(statement.params());
                    let refs = postgres_param_refs(&params);
                    let affected_rows = transaction
                        .execute(statement.sql(), &refs)
                        .await
                        .map_err(|error| postgres_error("transaction checked execute", error))?;
                    expected_affected_rows.verify(
                        step_index,
                        DbTransactionResultKind::AffectedRows,
                        affected_rows,
                    )?;
                    results.push(DbTransactionStepResult::Executed(DbExecuteResult {
                        affected_rows,
                        last_insert_id: None,
                    }));
                }
            }
        }
        transaction
            .commit()
            .await
            .map_err(|error| postgres_error("commit transaction", error))?;
        Ok(results)
    }

    async fn health_check(&self) -> DbResult<DbHealth> {
        let rows = self.query(DbStatement::new("SELECT 1 AS ok")).await?;
        if rows.len() == 1 {
            Ok(DbHealth::healthy())
        } else {
            Ok(DbHealth::unhealthy(
                "postgres health query returned no rows",
            ))
        }
    }
}

async fn query_with_client(client: &Client, statement: &DbStatement) -> DbResult<Vec<DbRow>> {
    let params = postgres_params(statement.params());
    let refs = postgres_param_refs(&params);
    client
        .query(statement.sql(), &refs)
        .await
        .map_err(|error| postgres_error("query", error))?
        .into_iter()
        .map(row_to_db_row)
        .collect()
}

async fn execute_with_client(
    client: &Client,
    statement: &DbStatement,
) -> DbResult<DbExecuteResult> {
    let params = postgres_params(statement.params());
    let refs = postgres_param_refs(&params);
    let affected_rows = client
        .execute(statement.sql(), &refs)
        .await
        .map_err(|error| postgres_error("execute", error))?;
    Ok(DbExecuteResult {
        affected_rows,
        last_insert_id: None,
    })
}

fn parse_config(database_url: &str) -> DbResult<Config> {
    let mut config: Config = database_url.parse().map_err(|error| {
        DbError::InvalidInput(format!("invalid postgres connection config: {error}"))
    })?;
    // Require TLS unless the caller explicitly selects `sslmode=disable` for
    // an isolated local environment. In particular, PostgreSQL's `prefer`
    // default must not silently downgrade a production connection.
    if config.get_ssl_mode() != SslMode::Disable {
        config.ssl_mode(SslMode::Require);
    }
    // BCS statements intentionally use static, unqualified table names. Pinning
    // the search path here keeps all BCS data in the platform-owned schema and
    // prevents a connection URL from redirecting those statements elsewhere.
    config.options(WORKSPACE_SEARCH_PATH_OPTIONS);
    Ok(config)
}

fn checked_pool_size(max_connections: usize) -> DbResult<usize> {
    if max_connections == 0 {
        return Err(DbError::InvalidInput(
            "postgres max_connections must be greater than zero".to_string(),
        ));
    }
    Ok(max_connections)
}

fn postgres_error(action: &str, error: tokio_postgres::Error) -> DbError {
    match error.code() {
        Some(code) => DbError::Backend(format!("postgres {action} [{}]: {error}", code.code())),
        None => DbError::Backend(format!("postgres {action}: {error}")),
    }
}

#[derive(Debug)]
struct PostgresValue<'a>(&'a DbValue);

impl ToSql for PostgresValue<'_> {
    fn to_sql(
        &self,
        ty: &Type,
        out: &mut BytesMut,
    ) -> Result<IsNull, Box<dyn StdError + Sync + Send>> {
        match self.0 {
            DbValue::Null => Ok(IsNull::Yes),
            DbValue::Bool(value) if *ty == Type::BOOL => value.to_sql(ty, out),
            DbValue::I64(value) => encode_i64(*value, ty, out),
            DbValue::U64(value) => {
                let value = i64::try_from(*value).map_err(|_| {
                    invalid_value(format!(
                        "u64 value is out of PostgreSQL signed range: {value}"
                    ))
                })?;
                encode_i64(value, ty, out)
            }
            DbValue::F64(value) if *ty == Type::FLOAT8 => value.to_sql(ty, out),
            DbValue::F64(value) if *ty == Type::FLOAT4 => {
                let value = value.to_string().parse::<f32>().map_err(|error| {
                    invalid_value(format!("f64 value cannot be encoded as float4: {error}"))
                })?;
                value.to_sql(ty, out)
            }
            DbValue::String(value) => encode_string(value, ty, out),
            DbValue::Bytes(value) if *ty == Type::BYTEA => value.to_sql(ty, out),
            value => Err(invalid_value(format!(
                "cannot encode {value:?} as PostgreSQL type {ty}"
            ))),
        }
    }

    fn accepts(_ty: &Type) -> bool {
        true
    }

    to_sql_checked!();
}

fn encode_i64(
    value: i64,
    ty: &Type,
    out: &mut BytesMut,
) -> Result<IsNull, Box<dyn StdError + Sync + Send>> {
    match *ty {
        Type::INT2 => i16::try_from(value)
            .map_err(|_| invalid_value(format!("i64 value is out of int2 range: {value}")))?
            .to_sql(ty, out),
        Type::INT4 => i32::try_from(value)
            .map_err(|_| invalid_value(format!("i64 value is out of int4 range: {value}")))?
            .to_sql(ty, out),
        Type::INT8 => value.to_sql(ty, out),
        Type::OID => u32::try_from(value)
            .map_err(|_| invalid_value(format!("i64 value is out of oid range: {value}")))?
            .to_sql(ty, out),
        _ => Err(invalid_value(format!(
            "cannot encode i64 as PostgreSQL type {ty}"
        ))),
    }
}

fn encode_string(
    value: &str,
    ty: &Type,
    out: &mut BytesMut,
) -> Result<IsNull, Box<dyn StdError + Sync + Send>> {
    match *ty {
        Type::TEXT | Type::VARCHAR | Type::BPCHAR | Type::NAME | Type::UNKNOWN => {
            value.to_sql(ty, out)
        }
        Type::JSON | Type::JSONB => {
            let json: serde_json::Value = serde_json::from_str(value).map_err(|error| {
                invalid_value(format!("invalid JSON parameter for PostgreSQL: {error}"))
            })?;
            Json(json).to_sql(ty, out)
        }
        Type::UUID => value
            .parse::<uuid::Uuid>()
            .map_err(|error| invalid_value(format!("invalid UUID parameter: {error}")))?
            .to_sql(ty, out),
        Type::TIMESTAMP => NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S%.f")
            .map_err(|error| invalid_value(format!("invalid timestamp parameter: {error}")))?
            .to_sql(ty, out),
        Type::TIMESTAMPTZ => DateTime::parse_from_rfc3339(value)
            .map_err(|error| invalid_value(format!("invalid timestamptz parameter: {error}")))?
            .with_timezone(&Utc)
            .to_sql(ty, out),
        Type::DATE => NaiveDate::parse_from_str(value, "%Y-%m-%d")
            .map_err(|error| invalid_value(format!("invalid date parameter: {error}")))?
            .to_sql(ty, out),
        Type::TIME => NaiveTime::parse_from_str(value, "%H:%M:%S%.f")
            .map_err(|error| invalid_value(format!("invalid time parameter: {error}")))?
            .to_sql(ty, out),
        _ if matches!(ty.kind(), Kind::Enum(_)) => {
            out.extend_from_slice(value.as_bytes());
            Ok(IsNull::No)
        }
        _ => Err(invalid_value(format!(
            "cannot encode string as PostgreSQL type {ty}"
        ))),
    }
}

fn invalid_value(message: String) -> Box<dyn StdError + Sync + Send> {
    Box::new(io::Error::new(io::ErrorKind::InvalidInput, message))
}

fn postgres_params(values: &[DbValue]) -> Vec<PostgresValue<'_>> {
    values.iter().map(PostgresValue).collect()
}

fn postgres_param_refs<'a>(values: &'a [PostgresValue<'a>]) -> Vec<&'a (dyn ToSql + Sync)> {
    values
        .iter()
        .map(|value| value as &(dyn ToSql + Sync))
        .collect()
}

fn row_to_db_row(row: Row) -> DbResult<DbRow> {
    let mut values = BTreeMap::new();
    for (index, column) in row.columns().iter().enumerate() {
        values.insert(
            column.name().to_string(),
            postgres_column_value(&row, index, column.type_())?,
        );
    }
    Ok(DbRow::new(values))
}

fn postgres_column_value(row: &Row, index: usize, ty: &Type) -> DbResult<DbValue> {
    match *ty {
        Type::BOOL => optional_column::<bool>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, DbValue::Bool)),
        Type::CHAR => optional_column::<i8>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, |value| DbValue::I64(i64::from(value)))),
        Type::INT2 => optional_column::<i16>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, |value| DbValue::I64(i64::from(value)))),
        Type::INT4 => optional_column::<i32>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, |value| DbValue::I64(i64::from(value)))),
        Type::INT8 => optional_column::<i64>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, DbValue::I64)),
        Type::OID => optional_column::<u32>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, |value| DbValue::U64(u64::from(value)))),
        Type::FLOAT4 => optional_column::<f32>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, |value| DbValue::F64(f64::from(value)))),
        Type::FLOAT8 => optional_column::<f64>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, DbValue::F64)),
        Type::TEXT | Type::VARCHAR | Type::BPCHAR | Type::NAME | Type::UNKNOWN => {
            optional_column::<String>(row, index, ty)
                .map(|value| value.map_or(DbValue::Null, DbValue::String))
        }
        Type::BYTEA => optional_column::<Vec<u8>>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, DbValue::Bytes)),
        Type::JSON | Type::JSONB => optional_column::<serde_json::Value>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, |value| DbValue::String(value.to_string()))),
        Type::UUID => optional_column::<uuid::Uuid>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, |value| DbValue::String(value.to_string()))),
        Type::TIMESTAMP => optional_column::<NaiveDateTime>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, |value| DbValue::String(value.to_string()))),
        Type::TIMESTAMPTZ => optional_column::<DateTime<Utc>>(row, index, ty).map(|value| {
            value.map_or(DbValue::Null, |value| {
                DbValue::String(value.to_rfc3339_opts(SecondsFormat::Micros, true))
            })
        }),
        Type::DATE => optional_column::<NaiveDate>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, |value| DbValue::String(value.to_string()))),
        Type::TIME => optional_column::<NaiveTime>(row, index, ty)
            .map(|value| value.map_or(DbValue::Null, |value| DbValue::String(value.to_string()))),
        _ => Err(DbError::Conversion(format!(
            "unsupported PostgreSQL column type {ty} at index {index}"
        ))),
    }
}

fn optional_column<T>(row: &Row, index: usize, ty: &Type) -> DbResult<Option<T>>
where
    T: FromSqlOwned,
{
    row.try_get::<_, Option<T>>(index).map_err(|error| {
        DbError::Conversion(format!(
            "read PostgreSQL column '{}' as {ty}: {error}",
            row.columns()[index].name()
        ))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn typed_null_accepts_server_inferred_type() {
        let mut output = BytesMut::new();
        let encoded = match PostgresValue(&DbValue::Null).to_sql(&Type::INT8, &mut output) {
            Ok(encoded) => encoded,
            Err(error) => panic!("encode null: {error}"),
        };
        assert!(matches!(encoded, IsNull::Yes));
        assert!(output.is_empty());
    }

    #[test]
    fn unsigned_overflow_is_rejected() {
        let mut output = BytesMut::new();
        let error = match PostgresValue(&DbValue::U64(u64::MAX)).to_sql(&Type::INT8, &mut output) {
            Ok(_) => panic!("u64::MAX must not fit PostgreSQL BIGINT"),
            Err(error) => error,
        };
        assert!(error.to_string().contains("signed range"));
    }

    #[test]
    fn jsonb_string_is_encoded_as_jsonb() {
        let mut output = BytesMut::new();
        let encoded = match PostgresValue(&DbValue::from(r#"{"ok":true}"#))
            .to_sql(&Type::JSONB, &mut output)
        {
            Ok(encoded) => encoded,
            Err(error) => panic!("encode JSONB: {error}"),
        };
        assert!(matches!(encoded, IsNull::No));
        assert_eq!(output.first(), Some(&1));
    }

    #[test]
    fn zero_sized_pool_is_rejected() {
        assert!(checked_pool_size(0).is_err());
    }

    #[test]
    fn connection_config_pins_workspace_search_path() {
        let config = match parse_config(
            "postgresql://bcs@example.invalid/bcs?options=-c%20search_path%3Duntrusted",
        ) {
            Ok(config) => config,
            Err(error) => panic!("parse postgres config: {error}"),
        };

        assert_eq!(config.get_options(), Some(WORKSPACE_SEARCH_PATH_OPTIONS));
    }

    #[test]
    fn connection_config_requires_tls_by_default() {
        let config = match parse_config("postgresql://bcs@example.invalid/bcs") {
            Ok(config) => config,
            Err(error) => panic!("parse postgres config: {error}"),
        };

        assert_eq!(config.get_ssl_mode(), SslMode::Require);
    }

    #[test]
    fn connection_config_allows_explicit_local_tls_disable() {
        let config = match parse_config("postgresql://bcs@example.invalid/bcs?sslmode=disable") {
            Ok(config) => config,
            Err(error) => panic!("parse postgres config: {error}"),
        };

        assert_eq!(config.get_ssl_mode(), SslMode::Disable);
    }
}
