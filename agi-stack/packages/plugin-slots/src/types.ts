/**
 * Frontend plugin slot contract (P3), mirroring
 * `src/domain/ports/plugins/ui.py` on the backend.
 */

export type UiSlotKind =
  | 'nav_item'
  | 'settings_page'
  | 'conversation_renderer'
  | 'tool_result_renderer'
  | 'composer_action'
  | 'mcp_canvas';

export interface UiSlotDefinition {
  pluginId: string;
  slot: UiSlotKind;
  id: string;
  moduleRef: string;
  permission: string;
  sandbox: boolean;
}

export interface PlatformPluginSnapshotPayload {
  schema_version: number;
  profile_id: string;
  plugins: PlatformPluginSnapshotRow[];
  digest: string;
}

export interface PlatformPluginSnapshotRow {
  id: string;
  provides: PlatformPluginCapability[];
  config?: Record<string, unknown>;
}

export interface PlatformPluginCapability {
  kind: string;
  id: string;
  contract: string;
  config_schema?: Record<string, unknown>;
  permissions?: string[] | undefined;
}

export interface PlatformPluginSnapshotResponse {
  version: number;
  nonce: string;
  profile_id: string;
  digest: string;
  payload: PlatformPluginSnapshotPayload;
}
