import { useMemo, useState } from 'react';
import { MagnifyingGlassIcon } from '@radix-ui/react-icons';

import { ConversationDetail } from './components/ConversationDetail';
import { InboxView } from './components/InboxView';
import { LoginScreen } from './components/LoginScreen';
import { NewThreadComposer } from './components/NewThreadComposer';
import { SettingsWorkspace } from './components/SettingsWorkspace';
import { Sidebar } from './components/Sidebar';
import { WorkspaceOverview } from './components/WorkspaceOverview';
import { codeTasks, workTasks } from './data';
import { useI18n } from './i18n';
import { getProject, getProjectWorkspaces, getTenant } from './workspaceContext';

const SESSION_KEY = 'memstack.prototype.session.v1';

function getInitialSession() {
  try {
    const raw = window.localStorage.getItem(SESSION_KEY) ?? window.sessionStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function SearchView() {
  const { t } = useI18n();
  return (
    <main className="auxiliary-view">
      <header><span>MEMSTACK</span><h1>{t('nav.search')}</h1><p>{t('Find threads, sources, code changes, and artifacts across every project.')}</p></header>
      <section className="overview-grid">
        <article className="overview-hero"><MagnifyingGlassIcon /><h2>{t('Search the workspace')}</h2><p>{t('Search is scoped to the current project and respects workspace permissions.')}</p></article>
        <article><span>{t('THREADS')}</span><b>12</b><p>{t('Across all workspaces')}</p></article>
        <article><span>{t('SOURCES')}</span><b>28</b><p>{t('Verified project evidence')}</p></article>
        <article><span>{t('ARTIFACTS')}</span><b>9</b><p>{t('Ready to reference')}</p></article>
      </section>
    </main>
  );
}

export function App() {
  const [session, setSession] = useState(getInitialSession);
  const [view, setView] = useState('home');
  const [activeThread, setActiveThread] = useState(null);
  const [toast, setToast] = useState('');
  const [workItems, setWorkItems] = useState(() => workTasks);
  const [codeItems, setCodeItems] = useState(() => codeTasks);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState('account');
  const [tenantId, setTenantId] = useState('northstar');
  const [projectId, setProjectId] = useState('desktop-client');
  const [activeWorkspaceId, setActiveWorkspaceId] = useState('desktop-client-main');
  const [workspaceList, setWorkspaceList] = useState(() => getProjectWorkspaces('northstar', 'desktop-client'));

  const tenant = getTenant(tenantId);
  const project = getProject(tenantId, projectId);
  const allTasks = useMemo(() => [...workItems, ...codeItems], [workItems, codeItems]);
  const workspace = workspaceList.find((item) => item.id === activeWorkspaceId) ?? workspaceList[0];

  const threadIndex = useMemo(() => {
    const index = new Map();
    workspaceList.forEach((item) => {
      item.sessions.forEach((threadSession) => {
        if (!index.has(threadSession.taskId)) {
          index.set(threadSession.taskId, { workspaceId: item.id, workspaceName: item.name, session: threadSession });
        }
      });
    });
    return index;
  }, [workspaceList]);

  const taskById = (id) => allTasks.find((item) => item.id === id);

  function resolveThread(threadSession) {
    const task = taskById(threadSession.taskId);
    const status = !task ? threadSession.status : task.status === 'planning' ? 'running' : task.status;
    return { ...threadSession, status, meta: task?.meta ?? threadSession.meta };
  }

  const inboxItems = useMemo(() => allTasks.flatMap((task) => {
    const location = threadIndex.get(task.id);
    if (!location) return [];
    const mode = workItems.some((item) => item.id === task.id) ? 'work' : 'code';
    return [{ ...task, mode, workspaceId: location.workspaceId, workspaceName: location.workspaceName, sessionId: location.session.id }];
  }), [allTasks, threadIndex, workItems]);

  const inboxCount = inboxItems.filter((item) => item.status === 'input' || item.status === 'planning').length;

  const activeThreadSession = activeThread
    ? workspaceList.find((item) => item.id === activeThread.workspaceId)?.sessions.find((item) => item.id === activeThread.sessionId) ?? null
    : null;
  const activeTask = activeThreadSession ? taskById(activeThreadSession.taskId) : null;
  const activeWorkspace = activeThread
    ? workspaceList.find((item) => item.id === activeThread.workspaceId) ?? workspace
    : workspace;

  function showToast(message) {
    setToast(message);
    window.setTimeout(() => setToast(''), 3200);
  }

  function updateTask(taskId, patch) {
    setWorkItems((current) => current.map((item) => item.id === taskId ? { ...item, ...patch } : item));
    setCodeItems((current) => current.map((item) => item.id === taskId ? { ...item, ...patch } : item));
  }

  function openThread(threadSession, workspaceId = activeWorkspaceId) {
    setActiveWorkspaceId(workspaceId);
    setActiveThread({ workspaceId, sessionId: threadSession.id });
    setView('thread');
  }

  function openInboxItem(item) {
    const threadSession = threadIndex.get(item.id)?.session ?? { id: item.id, taskId: item.id, mode: item.mode, title: item.title, status: item.status, meta: item.meta };
    openThread(threadSession, item.workspaceId);
  }

  function createThread(draft) {
    const id = `thread-${Date.now()}`;
    const title = draft.prompt.length > 56 ? `${draft.prompt.slice(0, 56)}…` : draft.prompt;
    const createdTask = {
      id,
      title,
      summary: draft.prompt,
      status: 'planning',
      meta: 'Agent is planning',
      progress: 0,
      phase: 'Proposing a plan',
      planPhase: 'generating',
      model: draft.model,
      effort: draft.effort,
      permission: draft.permission,
      prompt: draft.prompt,
    };
    if (draft.mode === 'work') {
      setWorkItems((current) => [createdTask, ...current]);
    } else {
      setCodeItems((current) => [createdTask, ...current]);
    }
    const threadSession = { id, taskId: id, mode: draft.mode, title, status: 'running', meta: 'Agent is planning' };
    setWorkspaceList((current) => current.map((item) => item.id === activeWorkspaceId ? { ...item, sessions: [threadSession, ...item.sessions] } : item));
    setActiveThread({ workspaceId: activeWorkspaceId, sessionId: id });
    setView('thread');
    window.setTimeout(() => updateTask(id, { planPhase: 'ready', meta: 'Plan ready for review' }), 2200);
  }

  function approvePlan(taskId, approvedPlan) {
    updateTask(taskId, {
      status: 'running',
      planPhase: 'approved',
      plan: approvedPlan,
      meta: `${approvedPlan.length} approved steps · starting`,
      progress: 4,
      phase: 'Starting approved plan',
    });
    showToast('Plan approved. Agent task started.');
  }

  function resolveApproval(taskId, action, instruction) {
    const labels = {
      'allow-once': 'Allowed once',
      'allow-always': 'Always allowed',
      deny: 'Denied',
    };
    updateTask(taskId, {
      status: 'running',
      meta: `${labels[action]} · resuming`,
      phase: 'Resuming after your decision',
    });
    showToast(instruction ? 'Decision and instruction sent. Thread resumed.' : 'Decision recorded. Thread resumed.');
  }

  function login(nextSession) {
    const value = { email: nextSession.email, signedInAt: Date.now() };
    const storage = nextSession.remember ? window.localStorage : window.sessionStorage;
    storage.setItem(SESSION_KEY, JSON.stringify(value));
    setSession(value);
  }

  function signOut() {
    window.localStorage.removeItem(SESSION_KEY);
    window.sessionStorage.removeItem(SESSION_KEY);
    setSettingsOpen(false);
    setSession(null);
  }

  function openSettings(section = 'account') {
    setSettingsSection(section);
    setSettingsOpen(true);
  }

  function changeContext(nextContext) {
    setTenantId(nextContext.tenantId);
    setProjectId(nextContext.projectId);
    const nextWorkspaces = getProjectWorkspaces(nextContext.tenantId, nextContext.projectId);
    setWorkspaceList(nextWorkspaces);
    setActiveWorkspaceId(nextWorkspaces[0].id);
    setActiveThread(null);
    setView('home');
    setSettingsOpen(false);
  }

  function openWorkspace(workspaceId) {
    setActiveWorkspaceId(workspaceId);
    setView('workspace');
  }

  if (!session) {
    return <LoginScreen onLogin={login} />;
  }

  return (
    <div className="desktop-app">
      <Sidebar
        view={view}
        activeWorkspaceId={workspace.id}
        activeThreadId={activeThread?.sessionId ?? null}
        inboxCount={inboxCount}
        tenant={tenant}
        project={project}
        workspaces={workspaceList}
        settingsOpen={settingsOpen}
        resolveThread={resolveThread}
        onNavigate={setView}
        onOpenWorkspace={openWorkspace}
        onOpenThread={openThread}
        onNewThread={() => setView('home')}
        onOpenSettings={openSettings}
        onSignOut={signOut}
      />
      {view === 'thread' && activeThreadSession ? (
        <ConversationDetail
          key={`${activeThreadSession.mode}-${activeThreadSession.taskId}`}
          mode={activeThreadSession.mode}
          task={activeTask ?? { id: activeThreadSession.taskId, title: activeThreadSession.title, summary: '', status: activeThreadSession.status, meta: activeThreadSession.meta, progress: 0, phase: '' }}
          project={project}
          workspace={activeWorkspace}
          onApprovePlan={(plan) => approvePlan(activeThreadSession.taskId, plan)}
          onRevisePlan={() => {
            updateTask(activeThreadSession.taskId, { planPhase: 'generating', meta: 'Agent is revising the plan' });
            window.setTimeout(() => updateTask(activeThreadSession.taskId, { planPhase: 'ready', meta: 'Revised plan ready' }), 1800);
          }}
          onResolveApproval={(action, instruction) => resolveApproval(activeThreadSession.taskId, action, instruction)}
          onToast={showToast}
        />
      ) : view === 'inbox' ? (
        <InboxView items={inboxItems} onOpenThread={openInboxItem} />
      ) : view === 'workspace' ? (
        <WorkspaceOverview
          tenant={tenant}
          project={project}
          workspace={workspace}
          onNewTask={() => setView('home')}
          onOpenSession={(threadSession) => openThread(threadSession, workspace.id)}
          onConfigure={() => openSettings('workspace')}
        />
      ) : view === 'search' ? (
        <SearchView />
      ) : (
        <NewThreadComposer
          workspace={workspace}
          recentThreads={workspace.sessions.map(resolveThread)}
          onCreate={createThread}
          onOpenThread={(threadSession) => openThread(threadSession, workspace.id)}
        />
      )}

      {settingsOpen ? <SettingsWorkspace key={settingsSection} initialSection={settingsSection} onClose={() => setSettingsOpen(false)} onToast={showToast} onSignOut={signOut} session={session} currentTenantId={tenantId} currentProjectId={projectId} onContextChange={changeContext} /> : null}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
