import { useState } from 'react';
import {
  ArrowRightIcon,
  CheckCircledIcon,
  ChevronDownIcon,
  ClockIcon,
  CodeIcon,
  CopyIcon,
  DesktopIcon,
  ExternalLinkIcon,
  FileIcon,
  GitHubLogoIcon,
  Link2Icon,
  LockClosedIcon,
  PauseIcon,
  PlayIcon,
  ReaderIcon,
  RocketIcon,
  SewingPinIcon,
} from '@radix-ui/react-icons';

import { codeChanges, workSources } from '../data';

const workSteps = ['Research', 'Analyze', 'Draft', 'Review'];
const codeSteps = ['Inspect', 'Plan', 'Implement', 'Verify'];

function ProgressStrip({ mode, progress }) {
  const steps = mode === 'work' ? workSteps : codeSteps;
  const activeIndex = progress === 100 ? 4 : Math.max(1, Math.ceil(progress / 25));
  return (
    <div className="progress-strip">
      {steps.map((step, index) => (
        <div className={index < activeIndex ? 'complete' : ''} key={step}>
          <span>{index < activeIndex ? <CheckCircledIcon /> : index + 1}</span>
          <small>{step}</small>
        </div>
      ))}
    </div>
  );
}

function WorkArtifact({ onSources }) {
  return (
    <article className="artifact-preview work-artifact">
      <div className="document-toolbar">
        <div><ReaderIcon /><span>Strategy brief · final draft</span></div>
        <button className="icon-button" type="button" aria-label="Copy brief"><CopyIcon /></button>
      </div>
      <div className="document-frame">
        <nav className="document-outline" aria-label="Brief outline">
          <button className="active" type="button">Overview</button>
          <button type="button">Executive summary</button>
          <button type="button">Market context</button>
          <button type="button">Strategic priorities</button>
          <button type="button">Go-to-market plan</button>
          <button type="button">Risks</button>
        </nav>
        <div className="document-sheet">
          <span className="eyebrow">PRODUCT STRATEGY · Q3 2026</span>
          <h2>Focus the roadmap on activation and trusted automation</h2>
          <p className="document-lead">Customer evidence points to one clear opportunity: help teams move from isolated agent experiments to dependable, reviewable work.</p>
          <div className="document-metrics">
            <div><b>18%</b><span>activation upside</span></div>
            <div><b>3.2×</b><span>faster review cycles</span></div>
            <div><b>71%</b><span>request auditability</span></div>
          </div>
          <h3>Three strategic bets</h3>
          <ol>
            <li><b>Mission Control</b><span>Make every running task legible, interruptible, and easy to resume.</span></li>
            <li><b>One task kernel</b><span>Unify Work and Code around context, approvals, memory, and artifacts.</span></li>
            <li><b>Trust by design</b><span>Show source lineage, execution scope, and approval boundaries by default.</span></li>
          </ol>
          <button className="source-link" type="button" onClick={onSources}><Link2Icon /> View 8 cited sources</button>
        </div>
      </div>
    </article>
  );
}

function InsightGrid({ mode, task, onInput, onSources }) {
  const hasApprovedPlan = Array.isArray(task.plan);
  return (
    <div className="insight-grid">
      <article>
        <span className="eyebrow">Progress</span>
        <div className="progress-detail"><b>{task.progress}%</b><div><span>{hasApprovedPlan ? 'Plan approved' : 'Objective understood'}</span><span>{hasApprovedPlan ? 'First step starting' : 'Context analyzed'}</span><span>{hasApprovedPlan ? `${task.plan.length} steps queued` : (mode === 'work' ? 'Brief synthesized' : 'Patch verified')}</span></div></div>
      </article>
      <article>
        <span className="eyebrow">{mode === 'work' ? 'Sources used' : 'Changes'}</span>
        <div className="insight-list">
          <span><ReaderIcon /> {mode === 'work' ? 'MemStack memory' : '4 files modified'}<b>{mode === 'work' ? '12' : '+138'}</b></span>
          <span><FileIcon /> {mode === 'work' ? 'Research documents' : 'Tests added'}<b>{mode === 'work' ? '7' : '3'}</b></span>
          <span><Link2Icon /> {mode === 'work' ? 'Verified web sources' : 'Checks passed'}<b>{mode === 'work' ? '9' : '18'}</b></span>
          <button type="button" onClick={mode === 'work' ? onSources : undefined}>{mode === 'work' ? 'Open sources' : 'Open changes'}</button>
        </div>
      </article>
      <article className={task.status === 'input' ? 'blocker-card active' : 'blocker-card'}>
        <span className="eyebrow">{task.status === 'input' ? 'Blocker · 1' : 'Run status'}</span>
        <p>{task.status === 'input' ? (mode === 'work' ? 'Confirm the strategic priority before the final recommendation.' : 'Approve the fixture boundary before editing shared state.') : 'No blockers. The agent can continue within the current scope.'}</p>
        {task.status === 'input' && <button type="button" onClick={() => onInput(task)}>Provide input</button>}
      </article>
    </div>
  );
}

function ActivePlanArtifact({ mode, task }) {
  return (
    <article className="artifact-preview active-plan-artifact">
      <div className="document-toolbar">
        <div><CheckCircledIcon /><span>Approved plan · {task.plan.length} steps</span></div>
        <span className="plan-authority"><LockClosedIcon /> Limited authority</span>
      </div>
      <div className="active-plan-layout">
        <section className="active-plan-list">
          {task.plan.map((step, index) => (
            <article className={index === 0 ? 'active' : ''} key={step.title}>
              <div>{index === 0 ? <PlayIcon /> : <span>{String(index + 1).padStart(2, '0')}</span>}</div>
              <section><b>{step.title}</b><p>{step.detail}</p><small><FileIcon /> {step.output}</small></section>
              <time>{index === 0 ? 'Starting' : step.duration}</time>
            </article>
          ))}
        </section>
        <aside className="active-plan-sidecar">
          <span className="eyebrow">RUN CONTRACT</span>
          <h3>Executing the plan you approved</h3>
          <p>The agent may act only inside the selected project and will stop before external side effects.</p>
          <dl><div><dt>Mode</dt><dd>{mode === 'work' ? 'Work' : 'Code'}</dd></div><div><dt>Context</dt><dd>{task.context?.length ?? 0} sources</dd></div><div><dt>Next review</dt><dd>After step 1</dd></div></dl>
        </aside>
      </div>
    </article>
  );
}

function CodeArtifact() {
  const [tab, setTab] = useState('Changes');
  return (
    <article className="artifact-preview code-artifact">
      <div className="code-tabs" role="tablist">
        {['Plan', 'Changes', 'Terminal', 'Preview'].map((name) => (
          <button className={tab === name ? 'active' : ''} type="button" key={name} onClick={() => setTab(name)}>{name}</button>
        ))}
      </div>
      {tab === 'Changes' && (
        <div className="changes-view">
          <div className="changes-summary"><GitHubLogoIcon /><b>4 files changed</b><span className="additions">+138</span><span className="deletions">−29</span></div>
          {codeChanges.map(([file, add, remove]) => (
            <div className="file-row" key={file}><FileIcon /><span>{file}</span><em>{add}</em><small>{remove}</small></div>
          ))}
          <pre><code><span>@@ async def run_pipeline(job):</span>{'\n'}+ async with isolated_fixture(job.id):{'\n'}+     await runner.execute(job){'\n'}+     await runner.wait_until_idle(){'\n'}{'\n'}- await shared_runner.execute(job)</code></pre>
        </div>
      )}
      {tab === 'Plan' && <div className="plain-tab"><h3>Implementation plan</h3><ol><li>Reproduce the fixture race.</li><li>Scope state to the current job.</li><li>Add a concurrent regression test.</li><li>Run the pipeline test matrix.</li></ol></div>}
      {tab === 'Terminal' && <pre className="terminal"><code>$ pytest src/tests/test_pipeline.py -q{'\n'}18 passed in 4.82s{'\n'}$ ruff check src/pipeline src/tests{'\n'}All checks passed.</code></pre>}
      {tab === 'Preview' && <div className="plain-tab"><CheckCircledIcon /><h3>Verification passed</h3><p>The isolated fixture removes the race in 50 consecutive runs. No public API changed.</p></div>}
    </article>
  );
}

export function TaskDetail({ mode, task, paused, onPause, onInput, onSources, onToast }) {
  const [message, setMessage] = useState('');
  const isReady = task.status === 'ready';
  const isInput = task.status === 'input';
  const hasApprovedPlan = Array.isArray(task.plan);
  const runLabel = paused ? 'Paused' : task.phase;

  function sendMessage() {
    if (!message.trim()) return;
    onToast(`Steering note sent to ${task.title}`);
    setMessage('');
  }

  return (
    <section className="task-detail">
      <header className="detail-topbar">
        <div className="breadcrumb"><span>{mode === 'work' ? 'Product Strategy' : 'Desktop Client'}</span><ArrowRightIcon /><b>{task.title}</b></div>
        <div className="run-controls">
          <span><LockClosedIcon /> Private</span>
          <span><ClockIcon /> 00:24:18</span>
          <span className="usage">$1.84</span>
          <button className="icon-button" type="button" onClick={onPause} aria-label={paused ? 'Resume task' : 'Pause task'}>{paused ? <PlayIcon /> : <PauseIcon />}</button>
        </div>
      </header>

      <div className="detail-content">
        <section className="task-summary-card">
          <div className="task-title-row">
            <div className={`task-icon ${mode}`} aria-hidden="true">{mode === 'work' ? <RocketIcon /> : <CodeIcon />}</div>
            <div><span className="eyebrow">{mode === 'work' ? 'RESEARCH & WRITING' : 'CODE SESSION'}</span><h1>{task.title}</h1><p>{task.summary}</p></div>
            <div className="progress-number"><b>{task.progress}%</b><span>{runLabel}</span></div>
          </div>
          <ProgressStrip mode={mode} progress={task.progress} />
          <div className="run-facts">
            <span><SewingPinIcon /> {mode === 'work' ? '8 trusted sources' : 'worktree/agent-fix'}</span>
            <span><DesktopIcon /> {mode === 'work' ? 'Cloud workspace' : 'Local sandbox'}</span>
            <button type="button">{mode === 'work' ? 'Sources' : 'Environment'} <ChevronDownIcon /></button>
          </div>
          {isInput && <div className="input-banner"><span><b>Your input is needed</b>Review the proposed boundary before the agent continues.</span><button type="button" onClick={() => onInput(task)}>Review request</button></div>}
        </section>

        <InsightGrid mode={mode} task={task} onInput={onInput} onSources={onSources} />

        <div className="artifact-heading"><div><span className="eyebrow">{hasApprovedPlan ? 'EXECUTION PLAN' : 'LATEST ARTIFACT'}</span><h2>{hasApprovedPlan ? 'Approved plan now running' : (mode === 'work' ? 'Leadership-ready strategy brief' : 'Verified code changes')}</h2></div><span className="saved-state"><CheckCircledIcon /> {hasApprovedPlan ? 'Approved' : 'Saved'}</span></div>
        {hasApprovedPlan ? <ActivePlanArtifact mode={mode} task={task} /> : (mode === 'work' ? <WorkArtifact onSources={onSources} /> : <CodeArtifact />)}
      </div>

      <footer className="action-dock">
        <div className="action-buttons">
          <button className="primary" type="button" onClick={() => onToast(hasApprovedPlan ? 'Opening live run timeline' : (isReady ? 'Artifact approved and task completed' : 'Review opened'))}>{hasApprovedPlan ? 'Open live run' : (mode === 'work' ? 'Review brief' : (isReady ? 'Approve changes' : 'Review changes'))}</button>
          <button type="button" onClick={() => setMessage(hasApprovedPlan ? 'Adjust the approved plan to ' : 'Please revise the executive summary to emphasize ')}>{hasApprovedPlan ? 'Adjust plan' : 'Ask for changes'}</button>
          <button type="button" onClick={mode === 'work' ? onSources : () => onToast('Opening changes in editor')}>{mode === 'work' ? 'Open context' : 'Open environment'} <ExternalLinkIcon /></button>
        </div>
        <div className="steer-composer">
          <textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder={`Steer ${task.title}…`} aria-label="Steer task" />
          <div>
            <span>{mode === 'work' ? 'Work' : 'Code'} · Agent</span>
            <button className="send-button" type="button" onClick={sendMessage} aria-label="Send steering note"><ArrowRightIcon /></button>
          </div>
        </div>
      </footer>
    </section>
  );
}

export function SourcesDialog({ onClose }) {
  return (
    <div className="source-list">
      <p>Every claim in the brief is linked to a retrievable source and the exact agent observation that used it.</p>
      {workSources.map(([title, detail, state]) => (
        <button type="button" key={title}><ReaderIcon /><span><b>{title}</b><small>{detail} · {state}</small></span><ExternalLinkIcon /></button>
      ))}
      <div className="dialog-actions"><button type="button" onClick={onClose}>Close</button><button className="primary" type="button">Open source workspace</button></div>
    </div>
  );
}
