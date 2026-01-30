/**
 * Agent Status Service - Workflow and Session status monitoring
 * 
 * ProjectReActAgent Lifecycle Integration:
 * - Tracks complete agent lifecycle from initialization to shutdown
 * - Displays resource counts (tools, skills, subagents)
 * - Shows execution metrics and health status
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

/**
 * ProjectReActAgent Lifecycle State
 * 项目级 ReAct Agent 生命周期状态
 */
export type ProjectAgentLifecycleState =
  | 'uninitialized'   // 未初始化 - Workflow 不存在
  | 'initializing'    // 初始化中 - 正在加载工具、技能等
  | 'ready'           // 就绪 - 可以接收请求
  | 'executing'       // 执行中 - 正在处理聊天请求
  | 'paused'          // 暂停 - 暂时不接收新请求
  | 'error'           // 错误状态
  | 'shutting_down';  // 关闭中

/**
 * Agent Session Status with ProjectReActAgent Lifecycle
 * 完整的项目 Agent 会话状态
 */
export interface AgentSessionStatus {
  // Basic status (existing)
  is_initialized: boolean;
  is_active: boolean;
  total_chats: number;
  active_chats: number;
  tool_count: number;
  cached_since?: string;
  workflow_id?: string;
  
  // Extended ProjectReActAgent Lifecycle Status
  /** 当前生命周期状态 */
  lifecycle_state?: ProjectAgentLifecycleState;
  /** 是否正在执行 */
  is_executing?: boolean;
  /** 失败聊天数 */
  failed_chats?: number;
  /** 技能数量 */
  skill_count?: number;
  /** 子代理数量 */
  subagent_count?: number;
  /** 创建时间 */
  created_at?: string;
  /** 最后活动时间 */
  last_activity_at?: string;
  /** 运行时间（秒） */
  uptime_seconds?: number;
  /** 最后错误信息 */
  last_error?: string;
  
  // Performance metrics
  /** 平均执行时间（毫秒） */
  avg_execution_time_ms?: number;
}

/**
 * Project Agent Metrics
 * 项目 Agent 详细指标
 */
export interface ProjectAgentMetrics {
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  tool_execution_count: Record<string, number>;
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

/**
 * Get detailed ProjectReActAgent lifecycle status
 * 获取详细的项目 Agent 生命周期状态
 */
export async function getProjectAgentLifecycle(
  projectId: string
): Promise<AgentSessionStatus> {
  const response = await api.get(`/api/v1/agent/projects/${projectId}/lifecycle`);
  return (response as { data: AgentSessionStatus }).data;
}

/**
 * Get project agent metrics
 * 获取项目 Agent 指标
 */
export async function getProjectAgentMetrics(
  projectId: string
): Promise<ProjectAgentMetrics> {
  const response = await api.get(`/api/v1/agent/projects/${projectId}/metrics`);
  return (response as { data: ProjectAgentMetrics }).data;
}

/**
 * Refresh project agent (reload tools, clear caches)
 * 刷新项目 Agent
 */
export async function refreshProjectAgent(
  projectId: string
): Promise<{ status: string; workflow_id: string }> {
  const response = await api.post(`/api/v1/agent/projects/${projectId}/refresh`, {});
  return (response as { data: { status: string; workflow_id: string } }).data;
}

/**
 * Pause project agent
 * 暂停项目 Agent
 */
export async function pauseProjectAgent(
  projectId: string
): Promise<{ status: string }> {
  const response = await api.post(`/api/v1/agent/projects/${projectId}/pause`, {});
  return (response as { data: { status: string } }).data;
}

/**
 * Resume project agent
 * 恢复项目 Agent
 */
export async function resumeProjectAgent(
  projectId: string
): Promise<{ status: string }> {
  const response = await api.post(`/api/v1/agent/projects/${projectId}/resume`, {});
  return (response as { data: { status: string } }).data;
}

/**
 * Stop project agent
 * 停止项目 Agent
 */
export async function stopProjectAgent(
  projectId: string
): Promise<{ status: string }> {
  const response = await api.post(`/api/v1/agent/projects/${projectId}/stop`, {});
  return (response as { data: { status: string } }).data;
}

export const agentStatusService = {
  getWorkflowStatus,
  getAgentSessionStatus,
  getProjectAgentLifecycle,
  getProjectAgentMetrics,
  refreshProjectAgent,
  pauseProjectAgent,
  resumeProjectAgent,
  stopProjectAgent,
};
