import type {
  AgentDefinitionDelegateCapabilityTier,
  AgentDefinitionDelegateConfig,
  AgentDefinitionDmScope,
  AgentDefinitionSessionPolicy,
  AgentDefinitionSpawnPolicy,
  AgentDefinitionToolPolicy,
} from '../../types/multiAgent';

export interface AgentDefinitionPolicyFormValues {
  can_spawn?: boolean | undefined;
  max_spawn_depth?: number | undefined;
  spawn_policy_max_active_runs?: number | undefined;
  spawn_policy_max_children_per_requester?: number | undefined;
  spawn_policy_allowed_subagents?: string[] | undefined;
  tool_policy_allow?: string[] | undefined;
  tool_policy_deny?: string[] | undefined;
  tool_policy_precedence?: 'allow_first' | 'deny_first' | undefined;
  session_policy_dm_scope?: AgentDefinitionDmScope | undefined;
  session_policy_max_messages?: number | undefined;
  session_policy_idle_reset_minutes?: number | undefined;
  session_policy_daily_reset_hour?: number | undefined;
  session_policy_ttl_hours?: number | undefined;
  delegate_config_capability_tier?: AgentDefinitionDelegateCapabilityTier | undefined;
  delegate_config_max_delegation_depth?: number | undefined;
  delegate_config_allowed_tools?: string[] | undefined;
  delegate_config_budget_limit_tokens?: number | undefined;
}

export function normalizeStringList(values: string[] | null | undefined): string[] | undefined {
  if (!values) {
    return undefined;
  }

  const seen = new Set<string>();
  const normalized = values
    .map((value) => value.trim())
    .filter((value) => {
      if (!value || seen.has(value)) {
        return false;
      }
      seen.add(value);
      return true;
    });

  return normalized.length > 0 ? normalized : undefined;
}

export function buildSpawnPolicy(
  values: AgentDefinitionPolicyFormValues,
  force = false
): AgentDefinitionSpawnPolicy | null | undefined {
  const allowedSubagents = normalizeStringList(values.spawn_policy_allowed_subagents);
  const hasPolicyFields =
    values.can_spawn === true ||
    values.spawn_policy_max_active_runs !== undefined ||
    values.spawn_policy_max_children_per_requester !== undefined ||
    allowedSubagents !== undefined;

  if (!force && !hasPolicyFields) {
    return undefined;
  }
  if (force && !hasPolicyFields) {
    return null;
  }

  return {
    max_depth: values.max_spawn_depth ?? 2,
    max_active_runs: values.spawn_policy_max_active_runs ?? 16,
    max_children_per_requester: values.spawn_policy_max_children_per_requester ?? 8,
    allowed_subagents: allowedSubagents ?? null,
  };
}

export function buildToolPolicy(
  values: AgentDefinitionPolicyFormValues,
  force = false
): AgentDefinitionToolPolicy | null | undefined {
  const allow = normalizeStringList(values.tool_policy_allow);
  const deny = normalizeStringList(values.tool_policy_deny);
  const precedence = values.tool_policy_precedence ?? 'deny_first';
  const hasPolicyFields = allow !== undefined || deny !== undefined || precedence !== 'deny_first';

  if (!force && !hasPolicyFields) {
    return undefined;
  }
  if (force && !hasPolicyFields) {
    return null;
  }

  return {
    allow: allow ?? [],
    deny: deny ?? [],
    precedence,
  };
}

export function buildSessionPolicy(
  values: AgentDefinitionPolicyFormValues,
  force = false
): AgentDefinitionSessionPolicy | null | undefined {
  const hasPolicyFields =
    values.session_policy_dm_scope !== undefined ||
    values.session_policy_max_messages !== undefined ||
    values.session_policy_idle_reset_minutes !== undefined ||
    values.session_policy_daily_reset_hour !== undefined ||
    values.session_policy_ttl_hours !== undefined;

  if (!force && !hasPolicyFields) {
    return undefined;
  }
  if (force && !hasPolicyFields) {
    return null;
  }

  const policy: AgentDefinitionSessionPolicy = {};
  if (values.session_policy_dm_scope !== undefined) {
    policy.dm_scope = values.session_policy_dm_scope;
  }
  if (values.session_policy_max_messages !== undefined) {
    policy.max_messages = values.session_policy_max_messages;
  }
  if (values.session_policy_idle_reset_minutes !== undefined) {
    policy.idle_reset_minutes = values.session_policy_idle_reset_minutes;
  }
  if (values.session_policy_daily_reset_hour !== undefined) {
    policy.daily_reset_hour = values.session_policy_daily_reset_hour;
  }
  if (values.session_policy_ttl_hours !== undefined) {
    policy.session_ttl_hours = values.session_policy_ttl_hours;
  }
  return policy;
}

export function buildDelegateConfig(
  values: AgentDefinitionPolicyFormValues,
  force = false
): AgentDefinitionDelegateConfig | null | undefined {
  const allowedTools = normalizeStringList(values.delegate_config_allowed_tools);
  const hasConfigFields =
    values.delegate_config_capability_tier !== undefined ||
    values.delegate_config_max_delegation_depth !== undefined ||
    values.delegate_config_budget_limit_tokens !== undefined ||
    allowedTools !== undefined;

  if (!force && !hasConfigFields) {
    return undefined;
  }
  if (force && !hasConfigFields) {
    return null;
  }

  const config: AgentDefinitionDelegateConfig = {};
  if (values.delegate_config_capability_tier !== undefined) {
    config.capability_tier = values.delegate_config_capability_tier;
  }
  if (values.delegate_config_max_delegation_depth !== undefined) {
    config.max_delegation_depth = values.delegate_config_max_delegation_depth;
  }
  if (allowedTools !== undefined) {
    config.allowed_tools = allowedTools;
  }
  if (values.delegate_config_budget_limit_tokens !== undefined) {
    config.budget_limit_tokens = values.delegate_config_budget_limit_tokens;
  }
  return config;
}
