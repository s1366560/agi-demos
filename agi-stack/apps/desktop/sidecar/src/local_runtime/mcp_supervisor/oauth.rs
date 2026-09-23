//! MCP OAuth grants are encrypted application-vault records, shared by leased generations.
use super::super::plugin_marketplace_v3::oauth_http;
use super::*;
use serde_json::json;
static REFRESH: AsyncMutex<()> = AsyncMutex::const_new(());
fn binding(id: &str) -> String {
    format!("mcp-oauth-binding:{id}")
}
fn unavailable() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_oauth_unavailable",
        "MCP OAuth grant is unavailable",
    )
}
#[derive(Clone, Serialize, Deserialize)]
struct Grant {
    client_id: String,
    resource: String,
    token_endpoint: String,
    revocation_endpoint: Option<String>,
    refresh_token: Option<String>,
    access_token: String,
    expires_at: i64,
    headers: BTreeMap<String, String>,
}
impl McpSupervisor {
    fn oauth_grant(
        &self,
        id: &str,
    ) -> McpResult<Option<(ApplicationCredentialVault, String, Grant)>> {
        let Some(vault) = self.credential_vault()? else {
            return Ok(None);
        };
        let Some(key) = vault.get(&binding(id)).map_err(|_| unavailable())? else {
            return Ok(None);
        };
        let raw = zeroize::Zeroizing::new(
            vault
                .get(&key)
                .map_err(|_| unavailable())?
                .ok_or_else(unavailable)?,
        );
        let grant = serde_json::from_str(&raw).map_err(|_| unavailable())?;
        Ok(Some((vault, key, grant)))
    }
    pub(in crate::local_runtime) fn oauth_status(&self, id: &str) -> McpResult<Value> {
        Ok(match self.oauth_grant(id)? {
            Some((_, _, grant)) => {
                json!({"status":if grant.expires_at>chrono::Utc::now().timestamp() || grant.refresh_token.as_ref().is_some_and(|token| !token.is_empty()) {"connected"}else{"expired"},"expires_at":grant.expires_at})
            }
            None => json!({"status":"not_connected"}),
        })
    }
    pub(in crate::local_runtime) fn oauth_connect(
        &self,
        scope: &McpScope,
        id: &str,
        metadata: &Value,
        client_id: &str,
        resource: &str,
        tokens: &Value,
    ) -> McpResult<()> {
        let access = tokens["access_token"]
            .as_str()
            .filter(|token| !token.is_empty() && token.len() < 65536)
            .ok_or_else(unavailable)?;
        if !tokens["token_type"]
            .as_str()
            .is_some_and(|kind| kind.eq_ignore_ascii_case("bearer"))
        {
            return Err(unavailable());
        }
        let expires = tokens["expires_in"]
            .as_i64()
            .filter(|ttl| *ttl > 0)
            .ok_or_else(unavailable)?;
        let mut grant = Grant {
            client_id: client_id.into(),
            resource: resource.into(),
            token_endpoint: metadata["token_endpoint"]
                .as_str()
                .ok_or_else(unavailable)?
                .into(),
            revocation_endpoint: metadata["revocation_endpoint"].as_str().map(str::to_owned),
            refresh_token: tokens["refresh_token"].as_str().map(str::to_owned),
            access_token: access.into(),
            expires_at: chrono::Utc::now().timestamp() + expires,
            headers: BTreeMap::new(),
        };
        let key = format!("mcp-oauth-grant:{}", uuid::Uuid::new_v4());
        {
            let vault = self.credential_vault.lock().map_err(|_| unavailable())?;
            Self::oauth_forget_locked(vault.as_ref(), id)?;
        }
        self.attach_oauth(scope, id, &key, &mut grant)
    }
    fn attach_oauth(
        &self,
        scope: &McpScope,
        id: &str,
        key: &str,
        grant: &mut Grant,
    ) -> McpResult<()> {
        let server = self.server(scope, id)?.ok_or_else(server_not_found)?;
        if server.command.first().map(String::as_str) != Some(grant.resource.as_str()) {
            return Err(unavailable());
        }
        let provision = McpCredentialProvisionInput {
            server_name: server.name.clone(),
            transport: server.transport,
            command: server.command.clone(),
            cwd: server.cwd.clone(),
            kind: McpCredentialKind::Header,
            name: "Authorization".into(),
            mutation_idempotency_key: None,
        };
        self.provision_credential(
            scope,
            &provision,
            &format!("Bearer {}", grant.access_token),
            &format!("oauth-secret-{}", uuid::Uuid::new_v4()),
        )?;
        let reference = credential_reference(
            scope,
            &server.name,
            server.transport,
            &server.command,
            server.cwd.as_deref(),
            McpCredentialKind::Header,
            "Authorization",
        )?;
        let mut refs = server.vault_env_refs;
        refs.insert("Authorization".into(), reference.clone());
        self.update_server(
            scope,
            id,
            McpServerDefinitionInput {
                name: server.name,
                description: server.description,
                transport: server.transport,
                command: server.command,
                cwd: server.cwd,
                vault_env_refs: refs,
                enabled: server.enabled,
            },
            server.revision,
            &format!("oauth-bind-{}", uuid::Uuid::new_v4()),
        )?;
        let vault_guard = self.credential_vault.lock().map_err(|_| unavailable())?;
        let vault = vault_guard.as_ref().ok_or_else(unavailable)?;
        if let Some(raw) = vault.get(key).map_err(|_| unavailable())? {
            // A refresh may have rotated this shared grant while the new server was registered.
            *grant = serde_json::from_str(&raw).map_err(|_| unavailable())?;
            vault
                .put(&reference, &format!("Bearer {}", grant.access_token))
                .map_err(|_| unavailable())?;
        }
        grant.headers.insert(id.into(), reference);
        vault
            .put(
                key,
                &serde_json::to_string(grant).map_err(|_| unavailable())?,
            )
            .map_err(|_| unavailable())?;
        vault.put(&binding(id), key).map_err(|_| unavailable())?;
        Ok(())
    }
    pub(in crate::local_runtime) fn oauth_inherit(
        &self,
        scope: &McpScope,
        old: &str,
        new: &str,
    ) -> McpResult<bool> {
        let Some((_, key, mut grant)) = self.oauth_grant(old)? else {
            return Ok(false);
        };
        self.attach_oauth(scope, new, &key, &mut grant)?;
        Ok(true)
    }
    pub(in crate::local_runtime) async fn oauth_refresh(&self, id: &str) -> McpResult<()> {
        let _guard = REFRESH.lock().await;
        let Some((vault, key, mut grant)) = self.oauth_grant(id)? else {
            return Ok(());
        };
        if grant.expires_at > chrono::Utc::now().timestamp() + 15 {
            return Ok(());
        }
        let refresh = grant.refresh_token.as_ref().ok_or_else(|| {
            McpSupervisorError::new(
                "local_mcp_oauth_expired",
                "Reconnect the expired MCP OAuth grant",
            )
        })?;
        let response = oauth_http::post(
            &grant.token_endpoint,
            &[
                ("grant_type".into(), "refresh_token".into()),
                ("refresh_token".into(), refresh.clone()),
                ("client_id".into(), grant.client_id.clone()),
                ("resource".into(), grant.resource.clone()),
            ],
        )
        .await;
        let tokens = match response {
            Ok(tokens) => tokens,
            Err(reason) => {
                if reason == "oauth_invalid_grant" {
                    let _vault_guard = self.credential_vault.lock().map_err(|_| unavailable())?;
                    if vault
                        .get(&binding(id))
                        .map_err(|_| unavailable())?
                        .as_deref()
                        == Some(key.as_str())
                    {
                        let current = vault
                            .get(&key)
                            .map_err(|_| unavailable())?
                            .ok_or_else(unavailable)?;
                        let mut invalid: Grant =
                            serde_json::from_str(&current).map_err(|_| unavailable())?;
                        invalid.refresh_token = None;
                        invalid.expires_at = chrono::Utc::now().timestamp() - 1;
                        vault
                            .put(
                                &key,
                                &serde_json::to_string(&invalid).map_err(|_| unavailable())?,
                            )
                            .map_err(|_| unavailable())?;
                    }
                }
                return Err(unavailable());
            }
        };
        let access = tokens["access_token"]
            .as_str()
            .filter(|token| !token.is_empty())
            .ok_or_else(unavailable)?;
        if !tokens["token_type"]
            .as_str()
            .is_some_and(|kind| kind.eq_ignore_ascii_case("bearer"))
        {
            return Err(unavailable());
        }
        let _vault_guard = self.credential_vault.lock().map_err(|_| unavailable())?;
        if vault
            .get(&binding(id))
            .map_err(|_| unavailable())?
            .as_deref()
            != Some(key.as_str())
        {
            return Err(unavailable());
        }
        // Merge the current registered generation references, not the pre-network snapshot.
        let current = vault
            .get(&key)
            .map_err(|_| unavailable())?
            .ok_or_else(unavailable)?;
        grant = serde_json::from_str(&current).map_err(|_| unavailable())?;
        grant.access_token = access.into();
        grant.expires_at = chrono::Utc::now().timestamp()
            + tokens["expires_in"]
                .as_i64()
                .filter(|ttl| *ttl > 0)
                .ok_or_else(unavailable)?;
        if let Some(refresh) = tokens["refresh_token"].as_str() {
            grant.refresh_token = Some(refresh.into());
        }
        for reference in grant.headers.values() {
            vault
                .put(reference, &format!("Bearer {}", grant.access_token))
                .map_err(|_| unavailable())?;
        }
        vault
            .put(
                &key,
                &serde_json::to_string(&grant).map_err(|_| unavailable())?,
            )
            .map_err(|_| unavailable())?;
        Ok(())
    }
    pub(in crate::local_runtime) async fn oauth_disconnect(&self, id: &str) -> McpResult<()> {
        let _guard = REFRESH.lock().await;
        let Some((vault, key, grant)) = self.oauth_grant(id)? else {
            return Ok(());
        };
        let result = if let Some(endpoint) = grant.revocation_endpoint.as_deref() {
            oauth_http::revoke(
                endpoint,
                &[
                    (
                        "token".into(),
                        grant
                            .refresh_token
                            .as_ref()
                            .unwrap_or(&grant.access_token)
                            .clone(),
                    ),
                    ("client_id".into(), grant.client_id),
                ],
            )
            .await
            .map_err(|_| unavailable())
        } else {
            Ok(())
        };
        let _vault_guard = self.credential_vault.lock().map_err(|_| unavailable())?;
        let grant = if let Some(current) = vault.get(&key).map_err(|_| unavailable())? {
            serde_json::from_str::<Grant>(&current).map_err(|_| unavailable())?
        } else {
            return result;
        };
        for (server, reference) in grant.headers {
            vault.clear(&reference).map_err(|_| unavailable())?;
            vault.clear(&binding(&server)).map_err(|_| unavailable())?;
        }
        vault.clear(&key).map_err(|_| unavailable())?;
        result
    }
    pub(super) fn oauth_forget_locked(
        vault: Option<&ApplicationCredentialVault>,
        id: &str,
    ) -> McpResult<()> {
        let Some(vault) = vault else { return Ok(()) };
        let Some(key) = vault.get(&binding(id)).map_err(|_| unavailable())? else {
            return Ok(());
        };
        if let Some(raw) = vault.get(&key).map_err(|_| unavailable())? {
            let mut grant: Grant = serde_json::from_str(&raw).map_err(|_| unavailable())?;
            grant.headers.remove(id);
            if grant.headers.is_empty() {
                vault.clear(&key).map_err(|_| unavailable())?;
            } else {
                vault
                    .put(
                        &key,
                        &serde_json::to_string(&grant).map_err(|_| unavailable())?,
                    )
                    .map_err(|_| unavailable())?;
            }
        }
        vault.clear(&binding(id)).map_err(|_| unavailable())?;
        Ok(())
    }
}
