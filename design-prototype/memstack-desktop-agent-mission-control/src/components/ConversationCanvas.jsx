import { useState } from 'react';
import {
  ActivityLogIcon,
  CheckCircledIcon,
  ChevronDownIcon,
  ClockIcon,
  CodeIcon,
  CommitIcon,
  DesktopIcon,
  EnterFullScreenIcon,
  ExternalLinkIcon,
  ExitFullScreenIcon,
  FileTextIcon,
  ReaderIcon,
  ReloadIcon,
  StackIcon,
  TargetIcon,
  Cross2Icon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

const codeTabs = [
  ['overview', 'Overview', StackIcon],
  ['plan', 'Plan', TargetIcon],
  ['changes', 'Changes', CodeIcon, '4'],
  ['terminal', 'Terminal', DesktopIcon],
  ['checks', 'Checks', CheckCircledIcon, '3'],
];

const workTabs = [
  ['overview', 'Overview', StackIcon],
  ['plan', 'Plan', TargetIcon],
  ['artifact', 'Artifact', FileTextIcon],
  ['sources', 'Sources', ReaderIcon, '28'],
  ['checks', 'Verify', CheckCircledIcon, '3'],
];

const diffLines = [
  ['38', '38', '  async def run_job(job: PipelineJob) -> Result:'],
  ['39', '', '-     async with shared_fixture() as runner:'],
  ['', '39', '+     async with isolated_fixture(job.id) as runner:'],
  ['40', '40', '          await runner.execute(job)'],
  ['41', '41', '          await runner.wait_until_idle()'],
  ['', '42', '+         await runner.assert_owner(job.id)'],
  ['42', '43', '      return runner.result'],
];

function StatusDot({ status }) {
  return <i className={`session-dot ${status}`} />;
}

function OverviewCanvas({ mode, task, onOpenTask, t }) {
  const stages = [
    ['Understand', 'Repository and task context inspected', 'complete'],
    ['Implement', mode === 'code' ? 'Fixture scoped and regression test added' : 'Leadership brief drafted from approved evidence', 'complete'],
    ['Verify', mode === 'code' ? 'Race loop and static checks are running' : 'Citations and recommendation coverage are running', 'running'],
    ['Review', 'Waiting for verified outcome', 'queued'],
  ];

  return (
    <div className="session-overview-canvas">
      <section className="session-canvas-hero">
        <div><span>{t('CURRENT OUTCOME')}</span><h2>{task.title}</h2><p>{task.summary}</p></div>
        <button type="button" onClick={onOpenTask}>{t('Open task canvas')}<ExternalLinkIcon /></button>
      </section>
      <div className="session-overview-grid">
        <section className="session-stage-card">
          <header><span>{t('EXECUTION STAGES')}</span><em>3 / 4</em></header>
          {stages.map(([name, detail, status]) => (
            <div className="session-stage-row" key={name}>
              {status === 'complete' ? <CheckCircledIcon className="complete" /> : status === 'running' ? <ActivityLogIcon className="running" /> : <ClockIcon />}
              <span><b>{t(name)}</b><small>{t(detail)}</small></span><em>{t(status === 'queued' ? 'Queued' : status === 'running' ? 'Running' : 'Completed')}</em>
            </div>
          ))}
        </section>
        <section className="session-run-card">
          <header><span>{t('RUN CONTEXT')}</span><em>{t('Live')}</em></header>
          <dl>
            <div><dt>{t('Environment')}</dt><dd>{mode === 'code' ? 'worktree/agent-fix' : t('Private project scope')}</dd></div>
            <div><dt>{t('Permission')}</dt><dd>{t('Ask for approval')}</dd></div>
            <div><dt>{t('Model')}</dt><dd>{mode === 'code' ? 'GPT-5.5 · High' : 'GPT-5.5 · Medium'}</dd></div>
            <div><dt>{t('Elapsed')}</dt><dd>00:24:18</dd></div>
            <div><dt>{t('Usage')}</dt><dd>{mode === 'code' ? '$1.84' : '$0.92'}</dd></div>
          </dl>
        </section>
      </div>
      <section className="session-deliverables-card">
        <header><span>{t('OUTPUTS & EVIDENCE')}</span><button type="button">{t('View all')}</button></header>
        <div><FileTextIcon /><span><b>{mode === 'code' ? t('Verified code changes') : t('Strategy brief draft')}</b><small>{mode === 'code' ? '4 files · +138 −29' : t('28 citations · Draft')}</small></span><StatusDot status="running" /></div>
        <div><CheckCircledIcon /><span><b>{t('Verification bundle')}</b><small>{mode === 'code' ? '18 tests · 50 race runs · ruff' : t('Source coverage · citation integrity · review checklist')}</small></span><StatusDot status="complete" /></div>
      </section>
    </div>
  );
}

function PlanCanvas({ mode, task, t }) {
  const plan = mode === 'code'
    ? ['Reproduce the shared-runner race', 'Scope the fixture to the active job', 'Add a concurrent regression test', 'Run targeted and static verification']
    : ['Review approved evidence', 'Map evidence to three strategic priorities', 'Draft the leadership brief', 'Validate citations and recommendation coverage'];
  return (
    <section className="session-plan-canvas">
      <header><div><span>{t('APPROVED PLAN')}</span><h2>{task.title}</h2></div><em>{t('Agent can update completed state')}</em></header>
      <div className="session-plan-list">
        {plan.map((step, index) => <div key={step}><span>{index < 2 ? <CheckCircledIcon /> : index === 2 ? <ActivityLogIcon /> : <ClockIcon />}</span><p><b>{index + 1}. {t(step)}</b><small>{index < 2 ? t('Completed with evidence') : index === 2 ? t('In progress now') : t('Runs after the current step')}</small></p><em>{index < 2 ? t('Done') : index === 2 ? t('Active') : t('Queued')}</em></div>)}
      </div>
      <footer><span>{t('Plan changes require a visible version and rationale.')}</span><button type="button">{t('Review plan history')}</button></footer>
    </section>
  );
}

function ChangesCanvas({ onReference, t }) {
  const [expanded, setExpanded] = useState(true);
  const visibleLines = expanded ? diffLines : diffLines.slice(0, 4);
  return (
    <section className="session-changes-canvas">
      <header className="session-canvas-toolbar">
        <div><span>{t('4 files changed')}</span><b>+138</b><em>−29</em></div>
        <span><button type="button" onClick={() => setExpanded((value) => !value)}>{expanded ? t('Collapse all') : t('Expand all')}<ChevronDownIcon className={expanded ? 'expanded' : ''} /></button><button type="button"><CommitIcon />{t('Commit')}</button></span>
      </header>
      <div className="session-file-tabs"><button className="active" type="button">runner.py <b>+8</b><em>−2</em></button><button type="button">test_pipeline.py <b>+42</b><em>−8</em></button><button type="button">shared.py <b>+6</b><em>−4</em></button></div>
      <article className="session-diff-card">
        <header><span><CodeIcon />src/pipeline/runner.py</span><small>{t('Click a line to reference it in the conversation')}</small></header>
        <div className="session-diff-lines">
          {visibleLines.map(([oldLine, newLine, code], index) => {
            const type = code.startsWith('+') ? 'added' : code.startsWith('-') ? 'removed' : '';
            const lineNumber = newLine || oldLine;
            return <button type="button" className={type} key={`${oldLine}-${newLine}-${index}`} onClick={() => onReference(`src/pipeline/runner.py#L${lineNumber}`)} title={t('Add line as context')}><span>{oldLine}</span><span>{newLine}</span><code>{code}</code></button>;
          })}
        </div>
        {!expanded ? <button className="session-show-lines" type="button" onClick={() => setExpanded(true)}>{t('Show 3 more lines')}</button> : null}
      </article>
      <article className="session-diff-card compact"><header><span><CodeIcon />src/tests/test_pipeline.py</span><small>+42 −8</small></header><button className="session-collapsed-file" type="button" onClick={() => onReference('src/tests/test_pipeline.py#L118-L166')}>{t('Concurrent regression coverage')}<span>{t('Add as context')}<ExternalLinkIcon /></span></button></article>
    </section>
  );
}

function TerminalCanvas({ verificationState, onRerun, t }) {
  return (
    <section className="session-terminal-canvas">
      <header className="session-canvas-toolbar"><div><span>{t('TERMINAL')}</span><em>local · worktree/agent-fix</em></div><button type="button" onClick={onRerun}><ReloadIcon />{verificationState === 'running' ? t('Running…') : t('Rerun verification')}</button></header>
      <pre><span>$ pytest src/tests/test_pipeline.py -q</span>{'\n'}<b>..................</b>{'\n'}18 passed in 4.82s{'\n\n'}<span>$ pytest src/tests/test_pipeline.py --count=50</span>{'\n'}50 consecutive runs passed{'\n\n'}<span>$ ruff check src/pipeline src/tests</span>{'\n'}{verificationState === 'running' ? <em>Checking…</em> : <b>All checks passed</b>}</pre>
      <footer><StatusDot status={verificationState} /><span>{verificationState === 'running' ? t('Verification is running in the isolated worktree') : t('Verification evidence attached to this session')}</span></footer>
    </section>
  );
}

function ArtifactCanvas({ onReference, t }) {
  return (
    <section className="session-artifact-canvas">
      <header className="session-canvas-toolbar"><div><span>{t('LEADERSHIP BRIEF')}</span><em>{t('Draft · Autosaved')}</em></div><button type="button">{t('Open editor')}<ExternalLinkIcon /></button></header>
      <article>
        <span>{t('EXECUTIVE BRIEF')}</span><h2>{t('Activation is the highest-leverage product priority')}</h2><p>{t('Customer evidence consistently shows that teams struggle to move from first successful task to a repeatable, reviewable workflow.')}</p>
        <h3>{t('Recommendation')}</h3><p>{t('Prioritize guided activation and evidence-backed templates before expanding the standalone agent surface.')}</p>
        <blockquote>{t('Teams value confidence and reviewability more than another automation entry point.')}<button type="button" onClick={() => onReference('Leadership brief#recommendation')}>{t('Reference section')}</button></blockquote>
      </article>
    </section>
  );
}

function SourcesCanvas({ onReference, t }) {
  const sources = [['Customer interviews — Q3', '12 episodes', 'High'], ['Activation telemetry', '4 dashboards', 'High'], ['Enterprise governance study', '7 documents', 'Medium'], ['Verified market sources', '9 links', 'High']];
  return <section className="session-sources-canvas"><header><div><span>{t('APPROVED SOURCES')}</span><h2>{t('Evidence used in this session')}</h2></div><em>28 {t('sources')}</em></header>{sources.map(([name, meta, confidence]) => <button type="button" key={name} onClick={() => onReference(name)}><ReaderIcon /><span><b>{t(name)}</b><small>{t(meta)}</small></span><em>{t(confidence)}</em></button>)}</section>;
}

function ChecksCanvas({ mode, t }) {
  const checks = mode === 'code'
    ? [['Targeted tests', '18 passed in 4.82s'], ['Race loop', '50 consecutive runs passed'], ['Static analysis', 'ruff check passed']]
    : [['Source coverage', '28 / 28 claims linked'], ['Citation integrity', 'No broken references'], ['Review checklist', '7 / 7 requirements met']];
  return <section className="session-checks-canvas"><header><div><span>{t('VERIFICATION')}</span><h2>{t('Evidence before completion')}</h2></div><em>{t('All required checks')}</em></header>{checks.map(([name, result]) => <div key={name}><CheckCircledIcon /><span><b>{t(name)}</b><small>{t(result)}</small></span><em>{t('Passed')}</em></div>)}</section>;
}

export function ConversationCanvas({ mode, task, activeTab, onTabChange, onReference, onOpenTask, verificationState, onRerun, layout, onLayoutChange }) {
  const { t } = useI18n();
  const tabs = mode === 'code' ? codeTabs : workTabs;
  return (
    <section className="session-canvas-pane" aria-label={t('Work canvas')}>
      <nav className="session-canvas-tabs" aria-label={t('Canvas views')}>
        {tabs.map(([id, label, Icon, count]) => <button className={activeTab === id ? 'active' : ''} type="button" key={id} onClick={() => onTabChange(id)}><Icon />{t(label)}{count ? <em>{count}</em> : null}</button>)}
        <span className="session-canvas-tab-spacer" />
        <button className="session-canvas-layout-button" type="button" onClick={() => onLayoutChange(layout === 'focus' ? 'split' : 'focus')} aria-label={t(layout === 'focus' ? 'Show conversation' : 'Focus canvas')}>{layout === 'focus' ? <ExitFullScreenIcon /> : <EnterFullScreenIcon />}</button>
        <button className="session-canvas-layout-button" type="button" onClick={() => onLayoutChange('thread')} aria-label={t('Close canvas')}><Cross2Icon /></button>
      </nav>
      <div className="session-canvas-content">
        {activeTab === 'overview' ? <OverviewCanvas mode={mode} task={task} onOpenTask={onOpenTask} t={t} /> : null}
        {activeTab === 'plan' ? <PlanCanvas mode={mode} task={task} t={t} /> : null}
        {activeTab === 'changes' ? <ChangesCanvas onReference={onReference} t={t} /> : null}
        {activeTab === 'terminal' ? <TerminalCanvas verificationState={verificationState} onRerun={onRerun} t={t} /> : null}
        {activeTab === 'artifact' ? <ArtifactCanvas onReference={onReference} t={t} /> : null}
        {activeTab === 'sources' ? <SourcesCanvas onReference={onReference} t={t} /> : null}
        {activeTab === 'checks' ? <ChecksCanvas mode={mode} t={t} /> : null}
      </div>
    </section>
  );
}
