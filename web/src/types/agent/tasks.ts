import type { PlanStatus } from './core';

/**
 * Agent types for React-mode Agent functionality.
 *
 * This module contains TypeScript types for the ReAct agent,
 * conversations, messages, and agent execution tracking.
 *
 * Multi-Level Thinking Support:
 * - Work-level planning for complex queries
 * - Task-level execution with detailed thinking
 * - SSE events for work_plan, task_start, task_complete
 */

/**
 * HITL request type
 */
export type HITLRequestType = 'clarification' | 'decision' | 'env_var';

/**
 * HITL request status
 */
export type HITLRequestStatus = 'pending' | 'answered' | 'timeout' | 'cancelled';

/**
 * Pending HITL request from backend
 */
export interface PendingHITLRequest {
  id: string;
  request_type: HITLRequestType;
  conversation_id: string;
  message_id?: string | undefined;
  question: string;
  options?: Array<Record<string, unknown>> | undefined;
  context?: Record<string, unknown> | undefined;
  metadata?: Record<string, unknown> | undefined;
  status: HITLRequestStatus;
  created_at: string;
  expires_at: string;
}

/**
 * Response for pending HITL requests query
 */
export interface PendingHITLResponse {
  requests: PendingHITLRequest[];
  total: number;
}

/**
 * Plan step in a work plan
 * @deprecated Use AgentTask instead
 */
export interface PlanStep {
  step_number: number;
  description: string;
  thought_prompt: string;
  required_tools: string[];
  expected_output: string;
  dependencies: number[];
}

/**
 * Work plan for multi-level thinking
 * @deprecated Use AgentTask[] instead
 */
export interface WorkPlan {
  id: string;
  conversation_id: string;
  status: PlanStatus;
  // eslint-disable-next-line @typescript-eslint/no-deprecated
  steps: PlanStep[];
  current_step_index: number;
  workflow_pattern_id?: string | undefined;
  created_at: string;
  updated_at?: string | undefined;
}

// =============================================================================
// Agent Task System (DB-persistent, SSE-streamed)
// =============================================================================

export type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled';

export type TaskPriority = 'high' | 'medium' | 'low';

export interface AgentTask {
  id: string;
  conversation_id: string;
  content: string;
  status: TaskStatus;
  priority: TaskPriority;
  order_index: number;
  created_at: string;
  updated_at: string;
}
