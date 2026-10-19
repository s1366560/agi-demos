export type ComputerUseConsentScope = "once" | "session" | "always";
export type ComputerUsePhase =
  | "idle"
  | "observing"
  | "acting"
  | "awaiting_permission"
  | "paused"
  | "stopped"
  | "focus_required"
  | "error";
export interface ComputerUseImageArtifact {
  readonly artifact_id: string;
  readonly mime_type: string;
  readonly width?: number;
  readonly height?: number;
  readonly observed_at?: string | number;
  readonly snapshot_id?: string;
  readonly window_id?: string;
}
export interface ComputerUseTarget {
  readonly app_id: string;
  readonly display_name: string;
  readonly process_id?: number;
  readonly identity_digest: string;
  readonly window_id?: string;
  readonly window_title?: string;
}
export interface ComputerUsePresentation {
  readonly phase: ComputerUsePhase;
  readonly updated_at?: string | number;
  readonly target?: ComputerUseTarget;
  readonly app_icon?: ComputerUseImageArtifact;
  readonly preview?: ComputerUseImageArtifact;
  readonly error_code?: string;
  readonly can_resume?: boolean;
  readonly resume_blocked_reason?: string;
}
export interface ComputerUsePendingConsent {
  readonly request_id: string;
  readonly session_id: string;
  readonly app: string;
  readonly capability: string;
  readonly scopes?: readonly ComputerUseConsentScope[];
  readonly target?: ComputerUseTarget;
  readonly app_icon?: ComputerUseImageArtifact;
}
export interface ComputerUseRecording {
  readonly recording_id: string;
  readonly session_id: string;
  readonly conversation_id: string;
  readonly run_id: string;
  readonly source: 'microphone' | 'system' | 'mixed';
  readonly status: 'recording' | 'stopping' | 'pending_export' | 'saved' | 'failed';
  readonly started_at: string;
  readonly ended_at?: string | null;
  readonly elapsed_ms?: number | null;
  readonly end_reason?: string | null;
  readonly error_code?: string | null;
  readonly can_retry_export?: boolean;
  readonly partial?: boolean;
  readonly artifacts: readonly {
    readonly artifact_id: string;
    readonly kind: 'audio';
    readonly mime_type: string;
    readonly source?: 'microphone' | 'system' | 'mixed';
  }[];
}
/** Show only the native pending request's concrete scope options. */
export function computerUseConsentScopes(
  pending: ComputerUsePendingConsent | undefined,
): readonly ComputerUseConsentScope[] {
  if (pending?.capability === "connector_action") return ["once"];
  const scopes = pending?.scopes;
  if (
    !scopes?.length ||
    scopes.some((scope) => !["once", "session", "always"].includes(scope))
  )
    return ["once"];
  return [...new Set(scopes)];
}
export interface ComputerUseSnapshot {
  readonly execution?: {
    readonly local: boolean;
    readonly cloud: boolean;
    readonly reason?: string;
  };
  readonly plugin_id: "memstack-computer-use";
  readonly device_id: string;
  readonly helper_available: boolean;
  readonly scope: { readonly tenant_id: string; readonly project_id: string };
  readonly instance: {
    readonly installed: boolean;
    readonly enabled: boolean;
    readonly revision: number;
    readonly microphone: boolean;
    readonly system_audio: boolean;
    readonly locked_use: boolean;
  };
  readonly pending: readonly ComputerUsePendingConsent[];
  readonly grants: readonly {
    readonly id: string;
    readonly app: string;
    readonly capability: string;
    readonly scope: ComputerUseConsentScope;
  }[];
  readonly sessions: readonly {
    readonly session_id: string;
    readonly conversation_id: string;
    readonly run_id: string;
    readonly stopped: boolean;
    readonly presentation?: ComputerUsePresentation;
  }[];
  readonly recent_presentation?: ComputerUsePresentation;
  readonly recordings?: readonly ComputerUseRecording[];
  readonly connectors?: readonly {
    readonly account_id: string;
    readonly provider: string;
    readonly capability: string;
    readonly available: boolean;
    readonly tools: readonly string[];
  }[];
  readonly accounts?: readonly {
    readonly account_id: string;
    readonly provider: string;
    readonly status: string;
    readonly reason?: string;
    readonly authorization_url?: string;
  }[];
  readonly permissions?: Readonly<
    Record<
      string,
      {
        readonly state:
          | "granted"
          | "denied"
          | "not_determined"
          | "unavailable"
          | "unverified";
        readonly detail?: string;
      }
    >
  >;
}
export type ComputerUseOperation = Readonly<{
  action:
    | "status"
    | "install"
    | "enable"
    | "disable"
    | "uninstall"
    | "configure"
    | "grant"
    | "decline"
    | "revoke"
    | "stop"
    | "stop_all"
    | "pause"
    | "resume"
    | "artifact_preview"
    | "audio_chunk"
    | "audio_stop"
    | "connector_connect"
    | "connector_start"
    | "connector_cancel"
    | "connector_disconnect"
    | "permissions_status"
    | "permission_request";
  expected_revision?: number;
  capability?:
    | "microphone"
    | "system_audio"
    | "locked_use"
    | "accessibility"
    | "input_monitoring"
    | "screen_capture"
    | "calendar"
    | "contacts"
    | "messages";
  enabled?: boolean;
  request_id?: string;
  scope?: ComputerUseConsentScope;
  grant_id?: string;
  session_id?: string;
  recording_id?: string;
  artifact_id?: string;
  offset?: number;
  provider?: "google" | "microsoft365";
  client_id?: string;
  account_id?: string;
}>;
export interface ComputerUseClientV2 {
  snapshot(signal?: AbortSignal): Promise<ComputerUseSnapshot>;
  manage(
    operation: ComputerUseOperation,
    signal?: AbortSignal,
  ): Promise<ComputerUseSnapshot>;
  preview(artifactId: string, signal?: AbortSignal): Promise<string>;
  audio(artifactId: string, signal?: AbortSignal): Promise<Blob>;
}
export type ComputerUseNativeInvoke = (
  command: string,
  args: Record<string, unknown>,
) => Promise<unknown>;

export function isComputerUseSnapshotForScope(
  value: unknown,
  scope: Readonly<{ tenantId: string; projectId: string }>,
): value is ComputerUseSnapshot {
  const result = value as ComputerUseSnapshot;
  return (
    result?.plugin_id === "memstack-computer-use" &&
    result.scope?.tenant_id === scope.tenantId &&
    result.scope?.project_id === scope.projectId &&
    Number.isSafeInteger(result.instance?.revision) &&
    Array.isArray(result.sessions) &&
    Array.isArray(result.pending) &&
    Array.isArray(result.grants) &&
    (result.recordings === undefined ||
      (Array.isArray(result.recordings) && result.recordings.every(isRecording)))
  );
}

function isRecording(value: unknown): value is ComputerUseRecording {
  if (!value || typeof value !== 'object') return false;
  const recording = value as ComputerUseRecording;
  return ['recording_id', 'session_id', 'conversation_id', 'run_id', 'started_at'].every(
    (key) => typeof recording[key as keyof ComputerUseRecording] === 'string' &&
      (recording[key as keyof ComputerUseRecording] as string).length > 0
  ) && ['microphone', 'system', 'mixed'].includes(recording.source) &&
    ['recording', 'stopping', 'pending_export', 'saved', 'failed'].includes(recording.status) &&
    (recording.can_retry_export === undefined || typeof recording.can_retry_export === 'boolean') &&
    (recording.partial === undefined || typeof recording.partial === 'boolean') &&
    ['ended_at', 'end_reason', 'error_code'].every((key) =>
      recording[key as keyof ComputerUseRecording] == null ||
      typeof recording[key as keyof ComputerUseRecording] === 'string') &&
    (recording.elapsed_ms == null ||
      (Number.isFinite(recording.elapsed_ms) && recording.elapsed_ms >= 0)) &&
    Array.isArray(recording.artifacts) && recording.artifacts.every((artifact) =>
      artifact?.kind === 'audio' && typeof artifact.artifact_id === 'string' &&
      /^cua-audio-[0-9a-f-]+$/u.test(artifact.artifact_id) && typeof artifact.mime_type === 'string'
    );
}
