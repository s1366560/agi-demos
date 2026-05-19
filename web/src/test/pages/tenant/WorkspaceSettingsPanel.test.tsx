import type { ReactNode } from 'react';

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { WorkspaceSettingsPanel } from '@/pages/tenant/WorkspaceSettings';
import { fireEvent, render, screen, waitFor } from '@/test/utils';
import type { Workspace, WorkspaceMember } from '@/types/workspace';

const mockState = vi.hoisted(() => ({
  workspace: null as Workspace | null,
  members: [] as WorkspaceMember[],
  updateWorkspace: vi.fn(),
  removeWorkspace: vi.fn(),
  addMember: vi.fn(),
  removeMember: vi.fn(),
  updateMemberRole: vi.fn(),
  loadWorkspaceSurface: vi.fn(),
  setCurrentWorkspace: vi.fn(),
}));

const buildWorkspace = (): Workspace => ({
  id: 'ws-1',
  tenant_id: 't-1',
  project_id: 'p-1',
  name: 'Workspace Alpha',
  created_by: 'u-1',
  description: 'Demo workspace',
  is_archived: false,
  metadata: {
    workspace_use_case: 'programming',
    workspace_type: 'software_development',
    collaboration_mode: 'autonomous',
    agent_conversation_mode: 'autonomous',
    sandbox_code_root: '/workspace/my-evo',
    code_context: {
      sandbox_code_root: '/workspace/my-evo',
    },
    autonomy_profile: {
      workspace_type: 'software_development',
      completion_policy: {
        allow_internal_task_artifacts: false,
        requires_external_artifact: true,
        minimum_verification_grade: 'pass',
        required_artifact_prefixes: ['git_diff:', 'test_run:'],
      },
    },
  },
  created_at: '2026-04-01T00:00:00Z',
  updated_at: '2026-04-02T00:00:00Z',
});

vi.mock('@/stores/workspace', () => ({
  useCurrentWorkspace: () => mockState.workspace,
  useWorkspaceMembers: () => mockState.members,
  useWorkspaceActions: () => ({
    loadWorkspaceSurface: mockState.loadWorkspaceSurface,
    setCurrentWorkspace: mockState.setCurrentWorkspace,
  }),
}));

vi.mock('@/services/workspaceService', () => ({
  workspaceService: {
    update: mockState.updateWorkspace,
    remove: mockState.removeWorkspace,
    addMember: mockState.addMember,
    removeMember: mockState.removeMember,
    updateMemberRole: mockState.updateMemberRole,
  },
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyPopconfirm: ({ children }: { children: ReactNode }) => children,
  useLazyMessage: () => ({
    success: vi.fn(),
    error: vi.fn(),
  }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

describe('WorkspaceSettingsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockState.workspace = buildWorkspace();
    mockState.members = [
      {
        id: 'member-1',
        workspace_id: 'ws-1',
        user_id: 'u-1',
        user_email: 'owner@example.com',
        role: 'owner',
        created_at: '2026-04-01T00:00:00Z',
      },
    ];
    mockState.updateWorkspace.mockResolvedValue(buildWorkspace());
  });

  it('marks workspace settings as a hosted non-authoritative projection', () => {
    render(<WorkspaceSettingsPanel tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    const boundaryBadge = screen.getByText('blackboard.settingsSurfaceHint').closest('div');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-boundary', 'hosted');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-authority', 'non-authoritative');
  });

  it('renders workspace operating, code context, autonomy, metadata, and member settings', () => {
    render(<WorkspaceSettingsPanel tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    expect(screen.getByText('workspaceSettings.operatingModel.title')).toBeInTheDocument();
    expect(screen.getByText('workspaceSettings.codeContext.title')).toBeInTheDocument();
    expect(screen.getByText('workspaceSettings.sourceControl.title')).toBeInTheDocument();
    expect(screen.getByText('workspaceSettings.autonomy.title')).toBeInTheDocument();
    expect(screen.getByText('workspaceSettings.metadata.title')).toBeInTheDocument();
    expect(screen.getByDisplayValue('/workspace/my-evo')).toBeInTheDocument();
    expect(screen.getAllByDisplayValue('memstack/workspace-alpha').length).toBeGreaterThanOrEqual(
      1
    );
    expect(screen.getByDisplayValue('https://github.com')).toBeInTheDocument();
    expect(screen.getByDisplayValue('localhost:8080')).toBeInTheDocument();
    expect(screen.getByDisplayValue('memstack-drone-runner')).toBeInTheDocument();
    expect(
      screen
        .getAllByRole('textbox')
        .some((input) => input instanceof HTMLTextAreaElement && input.value.includes('git_diff:'))
    ).toBe(true);
    expect(screen.getByText('owner@example.com')).toBeInTheDocument();
  });

  it('persists structured workspace settings into metadata on save', async () => {
    const updatedWorkspace = {
      ...buildWorkspace(),
      name: 'Workspace Beta',
    };
    mockState.updateWorkspace.mockResolvedValue(updatedWorkspace);

    render(<WorkspaceSettingsPanel tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    fireEvent.change(screen.getByLabelText('workspaceSettings.nameLabel'), {
      target: { value: 'Workspace Beta' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Save/ }));

    await waitFor(() => expect(mockState.updateWorkspace).toHaveBeenCalled());

    expect(mockState.updateWorkspace).toHaveBeenCalledWith('t-1', 'p-1', 'ws-1', {
      name: 'Workspace Beta',
      description: 'Demo workspace',
      is_archived: false,
      metadata: expect.objectContaining({
        workspace_use_case: 'programming',
        workspace_type: 'software_development',
        collaboration_mode: 'autonomous',
        agent_conversation_mode: 'autonomous',
        sandbox_code_root: '/workspace/my-evo',
        code_context: expect.objectContaining({
          sandbox_code_root: '/workspace/my-evo',
        }),
        autonomy_profile: expect.objectContaining({
          workspace_type: 'software_development',
          completion_policy: expect.objectContaining({
            allow_internal_task_artifacts: false,
            requires_external_artifact: true,
            minimum_verification_grade: 'pass',
            required_artifact_prefixes: ['git_diff:', 'test_run:'],
          }),
        }),
      }),
    });
    expect(mockState.setCurrentWorkspace).toHaveBeenCalledWith(updatedWorkspace);
  });

  it('persists Drone delivery settings from structured fields', async () => {
    mockState.workspace = {
      ...buildWorkspace(),
      metadata: {
        ...buildWorkspace().metadata,
        delivery_cicd: {
          provider: 'drone',
          code_root: '/workspace/my-evo',
          agent_managed: false,
          contract_source: 'workspace_defaults',
          contract_confidence: 1,
          timeout_seconds: 600,
          auto_deploy: false,
          drone: {
            repo: 'memstack/old-workspace',
            branch: 'main',
            server_url_env: 'DRONE_SERVER_URL',
            token_env: 'DRONE_TOKEN',
            poll_interval_seconds: 5,
          },
        },
      },
    };

    render(<WorkspaceSettingsPanel tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    fireEvent.change(screen.getByLabelText('workspaceSettings.sourceControl.repo'), {
      target: { value: 'memstack/new-workspace' },
    });
    fireEvent.change(screen.getByLabelText('workspaceSettings.sourceControl.defaultBranch'), {
      target: { value: 'develop' },
    });
    fireEvent.change(screen.getByLabelText('workspaceSettings.delivery.droneRunnerName'), {
      target: { value: 'memstack-custom-runner' },
    });
    fireEvent.change(screen.getByLabelText('workspaceSettings.delivery.droneDeployTarget'), {
      target: { value: 'staging' },
    });
    fireEvent.change(screen.getByLabelText('workspaceSettings.delivery.droneDeployCliImage'), {
      target: { value: 'alpine:3.21' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Save/ }));

    await waitFor(() => expect(mockState.updateWorkspace).toHaveBeenCalled());

    expect(mockState.updateWorkspace).toHaveBeenCalledWith(
      't-1',
      'p-1',
      'ws-1',
      expect.objectContaining({
        metadata: expect.objectContaining({
          source_control: expect.objectContaining({
            provider: 'github',
            repo: 'memstack/new-workspace',
            default_branch: 'develop',
            server_url: 'https://github.com',
            clone_url: 'https://github.com/memstack/new-workspace.git',
            auth_token_env: 'GITHUB_TOKEN',
          }),
          delivery_cicd: expect.objectContaining({
            provider: 'drone',
            code_root: '/workspace/my-evo',
            drone: expect.objectContaining({
              repo: 'memstack/new-workspace',
              branch: 'develop',
              server_url_env: 'DRONE_SERVER_URL',
              token_env: 'DRONE_TOKEN',
              poll_interval_seconds: 5,
              source_control: expect.objectContaining({
                provider: 'github',
                repo: 'memstack/new-workspace',
                default_branch: 'develop',
                server_url: 'https://github.com',
                clone_url: 'https://github.com/memstack/new-workspace.git',
                auth_token_env: 'GITHUB_TOKEN',
              }),
              environment: {
                api: {
                  server_url_env: 'DRONE_SERVER_URL',
                  token_env: 'DRONE_TOKEN',
                },
                server: {
                  server_port: 8080,
                  server_host: 'localhost:8080',
                  server_proto: 'http',
                  rpc_secret_env: 'DRONE_RPC_SECRET',
                  user_create: 'username:memstack,admin:true',
                  source_provider: 'github',
                  github_server: 'https://github.com',
                  github_client_id_env: 'DRONE_GITHUB_CLIENT_ID',
                  github_client_secret_env: 'DRONE_GITHUB_CLIENT_SECRET',
                  gitlab_server: 'https://gitlab.com',
                  gitlab_client_id_env: 'DRONE_GITLAB_CLIENT_ID',
                  gitlab_client_secret_env: 'DRONE_GITLAB_CLIENT_SECRET',
                  git_always_auth: false,
                },
                runner: {
                  runner_port: 3001,
                  runner_capacity: 2,
                  runner_name: 'memstack-custom-runner',
                  rpc_proto: 'http',
                  rpc_host: 'drone-server',
                  rpc_secret_env: 'DRONE_RPC_SECRET',
                },
              },
              deploy: expect.objectContaining({
                enabled: false,
                mode: 'cli',
                target: 'staging',
                stage: 'deploy',
                required: true,
                cli: {
                  image: 'alpine:3.21',
                  commands: [],
                },
              }),
            }),
          }),
        }),
      })
    );
  });
});
