//! Only the real authorized host can produce plugin metadata for the persisted timeline.
use super::LocalPluginToolHostV2;
use agistack_core::ports::ToolHost;
use std::{collections::BTreeSet, sync::Arc};

#[derive(Default)]
pub(in crate::local_runtime) struct PluginTimelineMetadataV2 {
    host: Option<Arc<LocalPluginToolHostV2>>,
    allowed_names: BTreeSet<String>,
}
impl PluginTimelineMetadataV2 {
    pub(super) fn capture(host: Arc<LocalPluginToolHostV2>) -> Self {
        Self {
            allowed_names: host.list_tools().into_iter().collect(),
            host: Some(host),
        }
    }
    pub(in crate::local_runtime) fn restrict_to(mut self, names: &[String]) -> Self {
        self.allowed_names.retain(|name| names.contains(name));
        self
    }
    pub(in crate::local_runtime) fn redact(&self, name: &str, payload: &str) -> Option<String> {
        if !self.allowed_names.contains(name) {
            return None;
        }
        let host = self.host.as_ref()?;
        let unavailable = || Some("[UNAVAILABLE]".to_owned());
        if !host.list_tools().iter().any(|tool| tool == name) {
            return unavailable();
        }
        let tool = host.tools.get(name)?;
        let Ok(generation) = host
            .authority
            .state
            .platform_plugin_authority_v2
            .acquire_generation()
        else {
            return unavailable();
        };
        let descriptor = generation.descriptor();
        if descriptor.profile_id != tool.attribution.profile_id
            || descriptor.generation != tool.attribution.generation
            || descriptor.digest != tool.attribution.snapshot_digest
        {
            return unavailable();
        }
        let metadata = host.metadata();
        let metadata = metadata.get(name)?;
        if metadata.name != name {
            return unavailable();
        }
        let Ok(value) = serde_json::from_str::<serde_json::Value>(payload) else {
            return Some("[UNPARSEABLE]".into());
        };
        let mut fields = super::super::authorized_tool_host::sensitive_input_fields();
        fields.extend(metadata.sensitive_input_fields.iter().cloned());
        let redacted = super::super::tool_authority::redact_sensitive_fields(&value, &fields);
        Some(serde_json::to_string(&redacted).unwrap_or_else(|_| "[UNAVAILABLE]".into()))
    }
}
