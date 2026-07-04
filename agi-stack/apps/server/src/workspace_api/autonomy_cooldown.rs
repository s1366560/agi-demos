use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use chrono::{DateTime, Duration, Utc};

pub(crate) type SharedAutonomyCooldownStore = Arc<dyn AutonomyCooldownStore>;

#[async_trait]
pub(crate) trait AutonomyCooldownStore: Send + Sync {
    async fn is_on_cooldown(&self, workspace_id: &str, root_task_id: &str) -> Result<bool, String>;

    async fn mark_cooldown(
        &self,
        workspace_id: &str,
        root_task_id: &str,
        ttl_seconds: i64,
    ) -> Result<(), String>;
}

#[derive(Default)]
pub(super) struct InMemoryAutonomyCooldownStore {
    entries: Mutex<HashMap<(String, String), DateTime<Utc>>>,
}

impl InMemoryAutonomyCooldownStore {
    pub(super) fn new() -> Self {
        Self::default()
    }
}

#[async_trait]
impl AutonomyCooldownStore for InMemoryAutonomyCooldownStore {
    async fn is_on_cooldown(&self, workspace_id: &str, root_task_id: &str) -> Result<bool, String> {
        let now = Utc::now();
        let mut entries = self
            .entries
            .lock()
            .map_err(|_| "workspace autonomy cooldown lock poisoned".to_string())?;
        entries.retain(|_, expires_at| *expires_at > now);
        Ok(entries.contains_key(&(workspace_id.to_string(), root_task_id.to_string())))
    }

    async fn mark_cooldown(
        &self,
        workspace_id: &str,
        root_task_id: &str,
        ttl_seconds: i64,
    ) -> Result<(), String> {
        let expires_at = Utc::now() + Duration::seconds(ttl_seconds.max(1));
        let mut entries = self
            .entries
            .lock()
            .map_err(|_| "workspace autonomy cooldown lock poisoned".to_string())?;
        entries.insert(
            (workspace_id.to_string(), root_task_id.to_string()),
            expires_at,
        );
        Ok(())
    }
}

#[async_trait]
impl AutonomyCooldownStore for agistack_adapters_redis::RedisWorkspaceAutonomyCooldownStore {
    async fn is_on_cooldown(&self, workspace_id: &str, root_task_id: &str) -> Result<bool, String> {
        agistack_adapters_redis::RedisWorkspaceAutonomyCooldownStore::is_on_cooldown(
            self,
            workspace_id,
            root_task_id,
        )
        .await
        .map_err(|err| err.to_string())
    }

    async fn mark_cooldown(
        &self,
        workspace_id: &str,
        root_task_id: &str,
        ttl_seconds: i64,
    ) -> Result<(), String> {
        let ttl_seconds = u64::try_from(ttl_seconds.max(1))
            .map_err(|_| "workspace autonomy cooldown ttl out of range".to_string())?;
        agistack_adapters_redis::RedisWorkspaceAutonomyCooldownStore::mark_cooldown(
            self,
            workspace_id,
            root_task_id,
            ttl_seconds,
        )
        .await
        .map_err(|err| err.to_string())
    }
}
