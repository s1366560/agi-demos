/**
 * Human-in-the-Loop (HITL) Type Definitions
 *
 * Types for managing human-in-the-loop interactions including:
 * - Clarification requests
 * - Permission requests
 * - Decision requests
 * - Environment variable requests
 */

import type { AgentEventType } from './generated/eventTypes';

// =============================================================================
// Base Types
// =============================================================================

/**
 * Risk level for permission requests
 */
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

/**
 * Status of a HITL request
 */
export type HITLRequestStatus = 'pending' | 'answered' | 'timeout' | 'cancelled';

/**
 * Type discriminator for HITL requests
 */
export type HITLRequestType = 'clarification' | 'permission' | 'decision' | 'env_var';

/**
 * Base interface for all HITL requests
 */
export interface HITLRequestBase {
  /** Unique request identifier */
  requestId: string;

  /** Type of HITL request */
  requestType: HITLRequestType;

  /** Current status */
  status: HITLRequestStatus;

  /** When the request was created */
  createdAt: number;

  /** When the request times out (optional) */
  timeoutAt?: number;

  /** Timeout in seconds (optional) */
  timeoutSeconds?: number;

  /** Conversation this request belongs to */
  conversationId: string;

  /** Additional context */
  context?: string;
}

// =============================================================================
// Clarification Request
// =============================================================================

/**
 * Type of clarification being requested
 */
export type ClarificationType =
  | 'choice' // Select from options
  | 'confirmation' // Yes/No
  | 'text_input' // Free-form text
  | 'multi_select'; // Select multiple options

/**
 * Clarification request - agent needs more information
 */
export interface ClarificationRequest extends HITLRequestBase {
  requestType: 'clarification';

  /** The question being asked */
  question: string;

  /** Type of clarification */
  clarificationType: ClarificationType;

  /** Available options (for choice/multi_select) */
  options?: string[];

  /** Whether custom input is allowed */
  allowCustom?: boolean;

  /** Default value if timeout */
  defaultValue?: string;
}

/**
 * Response to a clarification request
 */
export interface ClarificationResponse {
  requestId: string;
  answer: string | string[]; // string[] for multi_select
}

// =============================================================================
// Permission Request
// =============================================================================

/**
 * Permission request - agent wants to perform a potentially risky action
 */
export interface PermissionRequest extends HITLRequestBase {
  requestType: 'permission';

  /** Name of the tool requesting permission */
  toolName: string;

  /** Action being requested */
  action: string;

  /** Risk level of the action */
  riskLevel: RiskLevel;

  /** Detailed description of what will happen */
  details: Record<string, unknown>;

  /** Human-readable description */
  description?: string;

  /** Whether "remember this choice" is available */
  allowRemember?: boolean;

  /** Default action if timeout */
  defaultAction?: 'allow' | 'deny';
}

/**
 * Response to a permission request
 */
export interface PermissionResponse {
  requestId: string;
  allowed: boolean;
  remember?: boolean; // Remember this choice for this tool
}

// =============================================================================
// Decision Request
// =============================================================================

/**
 * Type of decision being requested
 */
export type DecisionType =
  | 'single_choice' // Select one option
  | 'multi_choice' // Select multiple options
  | 'ranking'; // Rank options in order

/**
 * Decision option with metadata
 */
export interface DecisionOption {
  /** Option identifier */
  id: string;

  /** Display label */
  label: string;

  /** Optional description */
  description?: string;

  /** Whether this is the recommended option */
  recommended?: boolean;

  /** Risk level if applicable */
  riskLevel?: RiskLevel;
}

/**
 * Decision request - agent needs user to make a choice
 */
export interface DecisionRequest extends HITLRequestBase {
  requestType: 'decision';

  /** The question/decision to make */
  question: string;

  /** Type of decision */
  decisionType: DecisionType;

  /** Available options */
  options: DecisionOption[];

  /** Whether custom input is allowed */
  allowCustom?: boolean;

  /** Default option if timeout */
  defaultOption?: string;

  /** Maximum selections (for multi_choice) */
  maxSelections?: number;
}

/**
 * Response to a decision request
 */
export interface DecisionResponse {
  requestId: string;
  decision: string | string[]; // string[] for multi_choice/ranking
}

// =============================================================================
// Environment Variable Request
// =============================================================================

/**
 * Field in an env var request
 */
export interface EnvVarField {
  /** Field name (will become env var name) */
  name: string;

  /** Display label */
  label: string;

  /** Field description */
  description?: string;

  /** Whether this field is required */
  required: boolean;

  /** Whether to mask input (for secrets) */
  secret?: boolean;

  /** Default value */
  defaultValue?: string;

  /** Validation pattern */
  pattern?: string;
}

/**
 * Environment variable request - tool needs credentials/config
 */
export interface EnvVarRequest extends HITLRequestBase {
  requestType: 'env_var';

  /** Tool requesting the env vars */
  toolName: string;

  /** Fields to collect */
  fields: EnvVarField[];

  /** Human-readable message */
  message: string;

  /** Whether to save for future sessions */
  allowSave?: boolean;
}

/**
 * Response to an env var request
 */
export interface EnvVarResponse {
  requestId: string;
  values: Record<string, string>;
  save?: boolean; // Save for future sessions
}

// =============================================================================
// Union Types
// =============================================================================

/**
 * Union of all HITL request types
 */
export type HITLRequest =
  | ClarificationRequest
  | PermissionRequest
  | DecisionRequest
  | EnvVarRequest;

/**
 * Union of all HITL response types
 */
export type HITLResponse =
  | ClarificationResponse
  | PermissionResponse
  | DecisionResponse
  | EnvVarResponse;

// =============================================================================
// Event Type Mapping
// =============================================================================

/**
 * Map HITL event types to request types
 */
export const HITL_EVENT_TYPE_MAP: Record<string, HITLRequestType> = {
  clarification_asked: 'clarification',
  permission_asked: 'permission',
  decision_asked: 'decision',
  env_var_requested: 'env_var',
} as const;

/**
 * Map HITL request types to answered event types
 */
export const HITL_ANSWERED_EVENT_MAP: Record<HITLRequestType, AgentEventType> = {
  clarification: 'clarification_answered',
  permission: 'permission_replied',
  decision: 'decision_answered',
  env_var: 'env_var_provided',
} as const;

// =============================================================================
// Type Guards
// =============================================================================

export function isClarificationRequest(req: HITLRequest): req is ClarificationRequest {
  return req.requestType === 'clarification';
}

export function isPermissionRequest(req: HITLRequest): req is PermissionRequest {
  return req.requestType === 'permission';
}

export function isDecisionRequest(req: HITLRequest): req is DecisionRequest {
  return req.requestType === 'decision';
}

export function isEnvVarRequest(req: HITLRequest): req is EnvVarRequest {
  return req.requestType === 'env_var';
}

// =============================================================================
// Utility Functions
// =============================================================================

/**
 * Check if a HITL request has timed out
 */
export function isRequestTimedOut(request: HITLRequestBase): boolean {
  if (!request.timeoutAt) return false;
  return Date.now() > request.timeoutAt;
}

/**
 * Get remaining time in seconds for a HITL request
 */
export function getRemainingTime(request: HITLRequestBase): number | null {
  if (!request.timeoutAt) return null;
  const remaining = Math.max(0, request.timeoutAt - Date.now());
  return Math.ceil(remaining / 1000);
}

/**
 * Create a HITL request from event data
 */
export function createHITLRequest(
  eventType: AgentEventType,
  data: Record<string, unknown>,
  conversationId: string
): HITLRequest | null {
  const requestType = HITL_EVENT_TYPE_MAP[eventType];
  if (!requestType) return null;

  const base: HITLRequestBase = {
    requestId: data.request_id as string,
    requestType,
    status: 'pending',
    createdAt: Date.now(),
    conversationId,
    context: data.context as string | undefined,
    timeoutSeconds: data.timeout_seconds as number | undefined,
    timeoutAt: data.timeout_seconds
      ? Date.now() + (data.timeout_seconds as number) * 1000
      : undefined,
  };

  switch (requestType) {
    case 'clarification':
      return {
        ...base,
        requestType: 'clarification',
        question: data.question as string,
        clarificationType: (data.clarification_type as ClarificationType) || 'text_input',
        options: data.options as string[] | undefined,
        allowCustom: data.allow_custom as boolean | undefined,
        defaultValue: data.default_value as string | undefined,
      };

    case 'permission':
      return {
        ...base,
        requestType: 'permission',
        toolName: data.tool_name as string,
        action: data.action as string,
        riskLevel: (data.risk_level as RiskLevel) || 'medium',
        details: (data.details as Record<string, unknown>) || {},
        description: data.description as string | undefined,
        allowRemember: data.allow_remember as boolean | undefined,
        defaultAction: data.default_action as 'allow' | 'deny' | undefined,
      };

    case 'decision':
      return {
        ...base,
        requestType: 'decision',
        question: data.question as string,
        decisionType: (data.decision_type as DecisionType) || 'single_choice',
        options: (data.options as DecisionOption[]) || [],
        allowCustom: data.allow_custom as boolean | undefined,
        defaultOption: data.default_option as string | undefined,
        maxSelections: data.max_selections as number | undefined,
      };

    case 'env_var':
      return {
        ...base,
        requestType: 'env_var',
        toolName: data.tool_name as string,
        fields: (data.fields as EnvVarField[]) || [],
        message: data.message as string,
        allowSave: data.allow_save as boolean | undefined,
      };

    default:
      return null;
  }
}
