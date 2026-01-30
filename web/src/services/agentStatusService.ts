/**
 * Agent Status Service - Workflow and Session status monitoring
 */

import { httpClient } from './client/httpClient';

const api = httpClient;

export interface WorkflowStatus {
  workflow_id: string;
  run_id: string;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELED' | 'TERMINATED' | 'TIMED_OUT' | 'UNKNOWN';
  started_at?: string;
  completed_at?: string;
}

export interface AgentSessionStatus {
  is_initialized: boolean;
  is_active: boolean;
  total_chats: number;
  active_chats: number;
  tool_count: number;
  cached_since?: string;
  workflow_id?: string;
}

/**
 * Get workflow status for a conversation
 */
export async function getWorkflowStatus(
  conversationId: string,
  messageId?: string
): Promise<WorkflowStatus> {
  const params = messageId ? `?message_id=${encodeURIComponent(messageId)}` : '';
  const response = await api.get(`/api/v1/agent/conversations/${conversationId}/workflow-status${params}`);
  return (response as { data: WorkflowStatus }).data;
}

/**
 * Get agent session status for a project
 */
export async function getAgentSessionStatus(
  projectId: string
): Promise<AgentSessionStatus> {
  const response = await api.get(`/api/v1/agent/projects/${projectId}/session-status`);
  return (response as { data: AgentSessionStatus }).data;
}

export const agentStatusService = {
  getWorkflowStatus,
  getAgentSessionStatus,
};
