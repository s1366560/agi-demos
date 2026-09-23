//! Publication and leases for independently verified marketplace MCP generations.
use super::*;
use rusqlite::params;

#[derive(Clone, Copy, PartialEq)]
enum Phase {
    Candidate,
    Active,
    Retired,
}
struct Entry {
    phase: Phase,
    leases: usize,
    scope: McpScope,
}
#[derive(Default)]
pub(super) struct GenerationCatalog {
    entries: HashMap<String, Entry>,
    snapshots: HashMap<String, super::super::plugin_marketplace_v3::cache::Lease>,
}
pub(in crate::local_runtime) struct McpCatalogLease {
    supervisor: McpSupervisor,
    scope: McpScope,
    ids: Vec<String>,
}
impl Drop for McpCatalogLease {
    fn drop(&mut self) {
        if let Ok(mut catalog) = self.supervisor.marketplace_generations.lock() {
            for id in &self.ids {
                if let Some(entry) = catalog.entries.get_mut(id) {
                    entry.leases = entry.leases.saturating_sub(1);
                }
            }
        }
        let _ = self.supervisor.reap_marketplace_generations();
    }
}
impl McpStore {
    pub(super) fn marketplace_catalog(&self) -> McpResult<GenerationCatalog> {
        self.session_store.with_local_mcp_connection(|connection|{
            connection.execute_batch("CREATE TABLE IF NOT EXISTS desktop_mcp_marketplace_generations_v1(server_id TEXT PRIMARY KEY REFERENCES desktop_mcp_servers_v1(id) ON DELETE CASCADE,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,phase TEXT NOT NULL CHECK(phase IN ('candidate','active','retired')))").map_err(|e|e.to_string())?;
            connection.execute_batch("CREATE TABLE IF NOT EXISTS desktop_mcp_marketplace_snapshot_leases_v1(server_id TEXT PRIMARY KEY REFERENCES desktop_mcp_servers_v1(id) ON DELETE CASCADE,path TEXT NOT NULL)").map_err(|e|e.to_string())?;
            let mut query=connection.prepare("SELECT server_id,tenant_id,project_id,phase FROM desktop_mcp_marketplace_generations_v1").map_err(|e|e.to_string())?;
            let entries=query.query_map([],|row|Ok((row.get::<_,String>(0)?,Entry{scope:McpScope{tenant_id:row.get(1)?,project_id:row.get(2)?},phase:match row.get::<_,String>(3)?.as_str(){"active"=>Phase::Active,"retired"=>Phase::Retired,_=>Phase::Candidate},leases:0}))).map_err(|e|e.to_string())?.collect::<Result<HashMap<_,_>,_>>().map_err(|e|e.to_string())?;
            let mut snapshots=HashMap::new();
            let mut query=connection.prepare("SELECT server_id,path FROM desktop_mcp_marketplace_snapshot_leases_v1").map_err(|e|e.to_string())?;
            for row in query.query_map([],|row|Ok((row.get::<_,String>(0)?,row.get::<_,String>(1)?))).map_err(|e|e.to_string())? {
                let (id,path)=row.map_err(|e|e.to_string())?;
                if let Ok(lease)=super::super::plugin_marketplace_v3::cache::lease(Path::new(&path)){snapshots.insert(id,lease);}
            }
            Ok(GenerationCatalog{entries,snapshots})
        }).map_err(|_|storage_error())
    }
    fn stage_generation(&self, scope: &McpScope, id: &str) -> McpResult<()> {
        self.session_store.with_local_mcp_connection(|connection|{
            connection.execute("INSERT INTO desktop_mcp_marketplace_generations_v1(server_id,tenant_id,project_id,phase) VALUES (?1,?2,?3,'candidate') ON CONFLICT(server_id) DO NOTHING",params![id,scope.tenant_id,scope.project_id]).map_err(|e|e.to_string())?;Ok(())
        }).map_err(|_|storage_error())
    }
    fn publish_generation(
        &self,
        scope: &McpScope,
        active: &[String],
        retired: &[String],
    ) -> McpResult<()> {
        self.session_store.with_local_mcp_connection(|connection|{
            let transaction=connection.transaction().map_err(|e|e.to_string())?;
            for (phase,ids) in [("active",active),("retired",retired)]{for id in ids{transaction.execute("UPDATE desktop_mcp_marketplace_generations_v1 SET phase=?1 WHERE server_id=?2 AND tenant_id=?3 AND project_id=?4",params![phase,id,scope.tenant_id,scope.project_id]).map_err(|e|e.to_string())?;}}
            transaction.commit().map_err(|e|e.to_string())
        }).map_err(|_|storage_error())
    }
}
impl McpSupervisor {
    pub(in crate::local_runtime) fn bind_marketplace_snapshot(
        &self,
        id: &str,
        path: &Path,
    ) -> McpResult<()> {
        let mut catalog = self
            .marketplace_generations
            .lock()
            .map_err(|_| storage_error())?;
        if !catalog.entries.contains_key(id) {
            return Err(storage_error());
        }
        let lease =
            super::super::plugin_marketplace_v3::cache::lease(path).map_err(|_| storage_error())?;
        self.store.session_store.with_local_mcp_connection(|connection|{
            connection.execute("INSERT INTO desktop_mcp_marketplace_snapshot_leases_v1(server_id,path) VALUES (?1,?2) ON CONFLICT(server_id) DO UPDATE SET path=excluded.path",rusqlite::params![id,path.to_string_lossy()]).map_err(|e|e.to_string())?;Ok(())
        }).map_err(|_|storage_error())?;
        catalog.snapshots.insert(id.into(), lease);
        Ok(())
    }

    pub(in crate::local_runtime) fn inherit_marketplace_credential(
        &self,
        scope: &McpScope,
        source_id: &str,
        binding: &str,
        target: &McpCredentialProvisionInput,
        key: &str,
    ) -> McpResult<bool> {
        let source = self
            .store
            .server(scope, source_id)?
            .ok_or_else(storage_error)?;
        let Some(reference) = source.vault_env_refs.get(binding) else {
            return Ok(false);
        };
        let vault = self.credential_vault()?.ok_or_else(storage_error)?;
        let Some(secret) = vault.get(reference).map_err(|_| storage_error())? else {
            return Ok(false);
        };
        let secret = zeroize::Zeroizing::new(secret);
        self.provision_credential(scope, target, secret.as_str(), key)?;
        Ok(true)
    }
    pub(in crate::local_runtime) fn marketplace_server_active(&self, id: &str) -> bool {
        self.marketplace_generations.lock().is_ok_and(|catalog| {
            catalog
                .entries
                .get(id)
                .is_some_and(|entry| entry.phase == Phase::Active)
        })
    }
    pub(in crate::local_runtime) fn recover_marketplace_candidates(
        &self,
        preserved: &std::collections::BTreeSet<String>,
    ) -> McpResult<()> {
        let candidates = {
            let catalog = self
                .marketplace_generations
                .lock()
                .map_err(|_| storage_error())?;
            catalog
                .entries
                .iter()
                .filter(|(id, entry)| entry.phase != Phase::Retired && !preserved.contains(*id))
                .map(|(id, entry)| (id.clone(), entry.scope.clone()))
                .collect::<Vec<_>>()
        };
        for (id, scope) in candidates {
            self.publish_marketplace_generation(&scope, &[], &[id])?;
        }
        self.reap_marketplace_generations()
    }
    pub(in crate::local_runtime) fn stage_marketplace_server(
        &self,
        scope: &McpScope,
        id: &str,
    ) -> McpResult<()> {
        let mut catalog = self
            .marketplace_generations
            .lock()
            .map_err(|_| storage_error())?;
        self.store.stage_generation(scope, id)?;
        catalog.entries.entry(id.into()).or_insert_with(|| Entry {
            scope: scope.clone(),
            phase: Phase::Candidate,
            leases: 0,
        });
        Ok(())
    }
    pub(in crate::local_runtime) fn publish_marketplace_generation(
        &self,
        scope: &McpScope,
        active: &[String],
        retired: &[String],
    ) -> McpResult<()> {
        {
            let mut catalog = self
                .marketplace_generations
                .lock()
                .map_err(|_| storage_error())?;
            for id in active.iter().chain(retired) {
                if !catalog
                    .entries
                    .get(id)
                    .is_some_and(|entry| entry.scope == *scope)
                {
                    return Err(storage_error());
                }
            }
            self.store.publish_generation(scope, active, retired)?;
            for id in active {
                if let Some(entry) = catalog.entries.get_mut(id) {
                    entry.phase = Phase::Active;
                }
            }
            for id in retired {
                if let Some(entry) = catalog.entries.get_mut(id) {
                    entry.phase = Phase::Retired;
                }
            }
        }
        self.reap_marketplace_generations()
    }
    pub(super) fn marketplace_visible(catalog: &GenerationCatalog, id: &str) -> bool {
        catalog
            .entries
            .get(id)
            .is_none_or(|entry| entry.phase == Phase::Active)
    }
    pub(in crate::local_runtime) fn acquire_catalog(
        &self,
        scope: &McpScope,
    ) -> McpResult<(Vec<McpServerDefinition>, McpCatalogLease)> {
        let mut catalog = self
            .marketplace_generations
            .lock()
            .map_err(|_| storage_error())?;
        let servers = self
            .store
            .list_servers(scope)?
            .into_iter()
            .filter(|server| Self::marketplace_visible(&catalog, &server.id))
            .collect::<Vec<_>>();
        let ids = servers.iter().map(|s| s.id.clone()).collect::<Vec<_>>();
        for id in &ids {
            if let Some(entry) = catalog.entries.get_mut(id) {
                entry.leases += 1;
            }
        }
        Ok((
            servers,
            McpCatalogLease {
                supervisor: self.clone(),
                scope: scope.clone(),
                ids,
            },
        ))
    }
    pub(super) fn acquire_active_call(
        &self,
        scope: &McpScope,
        id: &str,
    ) -> McpResult<McpCatalogLease> {
        let mut catalog = self
            .marketplace_generations
            .lock()
            .map_err(|_| storage_error())?;
        if let Some(entry) = catalog.entries.get_mut(id) {
            if entry.phase != Phase::Active || entry.scope != *scope {
                return Err(McpSupervisorError::new(
                    "local_mcp_generation_inactive",
                    "MCP plugin generation is not active",
                ));
            }
            entry.leases += 1;
        }
        Ok(McpCatalogLease {
            supervisor: self.clone(),
            scope: scope.clone(),
            ids: vec![id.into()],
        })
    }
    pub(in crate::local_runtime) async fn call_tool_pinned(
        &self,
        lease: &McpCatalogLease,
        scope: &McpScope,
        id: &str,
        name: &str,
        arguments: Value,
        key: &str,
    ) -> McpResult<McpToolCallOutcome> {
        if lease.scope != *scope || !lease.ids.iter().any(|owned| owned == id) {
            return Err(McpSupervisorError::new(
                "local_mcp_generation_scope_invalid",
                "MCP generation lease does not authorize this server",
            ));
        }
        self.call_tool_in_generation(scope, id, name, arguments, key)
            .await
    }

    pub(in crate::local_runtime) async fn read_resource_pinned(
        &self,
        lease: &McpCatalogLease,
        scope: &McpScope,
        id: &str,
        uri: &str,
    ) -> McpResult<Vec<Value>> {
        if lease.scope != *scope || !lease.ids.iter().any(|owned| owned == id) {
            return Err(McpSupervisorError::new(
                "local_mcp_generation_scope_invalid",
                "MCP generation lease does not authorize this server",
            ));
        }
        validate_resource_uri(uri)?;
        let server = self.required_server(scope, id)?;
        let result = self
            .request(&server, "resources/read", serde_json::json!({ "uri": uri }))
            .await?;
        result
            .get("contents")
            .and_then(Value::as_array)
            .cloned()
            .ok_or_else(|| {
                McpSupervisorError::new(
                    "local_mcp_malformed_response",
                    "MCP resources/read response is malformed",
                )
            })
    }

    pub(in crate::local_runtime) fn apps_pinned(
        &self,
        lease: &McpCatalogLease,
        scope: &McpScope,
    ) -> McpResult<Vec<McpAppDefinition>> {
        if lease.scope != *scope {
            return Err(McpSupervisorError::new(
                "local_mcp_generation_scope_invalid",
                "MCP generation lease does not authorize this scope",
            ));
        }
        // The lease prevents deletion of these exact generations even if publication
        // switches between catalog acquisition and metadata loading.
        Ok(self
            .store
            .list_apps(scope)?
            .into_iter()
            .filter(|app| lease.ids.contains(&app.server_id))
            .collect())
    }
    fn reap_marketplace_generations(&self) -> McpResult<()> {
        let mut catalog = self
            .marketplace_generations
            .lock()
            .map_err(|_| storage_error())?;
        let retired = catalog
            .entries
            .iter()
            .filter(|(_, entry)| entry.phase == Phase::Retired && entry.leases == 0)
            .map(|(id, entry)| (id.clone(), entry.scope.clone()))
            .collect::<Vec<_>>();
        for (id, scope) in retired {
            if let Some(server) = self.store.server(&scope, &id)? {
                self.delete_server(
                    &scope,
                    &id,
                    server.revision,
                    &format!("retire-generation-{id}"),
                )?;
            }
            catalog.entries.remove(&id);
            catalog.snapshots.remove(&id);
        }
        Ok(())
    }
}
