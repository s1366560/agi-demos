use std::time::Duration;

use crate::cron_automation_runtime::AutomationRuntimeWorkerConfig;
use crate::cron_worker::CronWorkerConfig;

pub(super) const CRON_PRODUCTION_READY_ENV: &str = "AGISTACK_CRON_PRODUCTION_READY";

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct CronSchedulerConfig {
    pub(crate) owner_id: String,
    pub(crate) owner_lease_seconds: i64,
    pub(crate) scope_page_size: i64,
    pub(crate) max_scope_pages: usize,
    pub(crate) reconcile_batch_size: i64,
    pub(crate) fire_batch_size: i64,
    pub(crate) operation_batch_size: i64,
    pub(crate) operation_lease_seconds: i64,
    pub(crate) runtime_batch_size: i64,
    pub(crate) runtime_lease_seconds: i64,
    pub(crate) runtime_heartbeat: Duration,
    pub(crate) poll_interval: Duration,
    pub(crate) autostart: bool,
    pub(crate) production_ready: bool,
}

impl CronSchedulerConfig {
    pub(crate) fn from_env() -> Self {
        let default_owner = format!(
            "agistack-cron-{}-{}",
            std::env::var("HOSTNAME").unwrap_or_else(|_| "local".to_string()),
            std::process::id()
        );
        Self {
            owner_id: string_env("AGISTACK_CRON_OWNER_ID", &default_owner),
            owner_lease_seconds: positive_i64_env("AGISTACK_CRON_OWNER_LEASE_SECONDS", 60),
            scope_page_size: positive_i64_env("AGISTACK_CRON_SCOPE_PAGE_SIZE", 25),
            max_scope_pages: positive_usize_env("AGISTACK_CRON_MAX_SCOPE_PAGES", 4),
            reconcile_batch_size: positive_i64_env("AGISTACK_CRON_RECONCILE_BATCH_SIZE", 25),
            fire_batch_size: positive_i64_env("AGISTACK_CRON_FIRE_BATCH_SIZE", 25),
            operation_batch_size: positive_i64_env("AGISTACK_CRON_OPERATION_BATCH_SIZE", 25),
            operation_lease_seconds: positive_i64_env(
                "AGISTACK_CRON_OPERATION_LEASE_SECONDS",
                60,
            ),
            runtime_batch_size: positive_i64_env("AGISTACK_CRON_RUNTIME_BATCH_SIZE", 1),
            runtime_lease_seconds: positive_i64_env("AGISTACK_CRON_RUNTIME_LEASE_SECONDS", 60),
            runtime_heartbeat: duration_env("AGISTACK_CRON_RUNTIME_HEARTBEAT_SECONDS", 15.0),
            poll_interval: duration_env("AGISTACK_CRON_POLL_SECONDS", 2.0),
            autostart: bool_env("AGISTACK_CRON_AUTOSTART", false),
            production_ready: bool_env(CRON_PRODUCTION_READY_ENV, false),
        }
    }

    pub(crate) fn operation_worker_config(&self) -> CronWorkerConfig {
        CronWorkerConfig {
            worker_id: format!("{}:operation", self.owner_id),
            batch_size: self.operation_batch_size,
            lease_seconds: self.operation_lease_seconds,
            autostart: true,
            production_ready: true,
            handlers_ready: true,
        }
    }

    pub(crate) fn runtime_worker_config(&self) -> AutomationRuntimeWorkerConfig {
        AutomationRuntimeWorkerConfig {
            worker_id: format!("{}:runtime", self.owner_id),
            batch_size: self.runtime_batch_size,
            lease_seconds: self.runtime_lease_seconds,
            heartbeat_interval: self.runtime_heartbeat,
        }
    }
}

impl Default for CronSchedulerConfig {
    fn default() -> Self {
        Self {
            owner_id: "agistack-cron-disabled".to_string(),
            owner_lease_seconds: 60,
            scope_page_size: 25,
            max_scope_pages: 4,
            reconcile_batch_size: 25,
            fire_batch_size: 25,
            operation_batch_size: 25,
            operation_lease_seconds: 60,
            runtime_batch_size: 1,
            runtime_lease_seconds: 60,
            runtime_heartbeat: Duration::from_secs(15),
            poll_interval: Duration::from_secs(2),
            autostart: false,
            production_ready: false,
        }
    }
}

fn string_env(name: &str, default: &str) -> String {
    std::env::var(name)
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| default.to_string())
}

fn positive_i64_env(name: &str, default: i64) -> i64 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.trim().parse::<i64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(default)
}

fn positive_usize_env(name: &str, default: usize) -> usize {
    std::env::var(name)
        .ok()
        .and_then(|value| value.trim().parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(default)
}

fn duration_env(name: &str, default_seconds: f64) -> Duration {
    let seconds = std::env::var(name)
        .ok()
        .and_then(|value| value.trim().parse::<f64>().ok())
        .filter(|value| value.is_finite() && *value > 0.0)
        .unwrap_or(default_seconds);
    Duration::from_secs_f64(seconds)
}

fn bool_env(name: &str, default: bool) -> bool {
    std::env::var(name)
        .ok()
        .map(|value| {
            matches!(
                value.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_scheduler_is_fail_closed() {
        let config = CronSchedulerConfig::default();
        assert!(!config.autostart);
        assert!(!config.production_ready);
        assert!(config.owner_lease_seconds > 0);
        assert!(config.max_scope_pages > 0);
        assert!(config.runtime_heartbeat < Duration::from_secs(config.runtime_lease_seconds as u64));
    }
}
