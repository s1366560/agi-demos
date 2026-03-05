// Enums as string union types
export type ScheduleType = 'at' | 'every' | 'cron';
export type PayloadType = 'system_event' | 'agent_turn';
export type DeliveryType = 'none' | 'announce' | 'webhook';
export type ConversationMode = 'reuse' | 'fresh';
export type CronRunStatus = 'success' | 'failed' | 'timeout' | 'skipped';
export type TriggerType = 'scheduled' | 'manual';

// Nested config interfaces
export interface ScheduleConfig {
  kind: ScheduleType;
  config: Record<string, unknown>;
}

export interface PayloadConfig {
  kind: PayloadType;
  config: Record<string, unknown>;
}

export interface DeliveryConfig {
  kind: DeliveryType;
  config: Record<string, unknown>;
}

// Request types
export interface CronJobCreate {
  name: string;
  description?: string | null;
  enabled?: boolean;
  delete_after_run?: boolean;
  schedule: ScheduleConfig;
  payload: PayloadConfig;
  delivery?: DeliveryConfig;
  conversation_mode?: ConversationMode;
  conversation_id?: string | null;
  timezone?: string;
  stagger_seconds?: number;
  timeout_seconds?: number;
  max_retries?: number;
}

export interface CronJobUpdate {
  name?: string | null;
  description?: string | null;
  enabled?: boolean | null;
  delete_after_run?: boolean | null;
  schedule?: ScheduleConfig | null;
  payload?: PayloadConfig | null;
  delivery?: DeliveryConfig | null;
  conversation_mode?: ConversationMode | null;
  conversation_id?: string | null;
  timezone?: string | null;
  stagger_seconds?: number | null;
  timeout_seconds?: number | null;
  max_retries?: number | null;
}

export interface ManualRunRequest {
  conversation_id?: string | null;
}

// Response types
export interface CronJobResponse {
  id: string;
  project_id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  delete_after_run: boolean;
  schedule: ScheduleConfig;
  payload: PayloadConfig;
  delivery: DeliveryConfig;
  conversation_mode: ConversationMode;
  conversation_id: string | null;
  timezone: string;
  stagger_seconds: number;
  timeout_seconds: number;
  max_retries: number;
  state: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface CronJobListResponse {
  items: CronJobResponse[];
  total: number;
}

export interface CronJobRunResponse {
  id: string;
  job_id: string;
  project_id: string;
  status: CronRunStatus;
  trigger_type: TriggerType;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  result_summary: Record<string, unknown>;
  conversation_id: string | null;
}

export interface CronJobRunListResponse {
  items: CronJobRunResponse[];
  total: number;
}
