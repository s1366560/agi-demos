use serde::Deserialize;

use super::error::ChannelApiError;

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ChannelConfigQuery {
    pub(crate) channel_type: Option<String>,
    #[serde(default)]
    pub(crate) enabled_only: bool,
    pub(crate) limit: Option<i64>,
    pub(crate) offset: Option<i64>,
}

impl ChannelConfigQuery {
    pub(super) fn validated(&self) -> Result<ValidatedChannelConfigQuery<'_>, ChannelApiError> {
        let limit = self.limit.unwrap_or(100);
        if !(1..=500).contains(&limit) {
            return Err(ChannelApiError::unprocessable(
                "limit must be greater than or equal to 1 and less than or equal to 500",
            ));
        }
        let offset = self.offset.unwrap_or(0);
        if offset < 0 {
            return Err(ChannelApiError::unprocessable(
                "offset must be greater than or equal to 0",
            ));
        }
        Ok(ValidatedChannelConfigQuery {
            channel_type: self
                .channel_type
                .as_deref()
                .map(str::trim)
                .filter(|value| !value.is_empty()),
            enabled_only: self.enabled_only,
            limit,
            offset,
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ValidatedChannelConfigQuery<'a> {
    pub(crate) channel_type: Option<&'a str>,
    pub(crate) enabled_only: bool,
    pub(crate) limit: i64,
    pub(crate) offset: i64,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ChannelOutboxQuery {
    #[serde(rename = "status")]
    pub(crate) status_filter: Option<String>,
    pub(crate) limit: Option<i64>,
    pub(crate) offset: Option<i64>,
}

impl ChannelOutboxQuery {
    pub(super) fn validated(&self) -> Result<ValidatedChannelOutboxQuery<'_>, ChannelApiError> {
        let page = ChannelPageQueryParams {
            limit: self.limit,
            offset: self.offset,
        }
        .validated(200)?;
        let status_filter = self
            .status_filter
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty());
        if let Some(status) = status_filter {
            if !is_valid_outbox_status(status) {
                return Err(ChannelApiError::unprocessable(
                    "status must be one of pending, failed, sent, dead_letter",
                ));
            }
        }
        Ok(ValidatedChannelOutboxQuery {
            status_filter,
            limit: page.limit,
            offset: page.offset,
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ValidatedChannelOutboxQuery<'a> {
    pub(crate) status_filter: Option<&'a str>,
    pub(crate) limit: i64,
    pub(crate) offset: i64,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ChannelPageQueryParams {
    pub(crate) limit: Option<i64>,
    pub(crate) offset: Option<i64>,
}

impl ChannelPageQueryParams {
    pub(super) fn validated(
        &self,
        max_limit: i64,
    ) -> Result<ValidatedChannelPageQuery, ChannelApiError> {
        let limit = self.limit.unwrap_or(50);
        if !(1..=max_limit).contains(&limit) {
            return Err(ChannelApiError::unprocessable(format!(
                "limit must be greater than or equal to 1 and less than or equal to {max_limit}",
            )));
        }
        let offset = self.offset.unwrap_or(0);
        if offset < 0 {
            return Err(ChannelApiError::unprocessable(
                "offset must be greater than or equal to 0",
            ));
        }
        Ok(ValidatedChannelPageQuery { limit, offset })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ValidatedChannelPageQuery {
    pub(crate) limit: i64,
    pub(crate) offset: i64,
}

fn is_valid_outbox_status(status: &str) -> bool {
    matches!(status, "pending" | "failed" | "sent" | "dead_letter")
}
