// Generated from shared/schemas/plugins/platform-plugin-protocol.v2.schema.json.
// Schema SHA-256: 29d898f99289918dcdae5beb63e091ffb9f85f34470d8c6c191b2ec5e59277a5
// Do not edit by hand; run scripts/generate_plugin_protocol_v2.py.

export type ScopeKindV2 = 'root' | 'tenant' | 'project' | 'session';

export type RuntimeKindV2 =
  | 'python-trusted'
  | 'rust-native'
  | 'wasm'
  | 'mcp'
  | 'subprocess'
  | 'frontend';

export type TrustKindV2 = 'builtin' | 'signed' | 'tenant-approved' | 'untrusted';

export type RestartPolicyV2 = 'hot-generation' | 'process-boundary';

export type ApplyStatusV2 = 'ack' | 'nack';

export type PublicationStatusV2 = 'reconciling' | 'ready' | 'degraded';

export type DataPlaneTargetV2 =
  | 'python'
  | 'rust-server'
  | 'desktop-sidecar'
  | 'web'
  | 'desktop-renderer';

export type EventModeV2 = 'emit' | 'serial' | 'bail' | 'waterfall';

export type ProfileLayerKindV2 = 'bundle' | 'profile' | 'tenant' | 'project' | 'session';

export interface ScopeV2 {
  readonly kind: ScopeKindV2;
  readonly tenant_id?: string | null;
  readonly project_id?: string | null;
  readonly session_id?: string | null;
}

export interface QuotaV2 {
  readonly max_wasm_fuel?: number;
  readonly max_wasm_memory_bytes?: number;
  readonly max_wall_time_ms?: number;
  readonly max_concurrent_calls?: number;
  readonly max_output_bytes?: number;
  readonly max_network_requests_per_minute?: number;
  readonly max_storage_bytes?: number;
  readonly max_monthly_usd_micros?: number;
}

export interface ArtifactReferenceV2 {
  readonly digest: string;
  readonly source: string;
  readonly signature?: string | null;
  readonly provenance?: string | null;
}

export interface ServiceProvidedV2 {
  readonly service: string;
  readonly version: string;
}

export interface ServiceRequiredV2 {
  readonly alias: string;
  readonly service: string;
  readonly version: string;
}

export interface ServiceContractV2 {
  readonly provides: ReadonlyArray<ServiceProvidedV2>;
  readonly requires: ReadonlyArray<ServiceRequiredV2>;
}

export type JsonSchemaV2 = Readonly<Record<string, unknown>>;

export interface EventContractV2 {
  readonly event: string;
  readonly mode: EventModeV2;
  readonly payload_schema: JsonSchemaV2;
  readonly result_schema: JsonSchemaV2;
}

export interface EventContractsV2 {
  readonly emits: ReadonlyArray<EventContractV2>;
  readonly handles: ReadonlyArray<EventContractV2>;
}

export interface PluginContractV2 {
  readonly services: ServiceContractV2;
  readonly events: EventContractsV2;
  readonly config_schema: JsonSchemaV2;
}

export interface PluginModuleV2 {
  readonly module_ref: string;
  readonly entrypoint: string;
  readonly artifact: ArtifactReferenceV2;
  readonly targets: ReadonlyArray<DataPlaneTargetV2>;
  readonly contract: PluginContractV2;
  readonly contract_digest: string;
}

export interface PluginManifestV2 {
  readonly schema_version: number;
  readonly plugin_id: string;
  readonly version: string;
  readonly runtime: RuntimeKindV2;
  readonly trust: TrustKindV2;
  readonly modules: ReadonlyArray<PluginModuleV2>;
  readonly permissions: ReadonlyArray<string>;
  readonly quotas: QuotaV2;
}

export interface ProfileEntryV2 {
  readonly entry_id: string;
  readonly parent_entry_id: string | null;
  readonly plugin_ref: string;
  readonly module_ref: string;
  readonly enabled: boolean;
  readonly config: Readonly<Record<string, unknown>>;
  readonly inject: Readonly<Record<string, string>>;
  readonly isolate: Readonly<Record<string, string>>;
  readonly scope: ScopeV2;
  readonly permissions: ReadonlyArray<string>;
  readonly quotas: QuotaV2;
  readonly restart_policy: RestartPolicyV2;
}

export interface BundleReferenceV2 {
  readonly bundle_id: string;
  readonly version: string;
  readonly digest: string;
  readonly source: string;
}

export interface BundleArtifactV2 {
  readonly artifact_id: string;
  readonly target: DataPlaneTargetV2;
  readonly path: string;
  readonly digest: string;
  readonly size_bytes: number;
  readonly media_type: string;
}

export interface ProfileLayerV2 {
  readonly layer_id: string;
  readonly kind: ProfileLayerKindV2;
  readonly scope: ScopeV2;
  readonly entries: ReadonlyArray<ProfileEntryV2>;
  readonly replacements: ReadonlyArray<ProfileEntryV2>;
  readonly disabled_entry_ids: ReadonlyArray<string>;
}

export interface ProfileSourceV2 {
  readonly schema_version: number;
  readonly source_id: string;
  readonly profile_id: string;
  readonly revision: number;
  readonly digest: string;
  readonly provenance: string | null;
  readonly layers: ReadonlyArray<ProfileLayerV2>;
}

export interface ProfileSourceReferenceV2 {
  readonly source_id: string;
  readonly revision: number;
  readonly digest: string;
}

export interface BundleManifestV2 {
  readonly schema_version: number;
  readonly bundle_id: string;
  readonly version: string;
  readonly manifests: ReadonlyArray<PluginManifestV2>;
  readonly layers: ReadonlyArray<ProfileLayerV2>;
  readonly artifacts: ReadonlyArray<BundleArtifactV2>;
  readonly digest: string;
  readonly signature: string | null;
  readonly provenance: string | null;
}

export interface DesiredBundleSetV2 {
  readonly schema_version: number;
  readonly desired_set_id: string;
  readonly revision: number;
  readonly bundles: ReadonlyArray<BundleReferenceV2>;
  readonly profile_source: ProfileSourceReferenceV2;
  readonly digest: string;
}

export interface ProfileSnapshotV2 {
  readonly schema_version: number;
  readonly profile_id: string;
  readonly generation: number;
  readonly manifests: ReadonlyArray<PluginManifestV2>;
  readonly entries: ReadonlyArray<ProfileEntryV2>;
  readonly digest: string;
}

export interface ControlPlaneEnvelopeV2 {
  readonly version: number;
  readonly nonce: string;
  readonly snapshot_digest: string;
  readonly type_url: string;
}

export interface SnapshotApplyReceiptV2 {
  readonly status: ApplyStatusV2;
  readonly requested_version: number;
  readonly requested_digest: string;
  readonly applied_version: number | null;
  readonly applied_digest: string | null;
  readonly error_code: string | null;
  readonly error_message: string | null;
}
