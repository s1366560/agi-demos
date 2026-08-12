//! Structured external Provider Registry validation contract.

use async_trait::async_trait;
use thiserror::Error;

use crate::{ModelId, ProviderId, TenantId, WorkspaceCommandError};

/// Scoped Provider/model pair sent to the external registry authority.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProviderRegistryLookup {
    tenant_id: TenantId,
    provider_id: ProviderId,
    model_id: ModelId,
}

impl ProviderRegistryLookup {
    #[must_use]
    pub const fn new(tenant_id: TenantId, provider_id: ProviderId, model_id: ModelId) -> Self {
        Self {
            tenant_id,
            provider_id,
            model_id,
        }
    }

    #[must_use]
    pub const fn tenant_id(&self) -> &TenantId {
        &self.tenant_id
    }

    #[must_use]
    pub const fn provider_id(&self) -> &ProviderId {
        &self.provider_id
    }

    #[must_use]
    pub const fn model_id(&self) -> &ModelId {
        &self.model_id
    }
}

/// One registry-authorized route target.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProviderRegistryRoute {
    provider_id: ProviderId,
    model_id: ModelId,
}

impl ProviderRegistryRoute {
    /// Parse a trusted registry response into bounded identifiers.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceCommandError`] when either identifier is blank or
    /// exceeds the persisted public contract width.
    pub fn parse(
        provider_id: impl Into<String>,
        model_id: impl Into<String>,
    ) -> Result<Self, WorkspaceCommandError> {
        Ok(Self {
            provider_id: ProviderId::parse(provider_id)?,
            model_id: ModelId::parse(model_id)?,
        })
    }

    #[must_use]
    pub const fn provider_id(&self) -> &ProviderId {
        &self.provider_id
    }

    #[must_use]
    pub const fn model_id(&self) -> &ModelId {
        &self.model_id
    }
}

/// External Provider Registry transport failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum ProviderRegistryPortError {
    #[error("Provider Registry is unavailable")]
    Unavailable,
}

/// Authority port for Provider/model validation and tenant defaults.
#[async_trait]
pub trait ProviderRegistryPort: Send + Sync {
    /// Verify one scoped Provider/model pair.
    ///
    /// # Errors
    ///
    /// Returns [`ProviderRegistryPortError`] when the external authority
    /// cannot return a trusted structured answer.
    async fn resolve(
        &self,
        lookup: &ProviderRegistryLookup,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError>;

    /// Return the explicit default route selected by the tenant registry.
    ///
    /// # Errors
    ///
    /// Returns [`ProviderRegistryPortError`] when the external authority is
    /// unavailable. `Ok(None)` means the tenant has no configured default.
    async fn tenant_default(
        &self,
        tenant_id: &TenantId,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registry_route_rejects_blank_and_oversized_model_ids() {
        assert!(matches!(
            ProviderRegistryRoute::parse("provider-1", " "),
            Err(WorkspaceCommandError::Blank { field: "model_id" })
        ));
        assert!(matches!(
            ProviderRegistryRoute::parse(
                "provider-1",
                "m".repeat(super::super::MODEL_ID_MAX_CHARS + 1)
            ),
            Err(WorkspaceCommandError::TooLong {
                field: "model_id",
                ..
            })
        ));
    }
}
