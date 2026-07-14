import {
  ActivityLogIcon,
  CheckCircledIcon,
  ClockIcon,
  CodeIcon,
  CubeIcon,
  DashboardIcon,
  ExclamationTriangleIcon,
  FileTextIcon,
  GearIcon,
  LightningBoltIcon,
  PersonIcon,
  PlusIcon,
  ReaderIcon,
  RocketIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

const statusIcon = {
  running: LightningBoltIcon,
  input: ExclamationTriangleIcon,
  ready: CheckCircledIcon,
};

const activityIcon = {
  artifact: FileTextIcon,
  memory: ReaderIcon,
  member: PersonIcon,
  task: DashboardIcon,
  verification: CheckCircledIcon,
};

function Metric({ label, value, note, tone = '' }) {
  return (
    <article className={`workspace-metric ${tone}`}>
      <span>{label}</span>
      <b>{value}</b>
      <small>{note}</small>
    </article>
  );
}

export function WorkspaceOverview({ tenant, project, workspace, onNewTask, onOpenSession, onConfigure }) {
  const { t } = useI18n();
  const running = workspace.sessions.filter((session) => session.status === 'running').length;
  const attention = workspace.sessions.filter((session) => session.status === 'input').length;
  const ready = workspace.sessions.filter((session) => session.status === 'ready').length;
  const modeLabel = workspace.conversationMode === 'multi_agent_shared' ? t('Shared multi-agent') : t('Single agent');

  return (
    <main className="workspace-overview">
      <header className="workspace-overview-header">
        <div>
          <span>{tenant.name} / {project.name}</span>
          <div className="workspace-title-line"><h1>{workspace.name}</h1><em><i />{t('Workspace online')}</em></div>
          <p>{t(workspace.description)}</p>
        </div>
        <div className="workspace-header-actions">
          <button type="button" onClick={onConfigure}><GearIcon />{t('Configure')}</button>
          <button className="primary" type="button" onClick={onNewTask}><PlusIcon />{t('nav.newTask')}</button>
        </div>
      </header>

      <section className="workspace-summary-grid">
        <article className="workspace-goal-card">
          <div className="workspace-card-heading"><span><RocketIcon /></span><div><small>{t('ROOT GOAL')}</small><h2>{t('Workspace purpose')}</h2></div></div>
          <p>{t(workspace.goal)}</p>
          <div className="workspace-goal-facts">
            <span><CubeIcon />{modeLabel}</span>
            <span><CheckCircledIcon />{t('Evidence required')}</span>
            <span><ClockIcon />{t('Updated')} {t(workspace.updated)}</span>
          </div>
        </article>
        <div className="workspace-metrics-grid">
          <Metric label={t('ACTIVE SESSIONS')} value={workspace.sessions.length} note={t('{running} running · {ready} ready', { running, ready })} tone="cyan" />
          <Metric label={t('NEEDS ATTENTION')} value={attention} note={attention ? t('Approval or input required') : t('No blocked sessions')} tone={attention ? 'amber' : 'green'} />
          <Metric label={t('MEMBERS')} value={workspace.members} note={t('Workspace collaborators')} />
          <Metric label={t('ACTIVE AGENTS')} value={workspace.agents} note={t('Bound to this workspace')} tone="green" />
        </div>
      </section>

      <section className="workspace-system-grid">
        <article>
          <header><ReaderIcon /><div><b>{t('Project knowledge')}</b><small>{t('Shared across this project')}</small></div><em>{t('Healthy')}</em></header>
          <div className="workspace-system-metrics"><span><b>{workspace.memories}</b><small>{t('Project memories')}</small></span><span><b>{workspace.graphNodes.toLocaleString()}</b><small>{t('Graph nodes')}</small></span><span><b>{workspace.storage}</b><small>{t('Storage')}</small></span></div>
        </article>
        <article>
          <header><PersonIcon /><div><b>{t('Agent roster')}</b><small>{modeLabel}</small></div><em>{workspace.agents} {t('active')}</em></header>
          <div className="workspace-agent-stack"><span>PL</span><span>RS</span><span>CD</span><span>RV</span><div><b>{t('Planner, researcher, coder, reviewer')}</b><small>{t('Explicit workspace bindings')}</small></div></div>
        </article>
        <article>
          <header><CodeIcon /><div><b>{t('Execution environment')}</b><small>{t('Project sandbox')}</small></div><em>{t('Connected')}</em></header>
          <div className="workspace-environment"><span><i />{t('Cloud sandbox')}</span><b>{t('Ready for isolated runs')}</b><small>{t('Credentials and tools inherit project policy')}</small></div>
        </article>
      </section>

      <section className="workspace-lower-grid">
        <article className="workspace-sessions-card">
          <header><div><span>{t('CONVERSATIONS')}</span><h2>{t('Recent sessions')}</h2></div><small>{workspace.sessions.length} {t('total')}</small></header>
          <div>
            {workspace.sessions.map((session) => {
              const StatusIcon = statusIcon[session.status] ?? ActivityLogIcon;
              return (
                <button type="button" key={session.id} onClick={() => onOpenSession(session)}>
                  <span className={`workspace-session-icon ${session.mode}`}><StatusIcon /></span>
                  <span><b>{session.title}</b><small>{t(session.meta)}</small></span>
                  <em className={session.status}>{t(session.status === 'input' ? 'Needs input' : session.status === 'running' ? 'Running' : 'Ready')}</em>
                </button>
              );
            })}
          </div>
        </article>
        <article className="workspace-activity-card">
          <header><div><span>{t('AUDIT TRAIL')}</span><h2>{t('Recent activity')}</h2></div><ActivityLogIcon /></header>
          <div>
            {workspace.activity.map((item, index) => {
              const ItemIcon = activityIcon[item.type] ?? ActivityLogIcon;
              return <div key={`${item.title}-${index}`}><span><ItemIcon /></span><p><b>{t(item.title)}</b><small>{t(item.meta)}</small></p></div>;
            })}
          </div>
        </article>
      </section>
    </main>
  );
}
