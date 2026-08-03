export type TenantAgentDashboardAuthority = 'cloud' | 'local';
export type TenantAgentDashboardAvailability =
  | 'available'
  | 'degraded'
  | 'unavailable'
  | 'not_applicable';

export type TenantAgentDashboardAction =
  | 'view-config'
  | 'update-config'
  | 'view-hook-catalog'
  | 'list-runs'
  | 'filter-runs'
  | 'inspect-run'
  | 'inspect-trace'
  | 'refresh'
  | 'retry';

export type TenantAgentDashboardScope = Readonly<{
  authority: TenantAgentDashboardAuthority;
  tenantId: string;
}>;

export type TenantRuntimeHook = Readonly<{
  hookName: string;
  pluginName: string;
  hookFamily: string | null;
  executorKind: string;
  sourceRef: string | null;
  entrypoint: string | null;
  enabled: boolean;
  priority: number | null;
  settings: Readonly<Record<string, unknown>>;
}>;

export type TenantRuntimeHookCatalogEntry = Readonly<{
  key: string;
  hookName: string;
  pluginName: string;
  hookFamily: string | null;
  displayName: string;
  description: string;
  defaultPriority: number | null;
  defaultEnabled: boolean;
  defaultExecutorKind: string;
  defaultSourceRef: string | null;
  defaultEntrypoint: string | null;
  defaultSettings: Readonly<Record<string, unknown>>;
  settingsSchema: Readonly<Record<string, unknown>>;
}>;

export type TenantAgentEditableConfig = Readonly<{
  llmModel: string;
  llmTemperature: number;
  patternLearningEnabled: boolean;
  multiLevelThinkingEnabled: boolean;
  maxWorkPlanSteps: number;
  toolTimeoutSeconds: number;
  enabledTools: readonly string[];
  disabledTools: readonly string[];
  runtimeHooks: readonly TenantRuntimeHook[];
}>;

export type TenantAgentConfig = TenantAgentEditableConfig &
  Readonly<{
    id: string;
    tenantId: string;
    configType: string;
    runtimeHookSettingsRedacted: boolean;
    multiAgentEnabled: boolean;
    authorityRevision: number;
    createdAt: string;
    updatedAt: string;
  }>;

export type TenantAgentRun = Readonly<{
  runId: string;
  conversationId: string;
  subagentName: string;
  task: string;
  status: string;
  createdAt: string;
  startedAt: string | null;
  endedAt: string | null;
  summary: string | null;
  error: string | null;
  executionTimeMs: number | null;
  tokensUsed: number | null;
  traceId: string | null;
  parentSpanId: string | null;
}>;

export type TenantAgentTrace = Readonly<{
  traceId: string | null;
  conversationId: string;
  runs: readonly TenantAgentRun[];
  total: number;
}>;

export type TenantAgentDashboardSnapshot = Readonly<{
  scope: TenantAgentDashboardScope;
  authority: TenantAgentDashboardAuthority;
  availability: TenantAgentDashboardAvailability;
  reasonCode: string | null;
  serviceVersion: string;
  contractVersion: string;
  allowedActions: readonly TenantAgentDashboardAction[];
  authorityRevision: number | null;
  canModify: boolean;
  config: TenantAgentConfig | null;
  hookCatalog: readonly TenantRuntimeHookCatalogEntry[];
  runs: readonly TenantAgentRun[];
  activeRunCount: number;
}>;

export type TenantAgentDashboardClient = Readonly<{
  load: (
    scope: TenantAgentDashboardScope,
    signal?: AbortSignal,
  ) => Promise<TenantAgentDashboardSnapshot>;
  updateConfig: (
    scope: TenantAgentDashboardScope,
    input: TenantAgentEditableConfig,
    expectedRevision: number,
    signal?: AbortSignal,
  ) => Promise<TenantAgentConfig>;
  inspectTrace: (
    scope: TenantAgentDashboardScope,
    conversationId: string,
    traceId: string,
    signal?: AbortSignal,
  ) => Promise<TenantAgentTrace>;
}>;
