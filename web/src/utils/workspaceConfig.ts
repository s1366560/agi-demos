import type {
  Workspace,
  WorkspaceCollaborationMode,
  WorkspaceCreateRequest,
  WorkspaceType,
  WorkspaceUseCase,
} from '@/types/workspace';

export const DEFAULT_WORKSPACE_USE_CASE: WorkspaceUseCase = 'general';
export const DEFAULT_COLLABORATION_MODE: WorkspaceCollaborationMode = 'multi_agent_shared';
export const MIN_WORKSPACE_DESCRIPTION_LENGTH = 12;

export function workspaceTypeForUseCase(useCase: WorkspaceUseCase): WorkspaceType {
  if (useCase === 'programming') return 'software_development';
  if (useCase === 'research') return 'research';
  if (useCase === 'operations') return 'operations';
  return 'general';
}

export function isWorkspaceUseCase(value: unknown): value is WorkspaceUseCase {
  return (
    value === 'programming' ||
    value === 'conversation' ||
    value === 'research' ||
    value === 'operations' ||
    value === 'general'
  );
}

export function isWorkspaceCollaborationMode(value: unknown): value is WorkspaceCollaborationMode {
  return (
    value === 'single_agent' ||
    value === 'multi_agent_shared' ||
    value === 'multi_agent_isolated' ||
    value === 'autonomous'
  );
}

export function getWorkspaceUseCase(workspace: Workspace): WorkspaceUseCase {
  const direct = workspace.metadata?.workspace_use_case;
  if (isWorkspaceUseCase(direct)) {
    return direct;
  }
  const type = workspace.metadata?.workspace_type;
  if (type === 'software_development') {
    return 'programming';
  }
  if (type === 'research' || type === 'operations' || type === 'general') {
    return type;
  }
  return DEFAULT_WORKSPACE_USE_CASE;
}

export function getWorkspaceCollaborationMode(workspace: Workspace): WorkspaceCollaborationMode {
  const direct = workspace.metadata?.collaboration_mode;
  if (isWorkspaceCollaborationMode(direct)) {
    return direct;
  }
  const legacy = workspace.metadata?.agent_conversation_mode;
  if (isWorkspaceCollaborationMode(legacy)) {
    return legacy;
  }
  return DEFAULT_COLLABORATION_MODE;
}

export function normaliseSandboxCodeRoot(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (trimmed.startsWith('/workspace/')) return trimmed.replace(/\/+$/, '');
  if (!trimmed.startsWith('/')) return `/workspace/${trimmed.replace(/^\/+/, '')}`;
  return trimmed.replace(/\/+$/, '');
}

export function isIsolatedSandboxCodeRoot(value: string): boolean {
  const normalised = normaliseSandboxCodeRoot(value);
  return normalised.startsWith('/workspace/') && normalised.length > '/workspace/'.length;
}

export function getSandboxCodeRoot(workspace: Workspace): string | null {
  const direct = workspace.metadata?.sandbox_code_root;
  if (typeof direct === 'string' && direct.trim()) return direct.trim();
  const codeContext = workspace.metadata?.code_context;
  if (
    codeContext &&
    typeof codeContext === 'object' &&
    'sandbox_code_root' in codeContext &&
    typeof codeContext.sandbox_code_root === 'string' &&
    codeContext.sandbox_code_root.trim()
  ) {
    return codeContext.sandbox_code_root.trim();
  }
  return null;
}

export function buildWorkspaceCreateRequest({
  name,
  description,
  useCase,
  collaborationMode,
  sandboxCodeRoot,
}: {
  name: string;
  description: string;
  useCase: WorkspaceUseCase;
  collaborationMode: WorkspaceCollaborationMode;
  sandboxCodeRoot: string;
}): WorkspaceCreateRequest {
  const workspaceType = workspaceTypeForUseCase(useCase);
  const normalizedCodeRoot = normaliseSandboxCodeRoot(sandboxCodeRoot);

  return {
    name: name.trim(),
    description: description.trim(),
    use_case: useCase,
    collaboration_mode: collaborationMode,
    ...(useCase === 'programming' ? { sandbox_code_root: normalizedCodeRoot } : {}),
    metadata: {
      workspace_use_case: useCase,
      workspace_type: workspaceType,
      collaboration_mode: collaborationMode,
      agent_conversation_mode: collaborationMode,
      autonomy_profile: { workspace_type: workspaceType },
      ...(useCase === 'programming'
        ? {
            sandbox_code_root: normalizedCodeRoot,
            code_context: { sandbox_code_root: normalizedCodeRoot },
          }
        : {}),
    },
  };
}
