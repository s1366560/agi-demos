import { useEffect, useRef, useState } from 'react';
import {
  ActivityLogIcon,
  ArrowRightIcon,
  CheckCircledIcon,
  ChevronDownIcon,
  ClockIcon,
  CodeIcon,
  DesktopIcon,
  DotsHorizontalIcon,
  FileTextIcon,
  Link2Icon,
  LockClosedIcon,
  MixerHorizontalIcon,
  PauseIcon,
  PersonIcon,
  ReaderIcon,
  StopIcon,
  TargetIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

import { ConversationCanvas } from './ConversationCanvas';
import './ConversationDetail.css';

function StatusBadge({ status, t }) {
  const label = status === 'input' ? t('Needs input') : status === 'ready' ? t('Ready to review') : t('Running');
  return <span className={`session-status-badge ${status}`}><i />{label}</span>;
}

function StageStrip({ status, t }) {
  const stages = [
    ['Understand', 'complete'],
    ['Implement', 'complete'],
    ['Verify', status === 'ready' ? 'complete' : status === 'input' ? 'paused' : 'active'],
    ['Review', status === 'ready' ? 'active' : 'queued'],
  ];
  return <div className="session-stage-strip" aria-label={t('Session progress')}>{stages.map(([name, state], index) => <div className={state} key={name}>{state === 'complete' ? <CheckCircledIcon /> : state === 'active' ? <ActivityLogIcon /> : <ClockIcon />}<span><small>0{index + 1}</small><b>{t(name)}</b></span></div>)}</div>;
}

function ToolActivity({ mode, expanded, onToggle, t }) {
  const tools = mode === 'code'
    ? [['Search files', 'src/pipeline · shared_runner', '4 results'], ['Read code', 'runner.py · shared.py · test_pipeline.py', '3 files'], ['Run tests', 'pytest --count=50', '1 failure reproduced'], ['Apply patch', 'Fixture ownership scoped to job ID', '+138 −29']]
    : [['Search memory', 'Activation and trust signals', '12 episodes'], ['Read sources', 'Interviews · metrics · market evidence', '28 sources'], ['Draft artifact', 'Leadership brief', '1 document'], ['Validate claims', 'Citation and coverage checks', '28 / 28']];
  return (
    <article className="session-tool-group">
      <button type="button" onClick={onToggle} aria-expanded={expanded}><span><ActivityLogIcon /></span><div><b>{t(mode === 'code' ? 'Inspected, reproduced, and patched the race' : 'Synthesized the approved evidence')}</b><small>{tools.length} {t('tool calls')} · {mode === 'code' ? '42s' : '51s'}</small></div><em>{t('Completed')}</em><ChevronDownIcon className={expanded ? 'expanded' : ''} /></button>
      {expanded ? <div className="session-tool-rows"><div className="session-subagent-row"><CodeIcon /><span><b>{t('Repository scout')}</b><small>{t('Mapped the runner lifecycle in an isolated context')}</small></span><em>{t('Subagent · 11s')}</em></div>{tools.map(([name, detail, result]) => <div key={name}><CheckCircledIcon /><span><b>{t(name)}</b><small>{t(detail)}</small></span><em>{t(result)}</em></div>)}</div> : null}
    </article>
  );
}

function ThreadMessage({ role, mode, time, children, t }) {
  const isUser = role === 'user';
  return <article className={`session-thread-message ${role}`}><div className="session-thread-avatar">{isUser ? <img src="/avatar-alex.png" alt="Alex Chen" /> : mode === 'code' ? <CodeIcon /> : <ReaderIcon />}</div><div><header><b>{isUser ? 'Alex Chen' : mode === 'code' ? 'Code Agent' : 'Research Agent'}</b>{!isUser ? <em>{t('Workspace agent')}</em> : null}<time>{time}</time><button type="button" aria-label={t('Message actions')}><DotsHorizontalIcon /></button></header>{children}</div></article>;
}

function SessionContextRail({ mode, task, onOpenCanvas, onReview, t }) {
  const workItems = mode === 'code'
    ? [['plan', 'Plan', TargetIcon], ['changes', 'Changes', CodeIcon], ['checks', 'Checks', CheckCircledIcon]]
    : [['plan', 'Plan', TargetIcon], ['artifact', 'Artifact', FileTextIcon], ['checks', 'Verify', CheckCircledIcon]];

  return (
    <aside className="session-context-rail" aria-label={t('Session inspector')}>
      {task.status === 'input' ? (
        <section className="session-attention-card">
          <span><StopIcon />{t('Needs your attention')}</span>
          <strong>{t(mode === 'code' ? 'Approve the fixture ownership boundary' : 'Choose the strategic priority')}</strong>
          <p>{t('Review before the agent continues.')}</p>
          <button type="button" onClick={onReview}>{t('Review request')}<ArrowRightIcon /></button>
        </section>
      ) : null}

      <section className="session-context-section session-run-snapshot">
        <header><span>{t('Run snapshot')}</span><em>{t(task.status === 'ready' ? 'Ready to review' : task.status === 'input' ? 'Waiting for approval' : 'Running')}</em></header>
        <div className="session-stage-progress"><span><i style={{ width: task.status === 'ready' ? '100%' : '75%' }} /></span><b>{task.status === 'ready' ? '4 / 4' : '3 / 4'}</b></div>
        <dl>
          <div><dt>{t('Current stage')}</dt><dd>{t(task.status === 'ready' ? 'Review' : 'Verify')}</dd></div>
          <div><dt>{t('Environment')}</dt><dd>{mode === 'code' ? 'worktree/agent-fix' : t('Private workspace')}</dd></div>
          <div><dt>{t('Elapsed')}</dt><dd>00:24:18</dd></div>
          <div><dt>{t('Permission')}</dt><dd>{t('Ask for approval')}</dd></div>
        </dl>
      </section>

      <section className="session-context-section session-work-surfaces">
        <header><span>{t('Work surfaces')}</span><small>{t('Open only when you need to inspect or act.')}</small></header>
        <div>
          {workItems.map(([id, label, Icon]) => (
            <button type="button" key={id} onClick={() => onOpenCanvas(id)}>
              <Icon /><span><b>{t(label)}</b><small>{id === 'plan' ? t('Approved scope and progress') : id === 'checks' ? t('Verification evidence') : t(mode === 'code' ? 'Review changed files' : 'Review the current artifact')}</small></span><ArrowRightIcon />
            </button>
          ))}
        </div>
      </section>

      <section className="session-context-section session-evidence-summary">
        <header><span>{t('Latest evidence')}</span></header>
        <div><CheckCircledIcon /><span><b>{mode === 'code' ? '18 tests · 50 race runs' : '28 linked claims'}</b><small>{t(mode === 'code' ? 'Targeted and concurrent verification' : 'Citation and source coverage')}</small></span></div>
      </section>
    </aside>
  );
}

export function ConversationDetail({ mode, task, workspace, onOpenTask, onInput, onToast }) {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState(task.status === 'input' ? 'plan' : mode === 'code' ? 'changes' : 'artifact');
  const [activityExpanded, setActivityExpanded] = useState(false);
  const [draft, setDraft] = useState('');
  const [contextRefs, setContextRefs] = useState([]);
  const [sentMessages, setSentMessages] = useState([]);
  const [sending, setSending] = useState(false);
  const [deliveryMode, setDeliveryMode] = useState('steer');
  const [canvasLayout, setCanvasLayout] = useState('thread');
  const [verificationState, setVerificationState] = useState('complete');
  const threadRef = useRef(null);

  useEffect(() => {
    if (!sending) return undefined;
    const timer = window.setTimeout(() => {
      setSentMessages((current) => [...current, { id: Date.now(), role: 'assistant', content: t('I added that direction to the active run and linked the referenced evidence.') }]);
      setSending(false);
      onToast(t('Message sent to conversation'));
    }, 500);
    return () => window.clearTimeout(timer);
  }, [sending, onToast, t]);

  useEffect(() => {
    setActiveTab(task.status === 'input' ? 'plan' : mode === 'code' ? 'changes' : 'artifact');
    setCanvasLayout('thread');
  }, [mode, task.id, task.status]);

  function addReference(reference) {
    setContextRefs((current) => current.includes(reference) ? current : [...current, reference]);
    onToast(t('Added to conversation context'));
  }

  function sendMessage() {
    const content = draft.trim();
    if (!content || sending) return;
    setSentMessages((current) => [...current, { id: Date.now(), role: 'user', content, refs: contextRefs }]);
    setDraft('');
    setContextRefs([]);
    setSending(true);
    window.setTimeout(() => { if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight; }, 40);
  }

  function rerunVerification() {
    setVerificationState('running');
    window.setTimeout(() => { setVerificationState('complete'); onToast(t('Verification passed')); }, 850);
  }

  function openCanvas(tab) {
    setActiveTab(tab);
    setCanvasLayout('split');
  }

  return (
    <main className="session-detail">
      <header className="session-header">
        <div className="session-heading"><span>{workspace.name} <ArrowRightIcon /> {t('Conversation')}</span><div><h1>{task.title}</h1><StatusBadge status={task.status} t={t} /></div></div>
        <StageStrip status={task.status} t={t} />
        <div className="session-header-actions"><span><DesktopIcon />{mode === 'code' ? 'worktree/agent-fix' : t('Private workspace')}</span><span><ClockIcon />00:24:18</span><button type="button"><PauseIcon />{t('Pause')}</button><button className="primary" type="button" onClick={onOpenTask}><FileTextIcon />{t('Open task')}</button><button className="icon-button" type="button" aria-label={t('Conversation actions')}><DotsHorizontalIcon /></button></div>
      </header>

      {task.status === 'input' && canvasLayout !== 'thread' ? <section className="session-hitl-banner"><StopIcon /><div><small>{t('HUMAN DECISION')}</small><b>{t(mode === 'code' ? 'Approve the fixture ownership boundary' : 'Choose the strategic priority')}</b><p>{t('The agent is paused before changing the approved scope.')}</p></div><button type="button" onClick={() => onInput(task)}>{t('Review request')}</button></section> : null}

      <div className={`session-workspace layout-${canvasLayout}`}>
        <section className="session-thread-pane">
          <header><div><span>{t('SESSION LOG')}</span><em>{t('Live')}</em></div><span><LockClosedIcon />{t('Private')}<PersonIcon />{mode === 'code' ? '2' : '3'}<button type="button" onClick={() => openCanvas(activeTab)}><ReaderIcon />{t('Open canvas')}</button></span></header>
          <div className="session-thread" ref={threadRef} aria-label={t('Conversation messages')}>
            <div className="session-thread-day"><span>{t('Today')}</span></div>
            <section className="session-live-summary">
              <div><span><ActivityLogIcon /></span><p><small>{t('CURRENT ACTIVITY')}</small><b>{t(mode === 'code' ? 'Verifying the isolated fix' : 'Validating the leadership brief')}</b></p><em>3 / 4</em></div>
              <dl><div><dt>{t('Last checkpoint')}</dt><dd>{t(mode === 'code' ? 'Patch applied' : 'Draft complete')}</dd></div><div><dt>{t('Evidence')}</dt><dd>{mode === 'code' ? '18 tests · 50 race runs' : '28 linked claims'}</dd></div></dl>
            </section>
            <ThreadMessage role="user" mode={mode} time="10:14" t={t}><p>{mode === 'code' ? 'Please reproduce the flaky pipeline test, isolate the race without changing the public API, and leave verification evidence in this session.' : 'Use the approved sources to prepare a leadership-ready brief. Keep every recommendation linked to customer evidence.'}</p></ThreadMessage>
            <ThreadMessage role="assistant" mode={mode} time="10:14" t={t}><p>{mode === 'code' ? 'I’ll inspect the shared runner, reproduce the race in an isolated worktree, then verify the smallest safe fix.' : 'I’ll synthesize the approved project evidence into a concise brief and keep each recommendation traceable.'}</p><ul>{(mode === 'code' ? ['Inspect fixture ownership', 'Reproduce concurrently', 'Patch and verify'] : ['Review evidence', 'Draft priorities', 'Validate citations']).map((item) => <li key={item}>{t(item)}</li>)}</ul></ThreadMessage>
            <div className="session-system-event"><DesktopIcon /><span><b>{t(mode === 'code' ? 'Isolated worktree ready' : 'Approved project context attached')}</b><small>{mode === 'code' ? 'worktree/agent-fix · Local sandbox' : '12 memories · 28 sources'}</small></span><time>10:15</time></div>
            <ToolActivity mode={mode} expanded={activityExpanded} onToggle={() => setActivityExpanded((value) => !value)} t={t} />
            <ThreadMessage role="assistant" mode={mode} time="10:18" t={t}><p>{mode === 'code' ? 'I found the race: shared mutable state kept the previous job’s runner alive. I scoped the fixture to the job ID and added concurrent regression coverage.' : 'The evidence converges on one priority: guided activation and reviewable templates create more value than another standalone agent entry point.'}</p><button className="session-inline-action" type="button" onClick={() => openCanvas(mode === 'code' ? 'changes' : 'artifact')}>{mode === 'code' ? <CodeIcon /> : <FileTextIcon />}{t(mode === 'code' ? 'Review 4 changed files' : 'Review leadership brief')}<ArrowRightIcon /></button></ThreadMessage>
            <div className="session-progress-event"><span><ActivityLogIcon /></span><div><b>{t(mode === 'code' ? 'Verification is running' : 'Artifact verification is running')}</b><small>{mode === 'code' ? '18 tests passed · 50 race runs passed · static checks' : t('28 claims linked · citation integrity · review checklist')}</small></div><em>3 / 4</em></div>
            {sentMessages.map((message) => <ThreadMessage key={message.id} role={message.role} mode={mode} time={t('Now')} t={t}>{message.refs?.length ? <div className="session-message-refs">{message.refs.map((ref) => <span key={ref}><Link2Icon />{ref}</span>)}</div> : null}<p>{message.content}</p></ThreadMessage>)}
            {sending ? <div className="session-agent-typing"><span /><span /><span />{t('Agent is responding')}</div> : null}
          </div>
          <footer className="session-composer">
            {contextRefs.length ? <div className="session-context-chips">{contextRefs.map((ref) => <button type="button" key={ref} onClick={() => setContextRefs((current) => current.filter((item) => item !== ref))}><Link2Icon />{ref}<span>×</span></button>)}</div> : null}
            <textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') sendMessage(); }} placeholder={t('Steer this session…')} aria-label={t('Message conversation')} />
            <div><span><button type="button"><Link2Icon />{t('Attach')}</button><button type="button"><MixerHorizontalIcon />{t('Context')}</button></span><div className="session-delivery-mode" aria-label={t('Message delivery')}><button className={deliveryMode === 'steer' ? 'active' : ''} type="button" onClick={() => setDeliveryMode('steer')}>{t('Steer now')}</button><button className={deliveryMode === 'queue' ? 'active' : ''} type="button" onClick={() => setDeliveryMode('queue')}>{t('Queue next')}</button></div><button className="send-button" type="button" disabled={!draft.trim() || sending} onClick={sendMessage} aria-label={t('Send message')}><ArrowRightIcon /></button></div>
          </footer>
        </section>

        {canvasLayout === 'thread' ? (
          <SessionContextRail mode={mode} task={task} onOpenCanvas={openCanvas} onReview={() => onInput(task)} t={t} />
        ) : (
          <ConversationCanvas mode={mode} task={task} activeTab={activeTab} onTabChange={setActiveTab} onReference={addReference} onOpenTask={onOpenTask} verificationState={verificationState} onRerun={rerunVerification} layout={canvasLayout} onLayoutChange={setCanvasLayout} />
        )}
      </div>
    </main>
  );
}
