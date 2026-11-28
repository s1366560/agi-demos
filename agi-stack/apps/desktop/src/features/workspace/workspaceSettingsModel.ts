import type { WorkspaceUpdateInput } from '../../api/client';
import type { WorkspaceSummary } from '../../types';
import {
  WORKSPACE_COLLABORATION_MODES,
  WORKSPACE_USE_CASES,
  isIsolatedSandboxCodeRoot,
  normalizeSandboxCodeRoot,
} from './workspaceCreateModel';
import type {
  WorkspaceCollaborationMode,
  WorkspaceUseCase,
} from './workspaceCreateModel';

export const MAX_WORKSPACE_SETTINGS_NAME_LENGTH = 255;
export const MAX_WORKSPACE_SETTINGS_DESCRIPTION_LENGTH = 1000;

export type WorkspaceSettingsDraft = {
  name: string;
  description: string;
  isArchived: boolean;
  useCase: WorkspaceUseCase;
  collaborationMode: WorkspaceCollaborationMode;
  sandboxCodeRoot: string;
};

export type WorkspaceSettingsValidation = {
  canSubmit: boolean;
  nameReady: boolean;
  descriptionReady: boolean;
  codeRootReady: boolean;
  normalizedCodeRoot: string;
};

export type WorkspaceSettingsScope = {
  tenantId: string;
  projectId: string;
  workspaceId: string;
  epoch: number;
  contextRevision: number;
};

export class WorkspaceSettingsScopeChangedError extends Error {
  readonly code = 'workspace_settings_scope_changed';

  constructor() {
    super('Workspace settings scope changed');
    this.name = 'WorkspaceSettingsScopeChangedError';
  }
}

export function hydrateWorkspaceSettingsDraft(
  workspace: WorkspaceSummary,
): WorkspaceSettingsDraft {
  const metadata = workspace.metadata ?? {};
  return {
    name: workspace.name ?? workspace.title ?? '',
    description: workspace.description ?? '',
    isArchived: workspace.is_archived ?? false,
    useCase: readWorkspaceUseCase(metadata),
    collaborationMode: readWorkspaceCollaborationMode(metadata),
    sandboxCodeRoot: readSandboxCodeRoot(metadata),
  };
}

export function workspaceSettingsProjectionSignature(
  workspace: WorkspaceSummary,
): string {
  return `${workspace.id}:${workspace.updated_at ?? ''}`;
}

export function validateWorkspaceSettingsDraft(
  draft: WorkspaceSettingsDraft,
): WorkspaceSettingsValidation {
  const nameLength = draft.name.trim().length;
  const descriptionLength = draft.description.trim().length;
  const normalizedCodeRoot = normalizeSandboxCodeRoot(draft.sandboxCodeRoot);
  const nameReady =
    nameLength > 0 && nameLength <= MAX_WORKSPACE_SETTINGS_NAME_LENGTH;
  const descriptionReady =
    descriptionLength <= MAX_WORKSPACE_SETTINGS_DESCRIPTION_LENGTH;
  const codeRootReady =
    (!normalizedCodeRoot && draft.useCase !== 'programming') ||
    isIsolatedSandboxCodeRoot(normalizedCodeRoot);
  const useCaseReady = WORKSPACE_USE_CASES.includes(draft.useCase);
  const collaborationModeReady = WORKSPACE_COLLABORATION_MODES.includes(
    draft.collaborationMode,
  );
  return {
    canSubmit:
      nameReady &&
      descriptionReady &&
      codeRootReady &&
      useCaseReady &&
      collaborationModeReady,
    nameReady,
    descriptionReady,
    codeRootReady,
    normalizedCodeRoot,
  };
}

export function workspaceSettingsDraftIsDirty(
  draft: WorkspaceSettingsDraft,
  baseline: WorkspaceSettingsDraft,
): boolean {
  return (
    draft.name.trim() !== baseline.name.trim() ||
    draft.description.trim() !== baseline.description.trim() ||
    draft.isArchived !== baseline.isArchived ||
    draft.useCase !== baseline.useCase ||
    draft.collaborationMode !== baseline.collaborationMode ||
    normalizeSandboxCodeRoot(draft.sandboxCodeRoot) !==
      normalizeSandboxCodeRoot(baseline.sandboxCodeRoot)
  );
}

export function buildWorkspaceUpdateInput(
  workspace: WorkspaceSummary,
  draft: WorkspaceSettingsDraft,
): WorkspaceUpdateInput | null {
  const validation = validateWorkspaceSettingsDraft(draft);
  if (!validation.canSubmit) return null;
  const currentMetadata = workspace.metadata ?? {};
  const metadata: Record<string, unknown> = { ...currentMetadata };
  const workspaceType = workspaceTypeForUseCase(draft.useCase);
  const existingProfile = isRecord(metadata.autonomy_profile)
    ? metadata.autonomy_profile
    : {};

  metadata.workspace_use_case = draft.useCase;
  metadata.workspace_type = workspaceType;
  metadata.collaboration_mode = draft.collaborationMode;
  metadata.agent_conversation_mode = draft.collaborationMode;
  metadata.autonomy_profile = {
    ...existingProfile,
    workspace_type: workspaceType,
  };

  if (validation.normalizedCodeRoot) {
    metadata.sandbox_code_root = validation.normalizedCodeRoot;
    metadata.code_context = {
      ...(isRecord(metadata.code_context) ? metadata.code_context : {}),
      sandbox_code_root: validation.normalizedCodeRoot,
    };
  } else {
    delete metadata.sandbox_code_root;
    if (isRecord(metadata.code_context)) {
      const codeContext = { ...metadata.code_context };
      delete codeContext.sandbox_code_root;
      metadata.code_context = codeContext;
    }
  }

  return {
    name: draft.name.trim(),
    description: draft.description.trim(),
    isArchived: draft.isArchived,
    metadata,
  };
}

export function workspaceSettingsScopeIsCurrent(
  submitted: WorkspaceSettingsScope,
  current: WorkspaceSettingsScope,
): boolean {
  return (
    submitted.tenantId === current.tenantId &&
    submitted.projectId === current.projectId &&
    submitted.workspaceId === current.workspaceId &&
    submitted.epoch === current.epoch &&
    submitted.contextRevision === current.contextRevision
  );
}

export function replaceWorkspaceInList(
  workspaces: WorkspaceSummary[],
  updated: WorkspaceSummary,
): WorkspaceSummary[] {
  let replaced = false;
  const next = workspaces.map((workspace) => {
    if (workspace.id !== updated.id) return workspace;
    replaced = true;
    return updated;
  });
  return replaced ? next : workspaces;
}

export function replaceWorkspaceInProjectCatalog(
  catalog: Record<string, WorkspaceSummary[]>,
  updated: WorkspaceSummary,
): Record<string, WorkspaceSummary[]> {
  const projectId = updated.project_id?.trim();
  if (!projectId) return catalog;
  const current = catalog[projectId];
  if (!current) return catalog;
  const next = replaceWorkspaceInList(current, updated);
  return next === current ? catalog : { ...catalog, [projectId]: next };
}

function readWorkspaceUseCase(
  metadata: Record<string, unknown>,
): WorkspaceUseCase {
  if (isWorkspaceUseCase(metadata.workspace_use_case)) {
    return metadata.workspace_use_case;
  }
  if (metadata.workspace_type === 'software_development') return 'programming';
  if (
    metadata.workspace_type === 'research' ||
    metadata.workspace_type === 'operations' ||
    metadata.workspace_type === 'general'
  ) {
    return metadata.workspace_type;
  }
  return 'general';
}

function readWorkspaceCollaborationMode(
  metadata: Record<string, unknown>,
): WorkspaceCollaborationMode {
  if (isWorkspaceCollaborationMode(metadata.collaboration_mode)) {
    return metadata.collaboration_mode;
  }
  if (isWorkspaceCollaborationMode(metadata.agent_conversation_mode)) {
    return metadata.agent_conversation_mode;
  }
  return 'multi_agent_shared';
}

function readSandboxCodeRoot(metadata: Record<string, unknown>): string {
  if (typeof metadata.sandbox_code_root === 'string') {
    return metadata.sandbox_code_root.trim();
  }
  if (
    isRecord(metadata.code_context) &&
    typeof metadata.code_context.sandbox_code_root === 'string'
  ) {
    return metadata.code_context.sandbox_code_root.trim();
  }
  return '';
}

function workspaceTypeForUseCase(
  useCase: WorkspaceUseCase,
): 'general' | 'software_development' | 'research' | 'operations' {
  if (useCase === 'programming') return 'software_development';
  if (useCase === 'research' || useCase === 'operations') return useCase;
  return 'general';
}

function isWorkspaceUseCase(value: unknown): value is WorkspaceUseCase {
  return WORKSPACE_USE_CASES.some((candidate) => candidate === value);
}

function isWorkspaceCollaborationMode(
  value: unknown,
): value is WorkspaceCollaborationMode {
  return WORKSPACE_COLLABORATION_MODES.some((candidate) => candidate === value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
