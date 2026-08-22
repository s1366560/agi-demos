// Generated from shared/schemas/plugins/platform-plugin-protocol.v2.schema.json.
// Schema SHA-256: 29d898f99289918dcdae5beb63e091ffb9f85f34470d8c6c191b2ec5e59277a5
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

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum PublicationStatusV2 {
    Reconciling,
    Ready,
    Degraded,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum DataPlaneTargetV2 {
    Python,
    RustServer,
    DesktopSidecar,
    Web,
    DesktopRenderer,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum EventModeV2 {
    Emit,
    Serial,
    Bail,
    Waterfall,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum ProfileLayerKindV2 {
    Bundle,
    Profile,
    Tenant,
    Project,
    Session,
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
pub struct ServiceProvidedV2 {
    pub service: String,
    pub version: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ServiceRequiredV2 {
    pub alias: String,
    pub service: String,
    pub version: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ServiceContractV2 {
    pub provides: Vec<ServiceProvidedV2>,
    pub requires: Vec<ServiceRequiredV2>,
}

pub type JsonSchemaV2 = BTreeMap<String, serde_json::Value>;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EventContractV2 {
    pub event: String,
    pub mode: EventModeV2,
    pub payload_schema: JsonSchemaV2,
    pub result_schema: JsonSchemaV2,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EventContractsV2 {
    pub emits: Vec<EventContractV2>,
    pub handles: Vec<EventContractV2>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PluginContractV2 {
    pub services: ServiceContractV2,
    pub events: EventContractsV2,
    pub config_schema: JsonSchemaV2,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PluginModuleV2 {
    pub module_ref: String,
    pub entrypoint: String,
    pub artifact: ArtifactReferenceV2,
    pub targets: Vec<DataPlaneTargetV2>,
    pub contract: PluginContractV2,
    pub contract_digest: String,
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
pub struct BundleReferenceV2 {
    pub bundle_id: String,
    pub version: String,
    pub digest: String,
    pub source: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BundleArtifactV2 {
    pub artifact_id: String,
    pub target: DataPlaneTargetV2,
    pub path: String,
    pub digest: String,
    pub size_bytes: u64,
    pub media_type: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileLayerV2 {
    pub layer_id: String,
    pub kind: ProfileLayerKindV2,
    pub scope: ScopeV2,
    pub entries: Vec<ProfileEntryV2>,
    pub replacements: Vec<ProfileEntryV2>,
    pub disabled_entry_ids: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileSourceV2 {
    pub schema_version: u64,
    pub source_id: String,
    pub profile_id: String,
    pub revision: u64,
    pub digest: String,
    pub provenance: Option<String>,
    pub layers: Vec<ProfileLayerV2>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileSourceReferenceV2 {
    pub source_id: String,
    pub revision: u64,
    pub digest: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BundleManifestV2 {
    pub schema_version: u64,
    pub bundle_id: String,
    pub version: String,
    pub manifests: Vec<PluginManifestV2>,
    pub layers: Vec<ProfileLayerV2>,
    pub artifacts: Vec<BundleArtifactV2>,
    pub digest: String,
    pub signature: Option<String>,
    pub provenance: Option<String>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DesiredBundleSetV2 {
    pub schema_version: u64,
    pub desired_set_id: String,
    pub revision: u64,
    pub bundles: Vec<BundleReferenceV2>,
    pub profile_source: ProfileSourceReferenceV2,
    pub digest: String,
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
