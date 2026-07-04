use std::sync::Arc;

use async_trait::async_trait;

use agistack_adapters_postgres::{
    ChannelConfigListQuery, ChannelOutboxListQuery, ChannelPageQuery, PgChannelRepository,
};

use super::{
    error::ChannelApiError,
    queries::{
        ValidatedChannelConfigQuery, ValidatedChannelOutboxQuery, ValidatedChannelPageQuery,
    },
    views::{
        ChannelConfigListView, ChannelConfigView, ChannelOutboxItemView, ChannelOutboxListView,
        ChannelSessionBindingItemView, ChannelSessionBindingListView, ChannelStatusView,
    },
};

pub(crate) type SharedChannels = Arc<dyn ChannelService>;

#[async_trait]
pub(crate) trait ChannelService: Send + Sync {
    async fn list_project_configs(
        &self,
        user_id: &str,
        project_id: &str,
        query: ValidatedChannelConfigQuery<'_>,
    ) -> Result<ChannelConfigListView, ChannelApiError>;

    async fn get_config(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelConfigView, ChannelApiError>;

    async fn get_status(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError>;

    async fn list_project_outbox(
        &self,
        user_id: &str,
        project_id: &str,
        query: ValidatedChannelOutboxQuery<'_>,
    ) -> Result<ChannelOutboxListView, ChannelApiError>;

    async fn list_project_session_bindings(
        &self,
        user_id: &str,
        project_id: &str,
        query: ValidatedChannelPageQuery,
    ) -> Result<ChannelSessionBindingListView, ChannelApiError>;
}

pub(crate) struct PgChannelService {
    repo: PgChannelRepository,
}

impl PgChannelService {
    pub(crate) fn new(repo: PgChannelRepository) -> Self {
        Self { repo }
    }

    async fn ensure_project_access(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<(), ChannelApiError> {
        if self
            .repo
            .user_has_project_access(user_id, project_id)
            .await
            .map_err(ChannelApiError::internal)?
        {
            Ok(())
        } else {
            Err(ChannelApiError::forbidden("Access denied to project"))
        }
    }

    async fn ensure_project_admin(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<(), ChannelApiError> {
        if self
            .repo
            .user_is_project_admin(user_id, project_id)
            .await
            .map_err(ChannelApiError::internal)?
        {
            Ok(())
        } else {
            Err(ChannelApiError::forbidden("Access denied to project"))
        }
    }
}

#[async_trait]
impl ChannelService for PgChannelService {
    async fn list_project_configs(
        &self,
        user_id: &str,
        project_id: &str,
        query: ValidatedChannelConfigQuery<'_>,
    ) -> Result<ChannelConfigListView, ChannelApiError> {
        self.ensure_project_access(user_id, project_id).await?;
        let rows = self
            .repo
            .list_configs(ChannelConfigListQuery {
                project_id,
                channel_type: query.channel_type,
                enabled_only: query.enabled_only,
                limit: query.limit,
                offset: query.offset,
            })
            .await
            .map_err(ChannelApiError::internal)?;
        let total = self
            .repo
            .count_configs(project_id, query.channel_type, query.enabled_only)
            .await
            .map_err(ChannelApiError::internal)?;
        Ok(ChannelConfigListView {
            items: rows.into_iter().map(ChannelConfigView::from).collect(),
            total,
        })
    }

    async fn get_config(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelConfigView, ChannelApiError> {
        let config = self
            .repo
            .get_config(config_id)
            .await
            .map_err(ChannelApiError::internal)?
            .ok_or_else(|| ChannelApiError::not_found("Configuration not found"))?;
        self.ensure_project_access(user_id, &config.project_id)
            .await?;
        Ok(ChannelConfigView::from(config))
    }

    async fn get_status(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError> {
        let status = self
            .repo
            .get_status(config_id)
            .await
            .map_err(ChannelApiError::internal)?
            .ok_or_else(|| ChannelApiError::not_found("Configuration not found"))?;
        self.ensure_project_access(user_id, &status.project_id)
            .await?;
        Ok(ChannelStatusView::from(status))
    }

    async fn list_project_outbox(
        &self,
        user_id: &str,
        project_id: &str,
        query: ValidatedChannelOutboxQuery<'_>,
    ) -> Result<ChannelOutboxListView, ChannelApiError> {
        self.ensure_project_admin(user_id, project_id).await?;
        let rows = self
            .repo
            .list_outbox(ChannelOutboxListQuery {
                project_id,
                status_filter: query.status_filter,
                limit: query.limit,
                offset: query.offset,
            })
            .await
            .map_err(ChannelApiError::internal)?;
        let total = self
            .repo
            .count_outbox(project_id, query.status_filter)
            .await
            .map_err(ChannelApiError::internal)?;
        Ok(ChannelOutboxListView {
            items: rows.into_iter().map(ChannelOutboxItemView::from).collect(),
            total,
        })
    }

    async fn list_project_session_bindings(
        &self,
        user_id: &str,
        project_id: &str,
        query: ValidatedChannelPageQuery,
    ) -> Result<ChannelSessionBindingListView, ChannelApiError> {
        self.ensure_project_admin(user_id, project_id).await?;
        let rows = self
            .repo
            .list_session_bindings(ChannelPageQuery {
                project_id,
                limit: query.limit,
                offset: query.offset,
            })
            .await
            .map_err(ChannelApiError::internal)?;
        let total = self
            .repo
            .count_session_bindings(project_id)
            .await
            .map_err(ChannelApiError::internal)?;
        Ok(ChannelSessionBindingListView {
            items: rows
                .into_iter()
                .map(ChannelSessionBindingItemView::from)
                .collect(),
            total,
        })
    }
}

#[derive(Default)]
pub(crate) struct DevChannelService;

impl DevChannelService {
    pub(crate) fn new() -> Self {
        Self
    }
}

#[async_trait]
impl ChannelService for DevChannelService {
    async fn list_project_configs(
        &self,
        _user_id: &str,
        _project_id: &str,
        _query: ValidatedChannelConfigQuery<'_>,
    ) -> Result<ChannelConfigListView, ChannelApiError> {
        Ok(ChannelConfigListView {
            items: Vec::new(),
            total: 0,
        })
    }

    async fn get_config(
        &self,
        _user_id: &str,
        _config_id: &str,
    ) -> Result<ChannelConfigView, ChannelApiError> {
        Err(ChannelApiError::not_found("Configuration not found"))
    }

    async fn get_status(
        &self,
        _user_id: &str,
        _config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError> {
        Err(ChannelApiError::not_found("Configuration not found"))
    }

    async fn list_project_outbox(
        &self,
        _user_id: &str,
        _project_id: &str,
        _query: ValidatedChannelOutboxQuery<'_>,
    ) -> Result<ChannelOutboxListView, ChannelApiError> {
        Ok(ChannelOutboxListView {
            items: Vec::new(),
            total: 0,
        })
    }

    async fn list_project_session_bindings(
        &self,
        _user_id: &str,
        _project_id: &str,
        _query: ValidatedChannelPageQuery,
    ) -> Result<ChannelSessionBindingListView, ChannelApiError> {
        Ok(ChannelSessionBindingListView {
            items: Vec::new(),
            total: 0,
        })
    }
}
