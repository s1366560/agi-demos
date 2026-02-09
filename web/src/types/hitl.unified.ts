/**
 * Unified HITL Types - Generated from Python hitl_types.py
 *
 * This file provides type definitions that match the backend Python types.
 * Single source of truth for HITL type definitions across frontend and backend.
 *
 * @generated from src/domain/model/agent/hitl_types.py
 */

// =============================================================================
// Enums
// =============================================================================

/**
 * Type of HITL interaction
 */
export type HITLType = 'clarification' | 'decision' | 'env_var' | 'permission';

/**
 * Status of an HITL request
 */
export type HITLStatus = 'pending' | 'answered' | 'completed' | 'timeout' | 'cancelled';

/**
 * Type of clarification needed
 */
export type ClarificationType =
  | 'scope'
  | 'approach'
  | 'prerequisite'
  | 'priority'
  | 'confirmation'
  | 'custom';

/**
 * Type of decision needed
 */
export type DecisionType =
  | 'branch'
  | 'method'
  | 'confirmation'
  | 'risk'
  | 'single_choice'
  | 'multi_choice'
  | 'custom';

/**
 * Risk level for decisions and permissions
 */
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

/**
 * Action for permission response
 */
export type PermissionAction = 'allow' | 'deny' | 'allow_always' | 'deny_always';

/**
 * Input type for environment variable fields
 */
export type EnvVarInputType = 'text' | 'password' | 'url' | 'api_key' | 'file_path' | 'textarea';

// =============================================================================
// Option Types
// =============================================================================

/**
 * An option for clarification questions
 */
export interface ClarificationOption {
  id: string;
  label: string;
  description?: string;
  recommended?: boolean;
}

/**
 * An option for decision requests
 */
export interface DecisionOption {
  id: string;
  label: string;
  description?: string;
  recommended?: boolean;
  riskLevel?: RiskLevel;
  estimatedTime?: string;
  estimatedCost?: string;
  risks?: string[];
}

/**
 * A field in an environment variable request
 */
export interface EnvVarField {
  name: string;
  label: string;
  description?: string;
  required: boolean;
  secret: boolean;
  inputType: EnvVarInputType;
  defaultValue?: string;
  placeholder?: string;
  pattern?: string;
}

// =============================================================================
// Request Data Types
// =============================================================================

/**
 * Data for a clarification request
 */
export interface ClarificationRequestData {
  question: string;
  clarificationType: ClarificationType;
  options: ClarificationOption[];
  allowCustom: boolean;
  context: Record<string, unknown>;
  defaultValue?: string;
}

/**
 * Data for a decision request
 */
export interface DecisionRequestData {
  question: string;
  decisionType: DecisionType;
  options: DecisionOption[];
  allowCustom: boolean;
  defaultOption?: string;
  maxSelections?: number;
  context: Record<string, unknown>;
}

/**
 * Data for an environment variable request
 */
export interface EnvVarRequestData {
  toolName: string;
  fields: EnvVarField[];
  message?: string;
  allowSave: boolean;
  context: Record<string, unknown>;
}

/**
 * Data for a permission request
 */
export interface PermissionRequestData {
  toolName: string;
  action: string;
  riskLevel: RiskLevel;
  details: Record<string, unknown>;
  description?: string;
  allowRemember: boolean;
  defaultAction?: PermissionAction;
  context: Record<string, unknown>;
}

// =============================================================================
// Unified HITL Request
// =============================================================================

/**
 * Unified HITL request that can represent any type of interaction.
 * This matches the Python HITLRequest dataclass.
 */
export interface UnifiedHITLRequest {
  requestId: string;
  hitlType: HITLType;
  conversationId: string;
  messageId?: string;

  // Type-specific data (only one will be set)
  clarificationData?: ClarificationRequestData;
  decisionData?: DecisionRequestData;
  envVarData?: EnvVarRequestData;
  permissionData?: PermissionRequestData;

  // Common fields
  status: HITLStatus;
  timeoutSeconds: number;
  createdAt: string; // ISO timestamp
  expiresAt?: string; // ISO timestamp

  // Tenant context
  tenantId?: string;
  projectId?: string;
  userId?: string;

  // Computed property
  question: string;
}

// =============================================================================
// Response Types
// =============================================================================

/**
 * Response data for clarification
 */
export interface ClarificationResponseData {
  answer: string | string[];
}

/**
 * Response data for decision
 */
export interface DecisionResponseData {
  decision: string | string[];
}

/**
 * Response data for environment variables
 */
export interface EnvVarResponseData {
  values: Record<string, string>;
  save: boolean;
}

/**
 * Response data for permission
 */
export interface PermissionResponseData {
  action: PermissionAction;
  remember: boolean;
}

/**
 * Union type for all response data
 */
export type HITLResponseData =
  | ClarificationResponseData
  | DecisionResponseData
  | EnvVarResponseData
  | PermissionResponseData;

// =============================================================================
// API Request/Response Types
// =============================================================================

/**
 * Request body for the unified /hitl/respond endpoint
 */
export interface HITLRespondRequest {
  requestId: string;
  hitlType: HITLType;
  responseData: Record<string, unknown>;
}

/**
 * Request body for the /hitl/cancel endpoint
 */
export interface HITLCancelRequest {
  requestId: string;
  reason?: string;
}

/**
 * Response from HITL endpoints
 */
export interface HITLApiResponse {
  success: boolean;
  message: string;
}

/**
 * Response for pending HITL requests
 */
export interface PendingHITLResponse {
  requests: HITLRequestFromApi[];
  total: number;
}

/**
 * HITL request as returned from API (snake_case)
 */
export interface HITLRequestFromApi {
  id: string;
  conversation_id: string;
  message_id?: string;
  request_type: string;
  question: string;
  options?: unknown[];
  context?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  status: string;
  created_at: string;
  expires_at?: string;
}

// =============================================================================
// Signal Types
// =============================================================================

/**
 * Payload for HITL response signal.
 * This is sent from API to Agent when user responds.
 */
export interface HITLSignalPayload {
  requestId: string;
  hitlType: HITLType;
  responseData: Record<string, unknown>;
  userId?: string;
  timestamp: string;
}

// =============================================================================
// Type Guards
// =============================================================================

export function isClarificationRequest(req: UnifiedHITLRequest): boolean {
  return req.hitlType === 'clarification' && !!req.clarificationData;
}

export function isDecisionRequest(req: UnifiedHITLRequest): boolean {
  return req.hitlType === 'decision' && !!req.decisionData;
}

export function isEnvVarRequest(req: UnifiedHITLRequest): boolean {
  return req.hitlType === 'env_var' && !!req.envVarData;
}

export function isPermissionRequest(req: UnifiedHITLRequest): boolean {
  return req.hitlType === 'permission' && !!req.permissionData;
}

// =============================================================================
// Utility Functions
// =============================================================================

/**
 * Check if request has timed out
 */
export function isRequestTimedOut(request: UnifiedHITLRequest): boolean {
  if (!request.expiresAt) return false;
  return new Date(request.expiresAt).getTime() < Date.now();
}

/**
 * Get remaining time in seconds
 */
export function getRemainingTimeSeconds(request: UnifiedHITLRequest): number | null {
  if (!request.expiresAt) return null;
  const remaining = new Date(request.expiresAt).getTime() - Date.now();
  return Math.max(0, Math.ceil(remaining / 1000));
}

/**
 * Convert API response to UnifiedHITLRequest
 */
export function apiToUnifiedRequest(
  apiRequest: HITLRequestFromApi,
  conversationId: string
): UnifiedHITLRequest {
  const hitlType =
    (apiRequest.metadata?.hitl_type as HITLType) ||
    mapRequestTypeToHitlType(apiRequest.request_type);

  return {
    requestId: apiRequest.id,
    hitlType,
    conversationId: apiRequest.conversation_id || conversationId,
    messageId: apiRequest.message_id,
    status: apiRequest.status as HITLStatus,
    timeoutSeconds: 300,
    createdAt: apiRequest.created_at,
    expiresAt: apiRequest.expires_at,
    question: apiRequest.question,
    // Type-specific data would be parsed from context/metadata
    clarificationData:
      hitlType === 'clarification'
        ? {
            question: apiRequest.question,
            clarificationType: 'custom',
            options: (apiRequest.options as ClarificationOption[]) || [],
            allowCustom: true,
            context: apiRequest.context || {},
          }
        : undefined,
    decisionData:
      hitlType === 'decision'
        ? {
            question: apiRequest.question,
            decisionType: 'single_choice',
            options: (apiRequest.options as DecisionOption[]) || [],
            allowCustom: false,
            context: apiRequest.context || {},
          }
        : undefined,
    envVarData:
      hitlType === 'env_var'
        ? {
            toolName: (apiRequest.metadata?.tool_name as string) || 'unknown',
            fields: (apiRequest.options as EnvVarField[]) || [],
            message: apiRequest.question,
            allowSave: true,
            context: apiRequest.context || {},
          }
        : undefined,
    permissionData:
      hitlType === 'permission'
        ? {
            toolName: (apiRequest.metadata?.tool_name as string) || 'unknown',
            action: apiRequest.question,
            riskLevel: 'medium',
            details: apiRequest.context || {},
            allowRemember: true,
            context: {},
          }
        : undefined,
  };
}

/**
 * Map legacy request_type to HITLType
 */
function mapRequestTypeToHitlType(requestType: string): HITLType {
  const mapping: Record<string, HITLType> = {
    clarification: 'clarification',
    decision: 'decision',
    env_var: 'env_var',
    permission: 'permission',
  };
  return mapping[requestType] || 'clarification';
}

/**
 * Build response data for API submission
 */
export function buildResponseData(
  hitlType: HITLType,
  response: HITLResponseData
): Record<string, unknown> {
  switch (hitlType) {
    case 'clarification':
      return { answer: (response as ClarificationResponseData).answer };
    case 'decision':
      return { decision: (response as DecisionResponseData).decision };
    case 'env_var':
      return {
        values: (response as EnvVarResponseData).values,
        save: (response as EnvVarResponseData).save,
      };
    case 'permission':
      return {
        action: (response as PermissionResponseData).action,
        remember: (response as PermissionResponseData).remember,
      };
    default:
      return response as unknown as Record<string, unknown>;
  }
}

// =============================================================================
// Event Type Mapping
// =============================================================================

/**
 * Map SSE event types to HITL types
 */
export const SSE_EVENT_TO_HITL_TYPE: Record<string, HITLType> = {
  clarification_asked: 'clarification',
  decision_asked: 'decision',
  env_var_requested: 'env_var',
  permission_asked: 'permission',
};

/**
 * Map HITL types to answered event types
 */
export const HITL_TYPE_TO_ANSWERED_EVENT: Record<HITLType, string> = {
  clarification: 'clarification_answered',
  decision: 'decision_answered',
  env_var: 'env_var_provided',
  permission: 'permission_replied',
};
