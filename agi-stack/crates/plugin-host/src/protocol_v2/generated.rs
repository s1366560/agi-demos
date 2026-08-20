// Generated from shared/schemas/plugins/platform-plugin-protocol.v2.schema.json.
// Schema SHA-256: 5754a10a8e17beb69de1f7d93f3efb610a1b22d0a8c11dac101c5b064022bead
// Do not edit by hand; run scripts/generate_plugin_protocol_v2.py.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum ScopeKindV2 {
    Root,
    Tenant,
    Project,
    Session,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum RuntimeKindV2 {
    PythonTrusted,
    RustNative,
    Wasm,
    Mcp,
    Subprocess,
    Frontend,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum TrustKindV2 {
    Builtin,
    Signed,
    TenantApproved,
    Untrusted,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum RestartPolicyV2 {
    HotGeneration,
    ProcessBoundary,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum ApplyStatusV2 {
    Ack,
    Nack,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ScopeV2 {
    pub kind: ScopeKindV2,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tenant_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub project_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QuotaV2 {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_wasm_fuel: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_wasm_memory_bytes: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_wall_time_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_concurrent_calls: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_output_bytes: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_network_requests_per_minute: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_storage_bytes: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_monthly_usd_micros: Option<u64>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactReferenceV2 {
    pub digest: String,
    pub source: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub signature: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provenance: Option<String>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PluginModuleV2 {
    pub module_ref: String,
    pub entrypoint: String,
    pub artifact: ArtifactReferenceV2,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PluginManifestV2 {
    pub schema_version: u64,
    pub plugin_id: String,
    pub version: String,
    pub runtime: RuntimeKindV2,
    pub trust: TrustKindV2,
    pub modules: Vec<PluginModuleV2>,
    pub permissions: Vec<String>,
    pub quotas: QuotaV2,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileEntryV2 {
    pub entry_id: String,
    pub parent_entry_id: Option<String>,
    pub plugin_ref: String,
    pub module_ref: String,
    pub enabled: bool,
    pub config: BTreeMap<String, serde_json::Value>,
    pub inject: BTreeMap<String, String>,
    pub isolate: BTreeMap<String, String>,
    pub scope: ScopeV2,
    pub permissions: Vec<String>,
    pub quotas: QuotaV2,
    pub restart_policy: RestartPolicyV2,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileSnapshotV2 {
    pub schema_version: u64,
    pub profile_id: String,
    pub generation: u64,
    pub manifests: Vec<PluginManifestV2>,
    pub entries: Vec<ProfileEntryV2>,
    pub digest: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ControlPlaneEnvelopeV2 {
    pub version: u64,
    pub nonce: String,
    pub snapshot_digest: String,
    pub type_url: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SnapshotApplyReceiptV2 {
    pub status: ApplyStatusV2,
    pub requested_version: u64,
    pub requested_digest: String,
    pub applied_version: Option<u64>,
    pub applied_digest: Option<String>,
    pub error_code: Option<String>,
    pub error_message: Option<String>,
}
