use super::*;

pub(crate) type SharedHttpServiceRegistry = Arc<dyn HttpServiceRegistry>;

#[async_trait]
pub(crate) trait HttpServiceRegistry: Send + Sync {
    async fn upsert(
        &self,
        project_id: &str,
        info: HttpServiceProxyInfo,
    ) -> SandboxApiResult<HttpServiceProxyInfo>;
    async fn list(&self, project_id: &str) -> SandboxApiResult<Vec<HttpServiceProxyInfo>>;
    async fn get(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>>;
    async fn remove(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>>;
    async fn create_preview_session(
        &self,
        token: &str,
        record: PreviewSessionRecord,
        ttl_seconds: i64,
    ) -> SandboxApiResult<()>;
    async fn get_preview_session(
        &self,
        token: &str,
    ) -> SandboxApiResult<Option<PreviewSessionRecord>>;
    async fn upsert_terminal_session(
        &self,
        record: TerminalSessionRecord,
        ttl_seconds: i64,
    ) -> SandboxApiResult<()>;
    async fn get_terminal_session(
        &self,
        project_id: &str,
        session_id: &str,
    ) -> SandboxApiResult<Option<TerminalSessionRecord>>;
    async fn create_mcp_upstream_token(
        &self,
        record: McpUpstreamTokenRecord,
        ttl_seconds: i64,
    ) -> SandboxApiResult<()>;
}

struct InMemoryHttpServiceRegistry {
    services: Mutex<BTreeMap<String, BTreeMap<String, HttpServiceProxyInfo>>>,
    preview_sessions: Mutex<BTreeMap<String, PreviewSessionRecord>>,
    terminal_sessions: Mutex<BTreeMap<String, TerminalSessionRecord>>,
    mcp_upstream_tokens: Mutex<BTreeMap<String, McpUpstreamTokenRecord>>,
}

impl InMemoryHttpServiceRegistry {
    fn new() -> Self {
        Self {
            services: Mutex::new(BTreeMap::new()),
            preview_sessions: Mutex::new(BTreeMap::new()),
            terminal_sessions: Mutex::new(BTreeMap::new()),
            mcp_upstream_tokens: Mutex::new(BTreeMap::new()),
        }
    }
}

pub(crate) fn in_memory_http_service_registry() -> SharedHttpServiceRegistry {
    Arc::new(InMemoryHttpServiceRegistry::new())
}

#[async_trait]
impl HttpServiceRegistry for InMemoryHttpServiceRegistry {
    async fn upsert(
        &self,
        project_id: &str,
        info: HttpServiceProxyInfo,
    ) -> SandboxApiResult<HttpServiceProxyInfo> {
        let mut services = self
            .services
            .lock()
            .map_err(|_| SandboxApiError::internal("http service registry mutex poisoned"))?;
        services
            .entry(project_id.to_string())
            .or_default()
            .insert(info.service_id.clone(), info.clone());
        Ok(info)
    }

    async fn list(&self, project_id: &str) -> SandboxApiResult<Vec<HttpServiceProxyInfo>> {
        let services = self
            .services
            .lock()
            .map_err(|_| SandboxApiError::internal("http service registry mutex poisoned"))?;
        Ok(services
            .get(project_id)
            .map(|project_services| project_services.values().cloned().collect())
            .unwrap_or_default())
    }

    async fn get(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        let services = self
            .services
            .lock()
            .map_err(|_| SandboxApiError::internal("http service registry mutex poisoned"))?;
        Ok(services
            .get(project_id)
            .and_then(|project_services| project_services.get(service_id))
            .cloned())
    }

    async fn remove(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        let mut services = self
            .services
            .lock()
            .map_err(|_| SandboxApiError::internal("http service registry mutex poisoned"))?;
        let Some(project_services) = services.get_mut(project_id) else {
            return Ok(None);
        };
        let removed = project_services.remove(service_id);
        if project_services.is_empty() {
            services.remove(project_id);
        }
        Ok(removed)
    }

    async fn create_preview_session(
        &self,
        token: &str,
        record: PreviewSessionRecord,
        _ttl_seconds: i64,
    ) -> SandboxApiResult<()> {
        self.preview_sessions
            .lock()
            .map_err(|_| SandboxApiError::internal("preview session mutex poisoned"))?
            .insert(token.to_string(), record);
        Ok(())
    }

    async fn get_preview_session(
        &self,
        token: &str,
    ) -> SandboxApiResult<Option<PreviewSessionRecord>> {
        let now = now_ms();
        let mut sessions = self
            .preview_sessions
            .lock()
            .map_err(|_| SandboxApiError::internal("preview session mutex poisoned"))?;
        sessions.retain(|_, session| session.expires_at_ms > now);
        Ok(sessions.get(token).cloned())
    }

    async fn upsert_terminal_session(
        &self,
        record: TerminalSessionRecord,
        _ttl_seconds: i64,
    ) -> SandboxApiResult<()> {
        let key = terminal_session_storage_key(&record.project_id, &record.session_id);
        self.terminal_sessions
            .lock()
            .map_err(|_| SandboxApiError::internal("terminal session mutex poisoned"))?
            .insert(key, record);
        Ok(())
    }

    async fn get_terminal_session(
        &self,
        project_id: &str,
        session_id: &str,
    ) -> SandboxApiResult<Option<TerminalSessionRecord>> {
        let now = now_ms();
        let mut sessions = self
            .terminal_sessions
            .lock()
            .map_err(|_| SandboxApiError::internal("terminal session mutex poisoned"))?;
        sessions.retain(|_, session| session.expires_at_ms > now);
        Ok(sessions
            .get(&terminal_session_storage_key(project_id, session_id))
            .cloned())
    }

    async fn create_mcp_upstream_token(
        &self,
        record: McpUpstreamTokenRecord,
        _ttl_seconds: i64,
    ) -> SandboxApiResult<()> {
        let now = now_ms();
        let mut tokens = self
            .mcp_upstream_tokens
            .lock()
            .map_err(|_| SandboxApiError::internal("mcp upstream token mutex poisoned"))?;
        tokens.retain(|_, token| token.expires_at_ms > now);
        tokens.insert(record.token.clone(), record);
        Ok(())
    }
}

#[async_trait]
impl HttpServiceRegistry for agistack_adapters_redis::RedisSandboxHttpRegistry {
    async fn upsert(
        &self,
        project_id: &str,
        info: HttpServiceProxyInfo,
    ) -> SandboxApiResult<HttpServiceProxyInfo> {
        let record = redis_service_record_from_info(&info);
        agistack_adapters_redis::RedisSandboxHttpRegistry::upsert_http_service(
            self, project_id, &record,
        )
        .await
        .map_err(SandboxApiError::internal)?;
        Ok(info)
    }

    async fn list(&self, project_id: &str) -> SandboxApiResult<Vec<HttpServiceProxyInfo>> {
        agistack_adapters_redis::RedisSandboxHttpRegistry::list_http_services(self, project_id)
            .await
            .map_err(SandboxApiError::internal)?
            .into_iter()
            .map(info_from_redis_service_record)
            .collect()
    }

    async fn get(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        agistack_adapters_redis::RedisSandboxHttpRegistry::get_http_service(
            self, project_id, service_id,
        )
        .await
        .map_err(SandboxApiError::internal)?
        .map(info_from_redis_service_record)
        .transpose()
    }

    async fn remove(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        let existing = self.get(project_id, service_id).await?;
        if existing.is_some() {
            agistack_adapters_redis::RedisSandboxHttpRegistry::remove_http_service(
                self, project_id, service_id,
            )
            .await
            .map_err(SandboxApiError::internal)?;
        }
        Ok(existing)
    }

    async fn create_preview_session(
        &self,
        token: &str,
        record: PreviewSessionRecord,
        ttl_seconds: i64,
    ) -> SandboxApiResult<()> {
        let record = agistack_adapters_redis::SandboxPreviewSessionRecord {
            project_id: record.project_id,
            service_id: record.service_id,
            expires_at_ms: record.expires_at_ms,
        };
        agistack_adapters_redis::RedisSandboxHttpRegistry::create_preview_session(
            self,
            token,
            &record,
            ttl_seconds.max(1) as u64,
        )
        .await
        .map_err(SandboxApiError::internal)
    }

    async fn get_preview_session(
        &self,
        token: &str,
    ) -> SandboxApiResult<Option<PreviewSessionRecord>> {
        let record =
            agistack_adapters_redis::RedisSandboxHttpRegistry::get_preview_session(self, token)
                .await
                .map_err(SandboxApiError::internal)?;
        Ok(record.map(|record| PreviewSessionRecord {
            project_id: record.project_id,
            service_id: record.service_id,
            expires_at_ms: record.expires_at_ms,
        }))
    }

    async fn upsert_terminal_session(
        &self,
        record: TerminalSessionRecord,
        ttl_seconds: i64,
    ) -> SandboxApiResult<()> {
        let record = agistack_adapters_redis::SandboxTerminalSessionRecord {
            project_id: record.project_id,
            session_id: record.session_id,
            cols: record.cols,
            rows: record.rows,
            connected: record.connected,
            last_seen_at_ms: record.last_seen_at_ms,
            expires_at_ms: record.expires_at_ms,
        };
        agistack_adapters_redis::RedisSandboxHttpRegistry::upsert_terminal_session(
            self,
            &record,
            ttl_seconds.max(1) as u64,
        )
        .await
        .map_err(SandboxApiError::internal)
    }

    async fn get_terminal_session(
        &self,
        project_id: &str,
        session_id: &str,
    ) -> SandboxApiResult<Option<TerminalSessionRecord>> {
        let record = agistack_adapters_redis::RedisSandboxHttpRegistry::get_terminal_session(
            self, project_id, session_id,
        )
        .await
        .map_err(SandboxApiError::internal)?;
        Ok(record.map(|record| TerminalSessionRecord {
            project_id: record.project_id,
            session_id: record.session_id,
            cols: record.cols,
            rows: record.rows,
            connected: record.connected,
            last_seen_at_ms: record.last_seen_at_ms,
            expires_at_ms: record.expires_at_ms,
        }))
    }

    async fn create_mcp_upstream_token(
        &self,
        record: McpUpstreamTokenRecord,
        ttl_seconds: i64,
    ) -> SandboxApiResult<()> {
        let record = agistack_adapters_redis::SandboxMcpUpstreamTokenRecord {
            token: record.token,
            project_id: record.project_id,
            sandbox_id: record.sandbox_id,
            issued_at_ms: record.issued_at_ms,
            expires_at_ms: record.expires_at_ms,
        };
        agistack_adapters_redis::RedisSandboxHttpRegistry::create_mcp_upstream_token(
            self,
            &record,
            ttl_seconds.max(1) as u64,
        )
        .await
        .map_err(SandboxApiError::internal)
    }
}
