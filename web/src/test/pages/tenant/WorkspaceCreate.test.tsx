import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';

import { act, fireEvent, render, screen, waitFor } from '../../utils';

import { WorkspaceCreate } from '../../../pages/tenant/WorkspaceCreate';

let projectState: any;
let tenantState: any;
let workspaceState: any;

vi.mock('../../../stores/tenant', () => ({
  useCurrentTenant: () => tenantState.currentTenant,
}));

vi.mock('../../../stores/project', () => ({
  useCurrentProject: () => projectState.currentProject,
  useProjectStore: (selector: (state: any) => unknown) =>
    selector({
      projects: projectState.projects,
      listProjects: projectState.listProjects,
    }),
}));

vi.mock('../../../stores/workspace', () => ({
  useWorkspaceActions: () => workspaceState.actions,
}));

describe('WorkspaceCreate', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    tenantState = {
      currentTenant: { id: 'tenant-1', name: 'Tenant One' },
    };

    projectState = {
      projects: [{ id: 'project-1', name: 'Project One' }],
      currentProject: { id: 'project-1', name: 'Project One' },
      listProjects: vi.fn().mockResolvedValue(undefined),
    };

    workspaceState = {
      actions: {
        createWorkspace: vi.fn().mockResolvedValue({ id: 'ws-created', name: 'My Evo delivery' }),
      },
    };
  });

  it('creates programming workspaces with scenario and collaboration metadata', async () => {
    render(
      <Routes>
        <Route
          path="/tenant/:tenantId/project/:projectId/workspaces/new"
          element={<WorkspaceCreate />}
        />
        <Route
          path="/tenant/:tenantId/project/:projectId/blackboard"
          element={<div>Blackboard destination</div>}
        />
      </Routes>,
      { route: '/tenant/tenant-1/project/project-1/workspaces/new' }
    );

    await act(async () => {
      fireEvent.change(screen.getByLabelText('Workspace name'), {
        target: { value: 'My Evo delivery' },
      });
      fireEvent.change(screen.getByLabelText('Objective'), {
        target: { value: 'Ship the My Evo workspace automation plan' },
      });
      fireEvent.click(screen.getByText('Programming'));
      fireEvent.click(screen.getByText('Autonomous'));
    });

    await waitFor(() => {
      expect(screen.getByLabelText('Sandbox code root')).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.change(screen.getByLabelText('Sandbox code root'), {
        target: { value: '/workspace/my-evo' },
      });
      fireEvent.change(screen.getByDisplayValue('localhost:8080'), {
        target: { value: 'drone.localhost:8080' },
      });
      fireEvent.change(screen.getByDisplayValue('memstack-drone-runner'), {
        target: { value: 'memstack-custom-runner' },
      });
      fireEvent.click(screen.getByRole('button', { name: /Create Workspace/i }));
    });

    await waitFor(() => {
      expect(workspaceState.actions.createWorkspace).toHaveBeenCalledWith('tenant-1', 'project-1', {
        name: 'My Evo delivery',
        description: 'Ship the My Evo workspace automation plan',
        use_case: 'programming',
        collaboration_mode: 'autonomous',
        sandbox_code_root: '/workspace/my-evo',
        source_control: {
          provider: 'github',
          repo: 'memstack/my-evo-delivery',
          default_branch: 'main',
          server_url: 'https://github.com',
          clone_url: 'https://github.com/memstack/my-evo-delivery.git',
          auth_token_env: 'GITHUB_TOKEN',
        },
        metadata: {
          workspace_use_case: 'programming',
          workspace_type: 'software_development',
          collaboration_mode: 'autonomous',
          agent_conversation_mode: 'autonomous',
          autonomy_profile: { workspace_type: 'software_development' },
          sandbox_code_root: '/workspace/my-evo',
          code_context: { sandbox_code_root: '/workspace/my-evo' },
          source_control: {
            provider: 'github',
            repo: 'memstack/my-evo-delivery',
            default_branch: 'main',
            server_url: 'https://github.com',
            clone_url: 'https://github.com/memstack/my-evo-delivery.git',
            auth_token_env: 'GITHUB_TOKEN',
          },
          delivery_cicd: {
            provider: 'drone',
            code_root: '/workspace/my-evo',
            agent_managed: false,
            contract_source: 'workspace_defaults',
            contract_confidence: 1,
            timeout_seconds: 600,
            auto_deploy: false,
            drone: {
              repo: 'memstack/my-evo-delivery',
              branch: 'main',
              server_url_env: 'DRONE_SERVER_URL',
              token_env: 'DRONE_TOKEN',
              poll_interval_seconds: 5,
              source_control: {
                provider: 'github',
                repo: 'memstack/my-evo-delivery',
                default_branch: 'main',
                server_url: 'https://github.com',
                clone_url: 'https://github.com/memstack/my-evo-delivery.git',
                auth_token_env: 'GITHUB_TOKEN',
              },
              environment: {
                api: {
                  server_url_env: 'DRONE_SERVER_URL',
                  token_env: 'DRONE_TOKEN',
                },
                server: {
                  server_port: 8080,
                  server_host: 'drone.localhost:8080',
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
              deploy: {
                enabled: false,
                mode: 'cli',
                stage: 'deploy',
                required: true,
                cli: {
                  image: 'alpine:3.20',
                  commands: [],
                },
                docker: {
                  context: '.',
                  dockerfile: 'Dockerfile',
                  tags: ['latest'],
                },
                kubernetes: {
                  namespace: 'default',
                  manifest_paths: ['k8s/*.yaml'],
                  kubeconfig_secret: 'kubeconfig',
                  kubectl_image: 'bitnami/kubectl:latest',
                },
              },
            },
          },
        },
      });
    });
    expect(await screen.findByText('Blackboard destination')).toBeInTheDocument();
  });

  it('requires the creation brief before creating a workspace', async () => {
    render(
      <Routes>
        <Route
          path="/tenant/:tenantId/project/:projectId/workspaces/new"
          element={<WorkspaceCreate />}
        />
      </Routes>,
      { route: '/tenant/tenant-1/project/project-1/workspaces/new' }
    );

    await act(async () => {
      fireEvent.change(screen.getByLabelText('Workspace name'), {
        target: { value: 'Name only' },
      });
    });

    expect(screen.getByRole('button', { name: /Create Workspace/i })).toBeDisabled();
    expect(workspaceState.actions.createWorkspace).not.toHaveBeenCalled();
  });
});
