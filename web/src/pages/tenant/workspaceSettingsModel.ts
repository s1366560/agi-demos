import {
  getSandboxCodeRoot,
  getWorkspaceCollaborationMode,
  getWorkspaceUseCase,
  normaliseSandboxCodeRoot,
  workspaceTypeForUseCase,
} from '@/utils/workspaceConfig';

import type {
  Workspace,
  WorkspaceCollaborationMode,
  WorkspaceMemberRole,
  WorkspaceMetadata,
  WorkspaceUseCase,
  WorkspaceVerificationGrade,
} from '@/types/workspace';

export const ROLE_OPTIONS: Array<{ value: WorkspaceMemberRole; labelKey: string }> = [
  { value: 'owner', labelKey: 'workspaceSettings.members.owner' },
  { value: 'editor', labelKey: 'workspaceSettings.members.editor' },
  { value: 'viewer', labelKey: 'workspaceSettings.members.viewer' },
];

export const USE_CASE_OPTIONS: Array<{
  value: WorkspaceUseCase;
  labelKey: string;
  descriptionKey: string;
}> = [
  {
    value: 'general',
    labelKey: 'tenant.workspaceList.typeGeneral',
    descriptionKey: 'tenant.workspaceList.typeGeneralDescription',
  },
  {
    value: 'programming',
    labelKey: 'tenant.workspaceList.typeProgramming',
    descriptionKey: 'tenant.workspaceList.typeProgrammingDescription',
  },
  {
    value: 'conversation',
    labelKey: 'tenant.workspaceList.typeConversation',
    descriptionKey: 'tenant.workspaceList.typeConversationDescription',
  },
  {
    value: 'research',
    labelKey: 'tenant.workspaceList.typeResearch',
    descriptionKey: 'tenant.workspaceList.typeResearchDescription',
  },
  {
    value: 'operations',
    labelKey: 'tenant.workspaceList.typeOperations',
    descriptionKey: 'tenant.workspaceList.typeOperationsDescription',
  },
];

export const COLLABORATION_MODE_OPTIONS: Array<{
  value: WorkspaceCollaborationMode;
  labelKey: string;
  descriptionKey: string;
}> = [
  {
    value: 'single_agent',
    labelKey: 'tenant.workspaceList.modeSingle',
    descriptionKey: 'tenant.workspaceList.modeSingleDescription',
  },
  {
    value: 'multi_agent_shared',
    labelKey: 'tenant.workspaceList.modeShared',
    descriptionKey: 'tenant.workspaceList.modeSharedDescription',
  },
  {
    value: 'multi_agent_isolated',
    labelKey: 'tenant.workspaceList.modeIsolated',
    descriptionKey: 'tenant.workspaceList.modeIsolatedDescription',
  },
  {
    value: 'autonomous',
    labelKey: 'tenant.workspaceList.modeAutonomous',
    descriptionKey: 'tenant.workspaceList.modeAutonomousDescription',
  },
];

export const VERIFICATION_GRADE_OPTIONS: WorkspaceVerificationGrade[] = ['pass', 'warn', 'fail'];

export interface SettingsDraft {
  name: string;
  description: string;
  isArchived: boolean;
  workspaceUseCase: WorkspaceUseCase;
  collaborationMode: WorkspaceCollaborationMode;
  sandboxCodeRoot: string;
  allowInternalTaskArtifacts: boolean;
  requiresExternalArtifact: boolean;
  minimumVerificationGrade: WorkspaceVerificationGrade;
  requiredArtifactPrefixes: string;
  deliveryProvider: string;
  deliveryTimeoutSeconds: number;
  deliveryAutoDeploy: boolean;
  deliveryPreviewPort: number;
  deliveryHealthUrl: string;
  deliveryHealthCommand: string;
  deliveryInstallCommand: string;
  deliveryLintCommand: string;
  deliveryTestCommand: string;
  deliveryBuildCommand: string;
  deliveryDeployCommand: string;
  rawMetadata: string;
}

export function syncDraftFromWorkspace(workspace: Workspace): SettingsDraft {
  const metadata = workspace.metadata ?? {};
  const profile = metadata.autonomy_profile ?? {};
  const policy = profile.completion_policy ?? {};
  const workspaceUseCase = getWorkspaceUseCase(workspace);
  const sandboxCodeRoot = getSandboxCodeRoot(workspace) ?? '';
  const delivery = metadata.delivery_cicd ?? {};

  return {
    name: workspace.name,
    description: workspace.description ?? '',
    isArchived: workspace.is_archived ?? false,
    workspaceUseCase,
    collaborationMode: getWorkspaceCollaborationMode(workspace),
    sandboxCodeRoot,
    allowInternalTaskArtifacts: policy.allow_internal_task_artifacts ?? false,
    requiresExternalArtifact: policy.requires_external_artifact ?? false,
    minimumVerificationGrade: policy.minimum_verification_grade ?? 'warn',
    requiredArtifactPrefixes: formatPrefixDraft(policy.required_artifact_prefixes),
    deliveryProvider: asString(delivery.provider) || 'sandbox_native',
    deliveryTimeoutSeconds: asNumber(delivery.timeout_seconds, 600),
    deliveryAutoDeploy: delivery.auto_deploy ?? true,
    deliveryPreviewPort: asNumber(delivery.preview_port, 3000),
    deliveryHealthUrl: asString(delivery.health_url),
    deliveryHealthCommand: asString(delivery.health_command),
    deliveryInstallCommand: asString(delivery.install_command),
    deliveryLintCommand: asString(delivery.lint_command),
    deliveryTestCommand: asString(delivery.test_command),
    deliveryBuildCommand: asString(delivery.build_command),
    deliveryDeployCommand: asString(delivery.deploy_command),
    rawMetadata: prettyJson(metadata),
  };
}

export function buildWorkspaceMetadataDraft(draft: SettingsDraft): {
  metadata: WorkspaceMetadata;
  error: string | null;
} {
  const parsed = parseMetadataDraft(draft.rawMetadata);
  if (parsed.error) {
    return parsed;
  }

  const metadata: WorkspaceMetadata = { ...parsed.metadata };
  const workspaceType = workspaceTypeForUseCase(draft.workspaceUseCase);
  const normalizedCodeRoot = normaliseSandboxCodeRoot(draft.sandboxCodeRoot);
  const existingProfile =
    metadata.autonomy_profile && typeof metadata.autonomy_profile === 'object'
      ? metadata.autonomy_profile
      : {};
  const existingPolicy =
    existingProfile.completion_policy && typeof existingProfile.completion_policy === 'object'
      ? existingProfile.completion_policy
      : {};

  metadata.workspace_use_case = draft.workspaceUseCase;
  metadata.workspace_type = workspaceType;
  metadata.collaboration_mode = draft.collaborationMode;
  metadata.agent_conversation_mode = draft.collaborationMode;
  metadata.autonomy_profile = {
    ...existingProfile,
    workspace_type: workspaceType,
    completion_policy: {
      ...existingPolicy,
      allow_internal_task_artifacts: draft.allowInternalTaskArtifacts,
      requires_external_artifact: draft.requiresExternalArtifact,
      minimum_verification_grade: draft.minimumVerificationGrade,
      required_artifact_prefixes: parsePrefixDraft(draft.requiredArtifactPrefixes),
    },
  };

  if (normalizedCodeRoot) {
    metadata.sandbox_code_root = normalizedCodeRoot;
    metadata.code_context = {
      ...(metadata.code_context ?? {}),
      sandbox_code_root: normalizedCodeRoot,
    };
  } else {
    delete metadata.sandbox_code_root;
    if (metadata.code_context) {
      const nextCodeContext = { ...metadata.code_context };
      delete nextCodeContext.sandbox_code_root;
      metadata.code_context = nextCodeContext;
    }
  }
  metadata.delivery_cicd = {
    ...(metadata.delivery_cicd ?? {}),
    provider: draft.deliveryProvider || 'sandbox_native',
    code_root: normalizedCodeRoot || undefined,
    timeout_seconds: Math.max(1, draft.deliveryTimeoutSeconds || 600),
    auto_deploy: draft.deliveryAutoDeploy,
    preview_port: Math.max(1, draft.deliveryPreviewPort || 3000),
    health_url: draft.deliveryHealthUrl.trim() || undefined,
    health_command: draft.deliveryHealthCommand.trim() || undefined,
    install_command: draft.deliveryInstallCommand.trim() || undefined,
    lint_command: draft.deliveryLintCommand.trim() || undefined,
    test_command: draft.deliveryTestCommand.trim() || undefined,
    build_command: draft.deliveryBuildCommand.trim() || undefined,
    deploy_command: draft.deliveryDeployCommand.trim() || undefined,
  };

  return { metadata, error: null };
}

export function getOptionLabel<TValue extends string>(
  value: TValue,
  options: Array<{ value: TValue; labelKey: string }>,
  t: (key: string) => string
): string {
  const option = options.find((item) => item.value === value);
  return option ? t(option.labelKey) : value;
}

function prettyJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseMetadataDraft(value: string): { metadata: WorkspaceMetadata; error: string | null } {
  try {
    const parsed: unknown = value.trim() ? JSON.parse(value) : {};
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { metadata: {}, error: 'metadata_object_required' };
    }
    return { metadata: parsed as WorkspaceMetadata, error: null };
  } catch {
    return { metadata: {}, error: 'metadata_invalid_json' };
  }
}

function parsePrefixDraft(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatPrefixDraft(value: unknown): string {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string').join(', ')
    : '';
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asNumber(value: unknown, fallback: number): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }
  return fallback;
}
