import { useMemo, useState } from 'react';
import {
  ArchiveIcon,
  DashboardIcon,
  LightningBoltIcon,
  MagnifyingGlassIcon,
  PlusIcon,
} from '@radix-ui/react-icons';

import { Dialog } from './components/Dialog';
import { LoginScreen } from './components/LoginScreen';
import { NewTaskFlow } from './components/NewTaskFlow';
import { SettingsWorkspace } from './components/SettingsWorkspace';
import { Sidebar } from './components/Sidebar';
import { SourcesDialog, TaskDetail } from './components/TaskDetail';
import { TaskQueue } from './components/TaskQueue';
import { codeTasks, workTasks } from './data';
import { useI18n } from './i18n';
import { getProject, getTenant } from './workspaceContext';

const SESSION_KEY = 'memstack.prototype.session.v1';

function getInitialSession() {
  try {
    const raw = window.localStorage.getItem(SESSION_KEY) ?? window.sessionStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

const auxiliaryCopy = {
  Home: ['Good afternoon, Alex', 'Three tasks are running and two artifacts are ready for review.', DashboardIcon],
  Automations: ['Automations', 'Schedule recurring agent tasks with explicit inputs, approval boundaries, and delivery targets.', LightningBoltIcon],
  Search: ['Search workspace', 'Find tasks, conversations, sources, code changes, and artifacts across every project.', MagnifyingGlassIcon],
  Projects: ['Projects', 'Shared context containers for tasks, memory, environments, people, and deliverables.', ArchiveIcon],
};

function AuxiliaryView({ name, onOpenWork, tenant, project }) {
  const { t } = useI18n();
  const [title, description, Icon] = auxiliaryCopy[name] ?? auxiliaryCopy.Home;
  const isProject = name === 'Projects';
  return (
    <main className="auxiliary-view">
      <header><span>{isProject ? tenant.name.toUpperCase() : 'MEMSTACK'}</span><h1>{isProject ? project.name : name === 'Home' ? title : t(`nav.${name === 'Automations' ? 'automations' : name === 'Search' ? 'search' : 'projects'}`)}</h1><p>{isProject ? t(project.description) : description}</p></header>
      <section className="overview-grid">
        <article className="overview-hero"><Icon /><h2>One workspace for every agent task</h2><p>Move from research to code without losing context, approvals, sources, or the final artifact.</p><button className="primary" type="button" onClick={onOpenWork}><PlusIcon /> {t('nav.myWork')}</button></article>
        <article><span>RUNNING</span><b>3</b><p>Across Work and Code</p></article>
        <article><span>NEEDS INPUT</span><b>2</b><p>One decision, one approval</p></article>
        <article><span>READY</span><b>4</b><p>Artifacts waiting for review</p></article>
      </section>
    </main>
  );
}

export function App() {
  const [session, setSession] = useState(getInitialSession);
  const [activeNav, setActiveNav] = useState('My Work');
  const [mode, setMode] = useState('work');
  const [selected, setSelected] = useState({ work: 'strategy-brief', code: 'flaky-test' });
  const [paused, setPaused] = useState(false);
  const [dialog, setDialog] = useState(null);
  const [toast, setToast] = useState('');
  const [workItems, setWorkItems] = useState(() => workTasks);
  const [codeItems, setCodeItems] = useState(() => codeTasks);
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState('account');
  const [tenantId, setTenantId] = useState('northstar');
  const [projectId, setProjectId] = useState('product-strategy');
  const tasks = mode === 'work' ? workItems : codeItems;
  const task = useMemo(() => tasks.find((item) => item.id === selected[mode]) ?? tasks[0], [mode, selected, tasks]);
  const tenant = getTenant(tenantId);
  const project = getProject(tenantId, projectId);

  function showToast(message) {
    setToast(message);
    window.setTimeout(() => setToast(''), 3200);
  }

  function changeMode(nextMode) {
    setMode(nextMode);
    setActiveNav('My Work');
    setPaused(false);
  }

  function createTask(draft) {
    const createdTask = {
      id: `created-${Date.now()}`,
      title: draft.title,
      summary: draft.objective,
      status: 'running',
      meta: `${draft.plan.length} approved steps · starting`,
      progress: 4,
      phase: 'Starting approved plan',
      plan: draft.plan,
      context: draft.context,
    };
    if (draft.mode === 'work') {
      setWorkItems((current) => [createdTask, ...current]);
    } else {
      setCodeItems((current) => [createdTask, ...current]);
    }
    setMode(draft.mode);
    setSelected((current) => ({ ...current, [draft.mode]: createdTask.id }));
    setActiveNav('My Work');
    setNewTaskOpen(false);
    showToast('Plan approved. Agent task started.');
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
    setActiveNav('Projects');
    setSettingsOpen(false);
  }

  if (!session) {
    return <LoginScreen onLogin={login} />;
  }

  return (
    <div className="desktop-app">
      <Sidebar
        activeNav={activeNav}
        mode={mode}
        taskCount={workItems.length + codeItems.length}
        tenant={tenant}
        project={project}
        settingsOpen={settingsOpen}
        onModeChange={changeMode}
        onNavigate={setActiveNav}
        onNewTask={() => { setActiveNav('My Work'); setNewTaskOpen(true); }}
        onOpenSettings={openSettings}
        onSignOut={signOut}
      />
      {activeNav === 'My Work' ? (
        <main className="mission-control">
          <TaskQueue
            mode={mode}
            tasks={tasks}
            selectedId={task.id}
            onSelect={(id) => setSelected((current) => ({ ...current, [mode]: id }))}
            onInput={(inputTask) => setDialog({ type: 'input', task: inputTask })}
          />
          <TaskDetail
            mode={mode}
            task={task}
            paused={paused}
            onPause={() => setPaused((current) => !current)}
            onInput={(inputTask) => setDialog({ type: 'input', task: inputTask })}
            onSources={() => setDialog({ type: 'sources' })}
            onToast={showToast}
          />
        </main>
      ) : <AuxiliaryView name={activeNav} tenant={tenant} project={project} onOpenWork={() => setActiveNav('My Work')} />}

      {dialog?.type === 'input' && (
        <Dialog title="Review agent request" onClose={() => setDialog(null)}>
          <div className="request-body">
            <span className="request-label">TASK</span>
            <h3>{dialog.task.title}</h3>
            <p>The agent recommends proceeding with the conservative option. This keeps the change reversible and inside the current project boundary.</p>
            <label><span>Your instruction</span><textarea defaultValue="Proceed with the conservative option and document the trade-off." /></label>
            <div className="dialog-actions"><button type="button" onClick={() => setDialog(null)}>Cancel</button><button className="primary" type="button" onClick={() => { setDialog(null); showToast('Instruction sent. Task resumed.'); }}>Send and resume</button></div>
          </div>
        </Dialog>
      )}
      {dialog?.type === 'sources' && <Dialog title="Source workspace" onClose={() => setDialog(null)}><SourcesDialog onClose={() => setDialog(null)} /></Dialog>}
      {newTaskOpen ? <NewTaskFlow initialMode={mode} onClose={() => setNewTaskOpen(false)} onCreate={createTask} /> : null}
      {settingsOpen ? <SettingsWorkspace key={settingsSection} initialSection={settingsSection} onClose={() => setSettingsOpen(false)} onToast={showToast} onSignOut={signOut} session={session} currentTenantId={tenantId} currentProjectId={projectId} onContextChange={changeContext} /> : null}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
