// Generated from shared/schemas/plugins/platform-plugin-protocol.v2.schema.json.
// Schema SHA-256: 5754a10a8e17beb69de1f7d93f3efb610a1b22d0a8c11dac101c5b064022bead
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

export interface PluginModuleV2 {
  readonly module_ref: string;
  readonly entrypoint: string;
  readonly artifact: ArtifactReferenceV2;
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
