//! Explicit local CDP providers share the existing scoped browser tool host.
mod endpoint;
mod provider;
mod registry;
mod transport;

pub(crate) use registry::CdpRegistry;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CdpEndpointConfig {
    pub id: String,
    pub name: String,
    pub endpoint: String,
    #[serde(default)]
    pub enabled: bool,
}

pub(crate) fn validate_configs(configs: &[CdpEndpointConfig]) -> Result<(), String> {
    let mut ids = std::collections::HashSet::new();
    for config in configs {
        let id = uuid::Uuid::parse_str(&config.id).map_err(|_| "cdp_provider_id_invalid")?;
        if id.to_string() != config.id
            || !ids.insert(id)
            || config.name.trim().is_empty()
            || config.name.len() > 256
        {
            return Err("cdp_provider_config_invalid".into());
        }
        endpoint::validate(&config.endpoint)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests;
#[cfg(test)]
mod tests_chromium;
