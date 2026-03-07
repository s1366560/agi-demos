// ============================================
// Workflow Pattern Types (T074, T085)
// ============================================

/**
 * Pattern step in a workflow pattern
 */
export interface PatternStep {
  step_number: number;
  description: string;
  tool_name: string;
  expected_output_format: string;
  similarity_threshold: number;
  tool_parameters?: Record<string, unknown> | undefined;
}

/**
 * Workflow pattern for learned workflows (FR-019, FR-020)
 *
 * Patterns are tenant-scoped - shared across all projects within
 * a tenant but isolated between tenants.
 */
export interface WorkflowPattern {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  steps: PatternStep[];
  success_rate: number;
  usage_count: number;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown> | undefined;
}

/**
 * Workflow patterns list response
 */
export interface PatternsListResponse {
  patterns: WorkflowPattern[];
  total: number;
  page: number;
  page_size: number;
}

/**
 * Reset patterns response
 */
export interface ResetPatternsResponse {
  deleted_count: number;
  tenant_id: string;
}

// ============================================
// Tool Composition Types (T108, T115)
// ============================================

/**
 * Tool composition execution template (T108)
 *
 * Defines how tools are composed together.
 */
export interface ToolCompositionTemplate {
  type: 'sequential' | 'parallel' | 'conditional';
  aggregation?: 'merge' | 'concatenate' | 'prioritize' | undefined; // For parallel compositions
  condition?: string | undefined; // For conditional compositions
  fallback_alternatives: string[];
}

/**
 * Tool composition (T108)
 *
 * Represents a composition of multiple tools that work together
 * to accomplish complex tasks through intelligent chaining.
 */
export interface ToolComposition {
  id: string;
  name: string;
  description: string;
  tools: string[];
  execution_template: ToolCompositionTemplate;
  success_rate: number;
  success_count: number;
  failure_count: number;
  usage_count: number;
  created_at: string;
  updated_at: string;
}

/**
 * Tool compositions list response (T114)
 */
export interface ToolCompositionsListResponse {
  compositions: ToolComposition[];
  total: number;
}

// ============================================
// Plan Mode Types (Plan Document System)
// ============================================

/**
 * Plan document status
 */
export type PlanDocumentStatus = 'draft' | 'reviewing' | 'approved' | 'archived';

/**
 * Agent mode for plan mode switching
 */
export type AgentMode = 'build' | 'plan' | 'explore';

/**
 * Plan document
 */
export interface PlanDocument {
  id: string;
  conversation_id: string;
  title: string;
  content: string;
  status: PlanDocumentStatus;
  version: number;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/**
 * Plan mode status response
 */
export interface PlanModeStatus {
  is_in_plan_mode: boolean;
  current_mode: AgentMode;
  current_plan_id: string | null;
  plan: PlanDocument | null;
}

/**
 * Enter plan mode request
 */
export interface EnterPlanModeRequest {
  conversation_id: string;
  title: string;
  description?: string | undefined;
}

/**
 * Exit plan mode request
 */
export interface ExitPlanModeRequest {
  conversation_id: string;
  plan_id: string;
  approve?: boolean | undefined;
  summary?: string | undefined;
}

/**
 * Update plan request
 */
export interface UpdatePlanRequest {
  content?: string | undefined;
  title?: string | undefined;
  explored_files?: string[] | undefined;
  critical_files?:
    | Array<{
        path: string;
        type: 'create' | 'modify' | 'delete';
      }>
    | undefined;
  metadata?: Record<string, unknown> | undefined;
}

/**
 * Plan Mode SSE event data types
 */
export interface PlanModeEnterEventData {
  conversation_id: string;
  plan_id: string;
  plan_title: string;
}

export interface PlanModeExitEventData {
  conversation_id: string;
  plan_id: string;
  plan_status: PlanDocumentStatus;
  approved: boolean;
}

export interface PlanCreatedEventData {
  plan_id: string;
  title: string;
  conversation_id: string;
}

export interface PlanUpdatedEventData {
  plan_id: string;
  content: string;
  version: number;
}

// ===========================================================================
// Plan Mode Types
// ===========================================================================

/**
 * Execution plan step status
 */
export type ExecutionStepStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'cancelled';

/**
 * Execution plan status
 */
export type ExecutionPlanStatus =
  | 'draft'
  | 'approved'
  | 'executing'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled';

/**
 * Reflection assessment
 */
export type ReflectionAssessment =
  | 'on_track'
  | 'needs_adjustment'
  | 'off_track'
  | 'complete'
  | 'failed';

/**
 * Adjustment type for plan steps
 */
export type AdjustmentType = 'modify' | 'retry' | 'skip' | 'add_before' | 'add_after' | 'replace';

/**
 * Single execution step in a plan
 */
export interface ExecutionStep {
  step_id: string;
  description: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
  dependencies: string[];
  status: ExecutionStepStatus;
  result?: string | undefined;
  error?: string | undefined;
  started_at?: string | undefined;
  completed_at?: string | undefined;
}

/**
 * Step adjustment for reflection
 */
export interface StepAdjustment {
  step_id: string;
  adjustment_type: AdjustmentType;
  reason: string;
  new_tool_input?: Record<string, unknown> | undefined;
  new_tool_name?: string | undefined;
  new_step?: ExecutionStep | undefined;
}

/**
 * Reflection result from plan execution
 */
export interface ReflectionResult {
  assessment: ReflectionAssessment;
  reasoning: string;
  adjustments: StepAdjustment[];
  suggested_next_steps?: string[] | undefined;
  confidence?: number | undefined;
  final_summary?: string | undefined;
  error_type?: string | undefined;
  reflection_metadata: Record<string, unknown>;
  is_terminal: boolean;
}

/**
 * Plan snapshot for rollback functionality
 */
export interface StepState {
  step_id: string;
  status: string;
  result?: string | undefined;
  error?: string | undefined;
  started_at?: string | undefined;
  completed_at?: string | undefined;
  tool_input: Record<string, unknown>;
}

/**
 * Plan snapshot for rollback
 */
export interface PlanSnapshot {
  id: string;
  plan_id: string;
  name: string;
  description?: string | undefined;
  step_states: Record<string, StepState>;
  auto_created: boolean;
  snapshot_type: string;
  created_at: string;
}

/**
 * Execution plan for Plan Mode
 */
export interface ExecutionPlan {
  id: string;
  conversation_id: string;
  user_query: string;
  steps: ExecutionStep[];
  status: ExecutionPlanStatus;
  reflection_enabled: boolean;
  max_reflection_cycles: number;
  completed_steps: string[];
  failed_steps: string[];
  snapshot?: PlanSnapshot | undefined;
  started_at?: string | undefined;
  completed_at?: string | undefined;
  error?: string | undefined;
  progress_percentage: number;
  is_complete: boolean;
}
