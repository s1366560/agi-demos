import { httpClient } from './client/httpClient';

export type RunInputDelivery = 'steer_now' | 'queue_next';
export type RunInputStatus =
  | 'pending_boundary'
  | 'queued'
  | 'applied'
  | 'ready'
  | 'blocked'
  | 'promoted_to_plan';

export type RunInputAllowedAction = RunInputDelivery | 'promote' | 'kill_run';

export interface ActiveAgentRun {
  conversation_id: string;
  run_id: string;
  turn_id: string;
  run_revision: number;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  allowed_actions: RunInputAllowedAction[];
  authority_revision: number;
}

export interface RunInputCodeRangeReference {
  type: 'code_range';
  snapshot_id: string;
  environment_id: string;
  path: string;
  start_line: number;
  end_line: number;
  side: 'old' | 'new';
  patch_digest: string;
}

export type RunInputReference = RunInputCodeRangeReference;

export interface RunInputContextItem {
  kind: 'attachment' | 'command' | 'thread' | 'agent' | 'skill' | 'plugin';
  resource_id: string;
  label: string;
  metadata?: Record<string, unknown>;
}

export interface AgentRunInput {
  id: string;
  conversation_id: string;
  run_id: string;
  expected_run_revision: number;
  message_id: string;
  idempotency_key: string;
  delivery: RunInputDelivery;
  status: RunInputStatus;
  sequence: number;
  queue_position?: number | null;
  content: string;
  references: RunInputReference[];
  context_items: RunInputContextItem[];
  applied_round?: number | null;
  applied_at?: string | null;
  injected_via: string | null;
  dispatch_status: 'not_required' | 'dispatching' | 'dispatched' | 'failed';
  dispatch_attempts: number;
  dispatch_lease_expires_at: string | null;
  dispatch_error_code: string | null;
  promotion_idempotency_key?: string | null;
  promoted_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateRunInputRequest {
  expected_run_revision: number;
  message: string;
  message_id: string;
  idempotency_key: string;
  delivery: RunInputDelivery;
  references: RunInputReference[];
  context_items: RunInputContextItem[];
}

export interface RunInputReceipt {
  accepted: boolean;
  created: boolean;
  action: 'send_message';
  conversation_id: string;
  message_id: string;
  delivery_mode: RunInputDelivery;
  run_id: string;
  run_revision: number;
  queue_position?: number | null;
  input: AgentRunInput;
}

export interface RunInputList {
  run_id: string;
  run_revision: number;
  inputs: AgentRunInput[];
  total_count: number;
}

export interface PromoteRunInputRequest {
  expected_source_run_revision: number;
  idempotency_key: string;
}

export interface PromoteRunInputReceipt {
  accepted: boolean;
  created: boolean;
  action: 'start_plan_turn';
  input?: AgentRunInput;
  conversation?: Record<string, unknown>;
  source_run?: Record<string, unknown>;
}

const runPath = (runId: string): string => `/agent/runs/${encodeURIComponent(runId)}`;

interface AgentRunProjectionResponse {
  id: string;
  turn_id: string;
  conversation_id: string;
  status: ActiveAgentRun['status'];
  revision: number;
  allowed_actions: RunInputAllowedAction[];
  authority_revision: number;
}

interface ActiveRunResponse {
  active_run: AgentRunProjectionResponse | null;
}

interface LatestRunResponse {
  latest_run: AgentRunProjectionResponse | null;
}

const normalizeRunProjection = (
  projection: AgentRunProjectionResponse | null
): ActiveAgentRun | null =>
  projection
    ? {
        conversation_id: projection.conversation_id,
        run_id: projection.id,
        turn_id: projection.turn_id,
        run_revision: projection.revision,
        status: projection.status,
        allowed_actions: projection.allowed_actions,
        authority_revision: projection.authority_revision,
      }
    : null;

export const runInputService = {
  async getActiveRun(conversationId: string): Promise<ActiveAgentRun | null> {
    const response = await httpClient.get<ActiveRunResponse>(
      `/agent/conversations/${encodeURIComponent(conversationId)}/active-run`
    );
    return normalizeRunProjection(response.active_run);
  },

  async getLatestRun(conversationId: string): Promise<ActiveAgentRun | null> {
    const response = await httpClient.get<LatestRunResponse>(
      `/agent/conversations/${encodeURIComponent(conversationId)}/latest-run`
    );
    return normalizeRunProjection(response.latest_run);
  },

  create(runId: string, request: CreateRunInputRequest): Promise<RunInputReceipt> {
    return httpClient.post(`${runPath(runId)}/inputs`, request);
  },

  list(runId: string): Promise<RunInputList> {
    return httpClient.get(`${runPath(runId)}/inputs`);
  },

  promote(
    runId: string,
    inputId: string,
    request: PromoteRunInputRequest
  ): Promise<PromoteRunInputReceipt> {
    return httpClient.post(
      `${runPath(runId)}/inputs/${encodeURIComponent(inputId)}/promote`,
      request
    );
  },
};
