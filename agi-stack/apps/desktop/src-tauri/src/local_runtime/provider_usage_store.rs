use rusqlite::{params, Connection};
use serde::Serialize;

pub(super) struct ProviderUsageRecord<'a> {
    pub(super) provider_id: &'a str,
    pub(super) tenant_id: &'a str,
    pub(super) operation_type: &'a str,
    pub(super) model_name: &'a str,
    pub(super) prompt_tokens: i64,
    pub(super) completion_tokens: i64,
    pub(super) cost_usd: Option<f64>,
    pub(super) response_time_ms: i64,
    pub(super) created_at: &'a str,
}

#[derive(Debug, Serialize)]
pub(super) struct ProviderUsageStatistic {
    provider_id: String,
    tenant_id: Option<String>,
    operation_type: Option<String>,
    total_requests: i64,
    total_prompt_tokens: i64,
    total_completion_tokens: i64,
    total_tokens: i64,
    total_cost_usd: Option<f64>,
    avg_response_time_ms: Option<f64>,
    first_request_at: Option<String>,
    last_request_at: Option<String>,
}

pub(super) fn initialize_schema(connection: &Connection) -> Result<(), String> {
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS desktop_llm_usage (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               provider_id TEXT NOT NULL,
               tenant_id TEXT NOT NULL,
               operation_type TEXT NOT NULL,
               model_name TEXT NOT NULL,
               prompt_tokens INTEGER NOT NULL,
               completion_tokens INTEGER NOT NULL,
               cost_usd REAL,
               response_time_ms INTEGER NOT NULL,
               created_at TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_desktop_llm_usage_scope
               ON desktop_llm_usage(provider_id, tenant_id, operation_type, created_at);",
        )
        .map_err(|error| error.to_string())
}

pub(super) fn record(
    connection: &Connection,
    usage: ProviderUsageRecord<'_>,
) -> Result<(), String> {
    connection
        .execute(
            "INSERT INTO desktop_llm_usage (
               provider_id, tenant_id, operation_type, model_name,
               prompt_tokens, completion_tokens, cost_usd, response_time_ms, created_at
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            params![
                usage.provider_id,
                usage.tenant_id,
                usage.operation_type,
                usage.model_name,
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.cost_usd,
                usage.response_time_ms,
                usage.created_at,
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

pub(super) fn statistics(
    connection: &Connection,
    provider_id: &str,
    tenant_id: &str,
) -> Result<Vec<ProviderUsageStatistic>, String> {
    let mut statement = connection
        .prepare(
            "SELECT provider_id, tenant_id, operation_type,
                    COUNT(id),
                    COALESCE(SUM(prompt_tokens), 0),
                    COALESCE(SUM(completion_tokens), 0),
                    COALESCE(SUM(prompt_tokens + completion_tokens), 0),
                    SUM(cost_usd),
                    AVG(response_time_ms),
                    MIN(created_at),
                    MAX(created_at)
             FROM desktop_llm_usage
             WHERE provider_id = ?1 AND tenant_id = ?2
             GROUP BY provider_id, tenant_id, operation_type
             ORDER BY operation_type ASC",
        )
        .map_err(|error| error.to_string())?;
    let rows = statement
        .query_map(params![provider_id, tenant_id], |row| {
            Ok(ProviderUsageStatistic {
                provider_id: row.get(0)?,
                tenant_id: row.get(1)?,
                operation_type: row.get(2)?,
                total_requests: row.get(3)?,
                total_prompt_tokens: row.get(4)?,
                total_completion_tokens: row.get(5)?,
                total_tokens: row.get(6)?,
                total_cost_usd: row.get(7)?,
                avg_response_time_ms: row.get(8)?,
                first_request_at: row.get(9)?,
                last_request_at: row.get(10)?,
            })
        })
        .map_err(|error| error.to_string())?;
    rows.collect::<Result<Vec<_>, _>>()
        .map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn usage<'a>(
        tenant_id: &'a str,
        created_at: &'a str,
        response_time_ms: i64,
    ) -> ProviderUsageRecord<'a> {
        ProviderUsageRecord {
            provider_id: "provider-a",
            tenant_id,
            operation_type: "llm",
            model_name: "model-a",
            prompt_tokens: 10,
            completion_tokens: 5,
            cost_usd: Some(0.25),
            response_time_ms,
            created_at,
        }
    }

    #[test]
    fn statistics_aggregate_persisted_requests_inside_the_exact_tenant_scope() {
        let connection = Connection::open_in_memory().expect("usage test database");
        initialize_schema(&connection).expect("usage schema");
        record(&connection, usage("tenant-a", "2026-07-20T10:00:00Z", 100))
            .expect("first tenant usage");
        record(&connection, usage("tenant-a", "2026-07-20T10:01:00Z", 300))
            .expect("second tenant usage");
        record(&connection, usage("tenant-b", "2026-07-20T10:02:00Z", 900))
            .expect("other tenant usage");

        let statistics =
            statistics(&connection, "provider-a", "tenant-a").expect("tenant statistics");
        assert_eq!(statistics.len(), 1);
        let statistic = &statistics[0];
        assert_eq!(statistic.provider_id, "provider-a");
        assert_eq!(statistic.tenant_id.as_deref(), Some("tenant-a"));
        assert_eq!(statistic.operation_type.as_deref(), Some("llm"));
        assert_eq!(statistic.total_requests, 2);
        assert_eq!(statistic.total_prompt_tokens, 20);
        assert_eq!(statistic.total_completion_tokens, 10);
        assert_eq!(statistic.total_tokens, 30);
        assert_eq!(statistic.total_cost_usd, Some(0.5));
        assert_eq!(statistic.avg_response_time_ms, Some(200.0));
        assert_eq!(
            statistic.first_request_at.as_deref(),
            Some("2026-07-20T10:00:00Z")
        );
        assert_eq!(
            statistic.last_request_at.as_deref(),
            Some("2026-07-20T10:01:00Z")
        );
    }
}
