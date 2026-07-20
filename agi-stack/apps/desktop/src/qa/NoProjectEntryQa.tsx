import '@radix-ui/themes/styles.css';
import React, { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';

import { DesktopSidebar } from '../features/navigation/DesktopSidebar';
import { SettingsWindow, type SettingsSection } from '../features/settings/SettingsWindow';
import { NewTaskFlow } from '../features/task/NewTaskFlow';
import { WorkspaceOverview } from '../features/workspace/WorkspaceOverview';
import { I18nProvider, useI18n } from '../i18n';
import type {
  AuthState,
  DesktopRuntimeConfig,
  ProjectSummary,
  TenantSummary,
  WorkspaceAuthorityCollection,
  WorkspaceSummary,
} from '../types';
import '../styles.css';

declare global {
  var __noProjectEntryQaRoot: Root | undefined;
}

const QA_API_ORIGIN = 'https://no-project.qa.memstack.invalid';
const NOW = '2026-07-18T08:00:00.000Z';
const qaSearchParams = new URLSearchParams(window.location.search);
const qaScenario = qaSearchParams.get('scenario');
const qaWindowState = qaSearchParams.get('state');

const tenants: TenantSummary[] = [
  {
    id: 'tenant-northstar',
    name: 'Northstar Labs',
    slug: 'northstar.ai',
    description: '3 workspaces · northstar.ai',
    plan: 'Enterprise',
  },
  {
    id: 'tenant-orbital',
    name: 'Orbital Research',
    slug: 'orbital-research.org',
    description: 'Research organization · orbital-research.org',
    plan: 'Team',
  },
  {
    id: 'tenant-sandbox',
    name: "Alex's Sandbox",
    slug: 'alex-sandbox',
    description: 'Owner · Private workspace',
    plan: 'Personal',
  },
];

const projectsByTenant: Record<string, ProjectSummary[]> = {
  'tenant-northstar': [],
  'tenant-orbital': [
    {
      id: 'project-orbital-signals',
      tenant_id: 'tenant-orbital',
      name: 'Signal Observatory',
      description: 'Research signals and evidence review',
      member_ids: ['user-alex', 'user-rhea', 'user-sam'],
      is_public: false,
    },
  ],
  'tenant-sandbox': [
    {
      id: 'project-personal-lab',
      tenant_id: 'tenant-sandbox',
      name: 'Personal Lab',
      description: 'Private experiments and drafts',
      member_ids: ['user-alex'],
      is_public: false,
    },
  ],
};

const initialConfig: DesktopRuntimeConfig = {
  apiBaseUrl: QA_API_ORIGIN,
  apiKey: 'qa-authenticated-session',
  localApiToken: '',
  tenantId: '',
  projectId: '',
  workspaceId: '',
  mode: 'cloud',
  workspaceRoot: '',
};

const initialAuth: AuthState = {
  status: 'signed_in',
  credentialKind: 'cloud_session',
  session: {
    session_id: 'qa-session-no-project',
    auth_method: 'password',
    expires_at: '2026-07-19T08:00:00.000Z',
    trusted_device: true,
  },
  context: null,
  user: {
    user_id: 'user-alex',
    email: 'alex@northstar.ai',
    name: 'Alex Chen',
    roles: ['admin'],
    is_active: true,
    created_at: '2025-03-12T09:00:00.000Z',
    profile: {},
  },
  tenants,
  projects: [],
  mustChangePassword: false,
  error: null,
};

async function noProjectQaFetch(input: RequestInfo | URL): Promise<Response> {
  const url = new URL(String(input), QA_API_ORIGIN);
  if (url.origin === QA_API_ORIGIN && url.pathname === '/api/v1/projects') {
    const tenantId = url.searchParams.get('tenant_id') ?? '';
    const page = Number(url.searchParams.get('page'));
    const pageSize = Number(url.searchParams.get('page_size'));
    const projects = projectsByTenant[tenantId] ?? [];
    const start = (page - 1) * pageSize;
    return jsonResponse({
      projects: projects.slice(start, start + pageSize),
      total: projects.length,
      page,
      page_size: pageSize,
    });
  }
  return jsonResponse({ detail: `Unhandled QA route: GET ${url.pathname}` }, 404);
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

globalThis.fetch = noProjectQaFetch;
try {
  window.localStorage.setItem('agistack.desktop.locale', 'zh-CN');
} catch {
  // The QA page still follows the browser language when storage is unavailable.
}

function NoProjectEntryQa() {
  const { t } = useI18n();
  const [auth, setAuth] = useState<AuthState>(() =>
    qaScenario === 'empty-workspaces'
      ? {
          ...initialAuth,
          context: {
            tenant_id: 'tenant-orbital',
            project_id: 'project-orbital-signals',
            revision: 1,
            updated_at: NOW,
          },
          projects: projectsByTenant['tenant-orbital'],
        }
      : initialAuth,
  );
  const [config, setConfig] = useState<DesktopRuntimeConfig>(() =>
    qaScenario === 'empty-workspaces'
      ? {
          ...initialConfig,
          tenantId: 'tenant-orbital',
          projectId: 'project-orbital-signals',
        }
      : initialConfig,
  );
  const [mode, setMode] = useState<'work' | 'code'>('work');
  const [settingsSection, setSettingsSection] = useState<SettingsSection>('workspace');
  const [settingsOpen, setSettingsOpen] = useState(
    () =>
      qaWindowState === 'open' ||
      (qaScenario !== 'empty-workspaces' && qaWindowState !== 'closed'),
  );
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const selectedTenant = auth.tenants.find((tenant) => tenant.id === config.tenantId) ?? null;
  const selectedProject = auth.projects.find((project) => project.id === config.projectId) ?? null;
  const tenantName = selectedTenant?.name || t('settings.noTenantSelected');
  const projectName = selectedProject?.name || t('settings.noProjectSelected');
  const newTaskDisabledReason = selectedProject ? null : t('task.disabledProjectRequired');
  const workspaceAuthority: WorkspaceAuthorityCollection<WorkspaceSummary> = selectedProject
    ? { status: 'ready', items: [], error: null }
    : { status: 'unavailable', items: [], error: null };
  const projectNodeState = selectedProject
    ? { [selectedProject.id]: { loading: false, error: null } }
    : {};
  const unavailableRoster = useMemo(
    () => ({ status: 'unavailable' as const, items: [], error: null }),
    [],
  );

  const openSettings = (section: SettingsSection) => {
    setSettingsSection(section);
    setSettingsOpen(true);
  };

  const applyContext = async (tenantId: string, projectId: string) => {
    const projects = projectsByTenant[tenantId] ?? [];
    const project = projects.find((candidate) => candidate.id === projectId);
    if (!project) throw new Error(t('settings.selectedProjectUnavailable'));
    setConfig((current) => ({
      ...current,
      tenantId,
      projectId,
      workspaceId: '',
    }));
    setAuth((current) => ({
      ...current,
      context: {
        tenant_id: tenantId,
        project_id: projectId,
        revision: 1,
        updated_at: NOW,
      },
      projects,
    }));
  };

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="app-shell hierarchy-shell runtime-mode browser-window">
        <section className="desktop-body">
          <DesktopSidebar
            activeSection={null}
            mode={mode}
            taskCount={0}
            tenantName={tenantName}
            projectName={projectName}
            user={auth.user}
            workspaces={[]}
            conversationsByWorkspace={{}}
            nodeState={{ projects: projectNodeState, workspaces: {} }}
            currentProjectId={config.projectId}
            currentWorkspaceId=""
            currentConversationId={null}
            workspaceTreeSelectionMode="overview"
            expandedWorkspaceIds={new Set()}
            newTaskDisabledReason={newTaskDisabledReason}
            onModeChange={setMode}
            onNavigate={() => undefined}
            onToggleWorkspace={() => undefined}
            onRetryProject={() => undefined}
            onRetryWorkspace={() => undefined}
            onSelectWorkspace={() => undefined}
            onSelectConversation={() => undefined}
            onNewTask={() => setNewTaskOpen(true)}
            onOpenAccountSettings={() => openSettings('account')}
            onSwitchWorkspace={() => openSettings('workspace')}
            onSignOut={() => undefined}
          />

          <main className="workbench">
            <WorkspaceOverview
              workspace={null}
              project={selectedProject}
              tenantName={tenantName}
              workspaceAuthority={workspaceAuthority}
              conversations={[]}
              members={unavailableRoster}
              agents={unavailableRoster}
              plan={null}
              sandboxStatus={null}
              newTaskDisabledReason={newTaskDisabledReason}
              onNewTask={() => setNewTaskOpen(true)}
              onRetryWorkspaces={() => undefined}
              onOpenConversation={() => undefined}
              onOpenSettings={() => openSettings('workspace')}
            />
          </main>
        </section>

        <NewTaskFlow
          open={newTaskOpen}
          config={config}
          actorId={auth.user?.user_id}
          workspaceAuthority={workspaceAuthority}
          preferredWorkspaceId=""
          preferredKind={mode === 'code' ? 'programming' : 'general'}
          disabledReason={newTaskDisabledReason}
          onClose={() => setNewTaskOpen(false)}
          onSessionPersisted={() => undefined}
          onSessionReady={() => setNewTaskOpen(false)}
          onRunAgentTurn={async () => 'acknowledged'}
          onOpenRuntimeSettings={() => openSettings('workspace')}
          onError={() => undefined}
        />

        <SettingsWindow
          open={settingsOpen}
          initialSection={settingsSection}
          auth={auth}
          config={config}
          connection="idle"
          wsConnected={false}
          wsError={null}
          runtimeDisabledReason={newTaskDisabledReason}
          onClose={() => setSettingsOpen(false)}
          onConfigChange={setConfig}
          onRuntimeStatusRefresh={async () => undefined}
          onRefreshRuntime={() => undefined}
          onContextChange={applyContext}
          onSignOut={() => undefined}
        />
      </div>
    </Theme>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root container');

const qaRoot = globalThis.__noProjectEntryQaRoot ?? createRoot(root);
globalThis.__noProjectEntryQaRoot = qaRoot;

qaRoot.render(
  <React.StrictMode>
    <I18nProvider>
      <NoProjectEntryQa />
    </I18nProvider>
  </React.StrictMode>,
);
