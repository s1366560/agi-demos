import type { WorkspaceCreateInput } from '../../api/client';
import type { WorkspaceSummary } from '../../types';

export const MIN_WORKSPACE_DESCRIPTION_LENGTH = 12;
export const MAX_WORKSPACE_NAME_LENGTH = 120;
export const MAX_WORKSPACE_DESCRIPTION_LENGTH = 600;

export const WORKSPACE_USE_CASES = [
  'general',
  'programming',
  'conversation',
  'research',
  'operations',
] as const;

export const WORKSPACE_COLLABORATION_MODES = [
  'single_agent',
  'multi_agent_shared',
  'multi_agent_isolated',
  'autonomous',
] as const;

export type WorkspaceUseCase = (typeof WORKSPACE_USE_CASES)[number];
export type WorkspaceCollaborationMode = (typeof WORKSPACE_COLLABORATION_MODES)[number];

export type WorkspaceCreateDraft = {
  name: string;
  description: string;
  useCase: WorkspaceUseCase | null;
  collaborationMode: WorkspaceCollaborationMode | null;
  sandboxCodeRoot: string;
};

export type WorkspaceCreateValidation = {
  canSubmit: boolean;
  nameReady: boolean;
  descriptionReady: boolean;
  useCaseReady: boolean;
  collaborationModeReady: boolean;
  codeRootReady: boolean;
  normalizedCodeRoot: string;
};

export type WorkspaceCreateScope = {
  tenantId: string;
  projectId: string;
  epoch: number;
  contextRevision: number;
};

export class WorkspaceCreateScopeChangedError extends Error {
  readonly code = 'workspace_create_scope_changed';

  constructor() {
    super('Workspace creation scope changed');
    this.name = 'WorkspaceCreateScopeChangedError';
  }
}

export function emptyWorkspaceCreateDraft(): WorkspaceCreateDraft {
  return {
    name: '',
    description: '',
    useCase: null,
    collaborationMode: null,
    sandboxCodeRoot: '',
  };
}

export function normalizeSandboxCodeRoot(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (trimmed.startsWith('/workspace/')) return trimmed.replace(/\/+$/, '');
  if (!trimmed.startsWith('/')) return `/workspace/${trimmed.replace(/\/+$/, '')}`;
  return trimmed.replace(/\/+$/, '');
}

export function isIsolatedSandboxCodeRoot(value: string): boolean {
  const normalized = normalizeSandboxCodeRoot(value);
  return normalized.startsWith('/workspace/') && normalized.length > '/workspace/'.length;
}

export function validateWorkspaceCreateDraft(
  draft: WorkspaceCreateDraft,
): WorkspaceCreateValidation {
  const nameLength = draft.name.trim().length;
  const descriptionLength = draft.description.trim().length;
  const normalizedCodeRoot = normalizeSandboxCodeRoot(draft.sandboxCodeRoot);
  const nameReady = nameLength > 0 && nameLength <= MAX_WORKSPACE_NAME_LENGTH;
  const descriptionReady =
    descriptionLength >= MIN_WORKSPACE_DESCRIPTION_LENGTH &&
    descriptionLength <= MAX_WORKSPACE_DESCRIPTION_LENGTH;
  const useCaseReady =
    draft.useCase !== null && WORKSPACE_USE_CASES.includes(draft.useCase);
  const collaborationModeReady =
    draft.collaborationMode !== null &&
    WORKSPACE_COLLABORATION_MODES.includes(draft.collaborationMode);
  const codeRootReady =
    draft.useCase !== 'programming' || isIsolatedSandboxCodeRoot(normalizedCodeRoot);
  return {
    canSubmit:
      nameReady &&
      descriptionReady &&
      useCaseReady &&
      collaborationModeReady &&
      codeRootReady,
    nameReady,
    descriptionReady,
    useCaseReady,
    collaborationModeReady,
    codeRootReady,
    normalizedCodeRoot,
  };
}

export function workspaceCreateDraftIsDirty(draft: WorkspaceCreateDraft): boolean {
  return (
    draft.name.trim().length > 0 ||
    draft.description.trim().length > 0 ||
    draft.useCase !== null ||
    draft.collaborationMode !== null ||
    draft.sandboxCodeRoot.trim().length > 0
  );
}

export function buildWorkspaceCreateInput(
  draft: WorkspaceCreateDraft,
): WorkspaceCreateInput | null {
  const validation = validateWorkspaceCreateDraft(draft);
  if (!validation.canSubmit || !draft.useCase || !draft.collaborationMode) return null;
  const workspaceType = workspaceTypeForUseCase(draft.useCase);
  const programmingMetadata =
    draft.useCase === 'programming'
      ? {
          sandbox_code_root: validation.normalizedCodeRoot,
          code_context: { sandbox_code_root: validation.normalizedCodeRoot },
        }
      : {};
  return {
    name: draft.name.trim(),
    description: draft.description.trim(),
    useCase: draft.useCase,
    collaborationMode: draft.collaborationMode,
    ...(draft.useCase === 'programming'
      ? { sandboxCodeRoot: validation.normalizedCodeRoot }
      : {}),
    metadata: {
      source: 'desktop',
      workspace_use_case: draft.useCase,
      workspace_type: workspaceType,
      collaboration_mode: draft.collaborationMode,
      agent_conversation_mode: draft.collaborationMode,
      autonomy_profile: { workspace_type: workspaceType },
      ...programmingMetadata,
    },
  };
}

export function workspaceCreateRadioNextValue<T extends string>(
  options: readonly T[],
  current: T | null,
  key: string,
): T | null {
  if (options.length === 0) return null;
  const currentIndex = current === null ? -1 : options.indexOf(current);
  let nextIndex: number;
  if (key === 'ArrowRight' || key === 'ArrowDown') {
    nextIndex = currentIndex < 0 || currentIndex === options.length - 1 ? 0 : currentIndex + 1;
  } else if (key === 'ArrowLeft' || key === 'ArrowUp') {
    nextIndex = currentIndex <= 0 ? options.length - 1 : currentIndex - 1;
  } else if (key === 'Home') {
    nextIndex = 0;
  } else if (key === 'End') {
    nextIndex = options.length - 1;
  } else {
    return null;
  }
  return options[nextIndex] ?? null;
}

export function workspaceCreateScopeIsCurrent(
  submitted: WorkspaceCreateScope,
  current: WorkspaceCreateScope,
): boolean {
  return (
    submitted.tenantId === current.tenantId &&
    submitted.projectId === current.projectId &&
    submitted.epoch === current.epoch &&
    submitted.contextRevision === current.contextRevision
  );
}

export function mergeWorkspaceIntoProjectCatalog(
  catalog: Record<string, WorkspaceSummary[]>,
  workspace: WorkspaceSummary,
): Record<string, WorkspaceSummary[]> {
  const projectId = workspace.project_id?.trim();
  if (!projectId) return catalog;
  const current = catalog[projectId] ?? [];
  return {
    ...catalog,
    [projectId]: [workspace, ...current.filter((candidate) => candidate.id !== workspace.id)],
  };
}

function workspaceTypeForUseCase(
  useCase: WorkspaceUseCase,
): 'general' | 'software_development' | 'research' | 'operations' {
  if (useCase === 'programming') return 'software_development';
  if (useCase === 'research' || useCase === 'operations') return useCase;
  return 'general';
}
