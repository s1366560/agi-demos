import { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CheckCircledIcon,
  ChevronDownIcon,
  CodeIcon,
  Cross2Icon,
  FileTextIcon,
  LightningBoltIcon,
  LockClosedIcon,
  MagicWandIcon,
  MixerHorizontalIcon,
  Pencil2Icon,
  PlusIcon,
  ReaderIcon,
  RocketIcon,
  SewingPinIcon,
} from '@radix-ui/react-icons';

const WORK_PLAN = [
  {
    title: 'Collect the strongest customer signals',
    detail: 'Review 12 interviews, the retention dashboard, and recent escalation notes.',
    output: 'Evidence map',
    duration: '4 min',
  },
  {
    title: 'Identify retention opportunities',
    detail: 'Cluster recurring friction, estimate reach, and flag contradictory evidence.',
    output: 'Prioritized findings',
    duration: '6 min',
  },
  {
    title: 'Design three experiment candidates',
    detail: 'Define audience, intervention, success metric, guardrail, and required effort.',
    output: 'Experiment cards',
    duration: '8 min',
  },
  {
    title: 'Draft the leadership brief',
    detail: 'Synthesize the recommendation with source-linked claims and open questions.',
    output: 'Reviewable brief',
    duration: '5 min',
  },
];

const CODE_PLAN = [
  {
    title: 'Inspect the current execution boundary',
    detail: 'Trace task state, event persistence, recovery hooks, and desktop command callers.',
    output: 'Impact map',
    duration: '5 min',
  },
  {
    title: 'Lock behavior with regression tests',
    detail: 'Cover paused, resumed, recovered, and duplicate-command scenarios.',
    output: 'Failing tests',
    duration: '7 min',
  },
  {
    title: 'Implement resumable execution',
    detail: 'Add the smallest state transition and checkpoint changes inside a worktree.',
    output: 'Code changes',
    duration: '12 min',
  },
  {
    title: 'Verify and prepare review',
    detail: 'Run targeted tests, lint changed files, and summarize the diff and residual risk.',
    output: 'Verified patch',
    duration: '6 min',
  },
];

const CONTEXT_OPTIONS = [
  ['Company memory', 'Shared decisions and durable project context', ReaderIcon],
  ['Project files', 'Documents and artifacts from this project', FileTextIcon],
  ['Web research', 'Verified external sources with citations', SewingPinIcon],
];

const MODE_DEFAULTS = {
  work: {
    title: 'Q4 customer retention experiments',
    objective: 'Create a leadership-ready brief that recommends three measurable retention experiments for Q4, grounded in customer interviews and product data.',
  },
  code: {
    title: 'Add resumable task execution',
    objective: 'Implement resumable task execution in the desktop client, including regression tests and a reviewable change summary.',
  },
};

function FlowStepper({ stage }) {
  const steps = [
    ['define', 'Describe task'],
    ['generating', 'Agent plans'],
    ['review', 'Review plan'],
  ];
  const activeIndex = Math.max(0, steps.findIndex(([key]) => key === stage));
  return (
    <div className="task-flow-stepper" aria-label="New task progress">
      {steps.map(([key, label], index) => (
        <div className={index <= activeIndex ? 'active' : ''} key={key}>
          <span>{index < activeIndex ? <CheckCircledIcon /> : index + 1}</span>
          <b>{label}</b>
        </div>
      ))}
    </div>
  );
}

function ModeCard({ active, icon: Icon, label, description, onClick }) {
  return (
    <button className={`task-mode-card ${active ? 'active' : ''}`} type="button" onClick={onClick}>
      <span><Icon /></span>
      <div><b>{label}</b><small>{description}</small></div>
      {active ? <CheckCircledIcon /> : null}
    </button>
  );
}

function DefineTask({ draft, onChange, onGenerate }) {
  const toggleContext = (label) => {
    const next = draft.context.includes(label)
      ? draft.context.filter((item) => item !== label)
      : [...draft.context, label];
    onChange({ ...draft, context: next });
  };
  const switchMode = (nextMode) => {
    const currentDefaults = MODE_DEFAULTS[draft.mode];
    const nextDefaults = MODE_DEFAULTS[nextMode];
    const usesDefaultBrief = draft.title === currentDefaults.title && draft.objective === currentDefaults.objective;
    onChange({
      ...draft,
      mode: nextMode,
      title: usesDefaultBrief ? nextDefaults.title : draft.title,
      objective: usesDefaultBrief ? nextDefaults.objective : draft.objective,
    });
  };

  return (
    <div className="task-flow-stage define-stage">
      <section className="task-flow-primary">
        <div className="stage-heading">
          <span className="eyebrow">NEW AGENT TASK</span>
          <h2>What should the agent accomplish?</h2>
          <p>Describe the outcome. The agent will inspect the available context and propose a plan before any work starts.</p>
        </div>

        <label className="task-field">
          <span>Task title</span>
          <input value={draft.title} onChange={(event) => onChange({ ...draft, title: event.target.value })} />
        </label>
        <label className="task-field objective-field">
          <span>Desired outcome</span>
          <textarea value={draft.objective} onChange={(event) => onChange({ ...draft, objective: event.target.value })} />
          <small>Include the audience, decision, or deliverable that defines “done.”</small>
        </label>

        <div className="task-field">
          <span>How should the agent work?</span>
          <div className="task-mode-grid">
            <ModeCard
              active={draft.mode === 'work'}
              icon={MixerHorizontalIcon}
              label="Work"
              description="Research, analysis, documents, and business artifacts"
              onClick={() => switchMode('work')}
            />
            <ModeCard
              active={draft.mode === 'code'}
              icon={CodeIcon}
              label="Code"
              description="Repository changes, tests, terminal, and verified patches"
              onClick={() => switchMode('code')}
            />
          </div>
        </div>
      </section>

      <aside className="task-flow-context">
        <div className="stage-heading compact">
          <span className="eyebrow">CONTEXT & BOUNDARIES</span>
          <h3>Give the agent a safe starting point</h3>
        </div>
        <label className="task-field">
          <span>Project</span>
          <button className="select-like" type="button">{draft.mode === 'work' ? 'Product Strategy' : 'Desktop Client'} <ChevronDownIcon /></button>
        </label>
        <div className="task-field">
          <span>Available context</span>
          <div className="context-option-list">
            {CONTEXT_OPTIONS.map(([label, description, Icon]) => {
              const active = draft.context.includes(label);
              return (
                <button className={active ? 'active' : ''} type="button" key={label} onClick={() => toggleContext(label)}>
                  <Icon /><span><b>{label}</b><small>{description}</small></span>{active ? <CheckCircledIcon /> : null}
                </button>
              );
            })}
          </div>
        </div>
        <div className="guardrail-note"><LockClosedIcon /><span><b>Plan-first protection</b>The agent cannot run tools or modify files until you approve its plan.</span></div>
      </aside>

      <footer className="task-flow-footer">
        <span><MagicWandIcon /> The agent will generate a reviewable plan from this brief.</span>
        <button className="primary flow-primary-action" type="button" onClick={onGenerate} disabled={!draft.title.trim() || !draft.objective.trim()}>
          Generate plan <ArrowRightIcon />
        </button>
      </footer>
    </div>
  );
}

function GeneratingPlan({ draft }) {
  return (
    <div className="task-flow-stage generating-stage">
      <section className="generating-card">
        <div className={`generating-icon ${draft.mode}`}><MagicWandIcon /></div>
        <span className="eyebrow">AGENT IS PLANNING</span>
        <h2>Building a plan for “{draft.title}”</h2>
        <p>The agent is reading only the context you selected. No tools have run and no files have changed.</p>
        <div className="planning-progress"><i /></div>
        <div className="planning-checks">
          <div className="complete"><CheckCircledIcon /><span><b>Understand the outcome</b><small>Definition of done and expected artifact captured</small></span></div>
          <div className="complete"><CheckCircledIcon /><span><b>Inspect available context</b><small>{draft.context.length} approved context sources mapped</small></span></div>
          <div className="active"><LightningBoltIcon /><span><b>Choose the safest execution path</b><small>Sequencing work, reviews, and verification</small></span></div>
          <div><RocketIcon /><span><b>Prepare the review packet</b><small>Estimating time, cost, and approval boundaries</small></span></div>
        </div>
      </section>
      <aside className="planning-sidecar">
        <span className="eyebrow">TASK BRIEF</span>
        <h3>{draft.title}</h3>
        <p>{draft.objective}</p>
        <dl><div><dt>Mode</dt><dd>{draft.mode === 'work' ? 'Work' : 'Code'}</dd></div><div><dt>Project</dt><dd>{draft.mode === 'work' ? 'Product Strategy' : 'Desktop Client'}</dd></div><div><dt>Authority</dt><dd>Plan only</dd></div></dl>
      </aside>
    </div>
  );
}

function PlanStep({ step, index, enabled, editing, onToggle, onEdit, onSave, onCancel }) {
  const [editTitle, setEditTitle] = useState(step.title);
  const [editDetail, setEditDetail] = useState(step.detail);
  if (editing) {
    return (
      <article className="generated-plan-step editing">
        <div className="plan-step-number">{String(index + 1).padStart(2, '0')}</div>
        <div className="plan-step-editor">
          <input aria-label="Plan step title" value={editTitle} onChange={(event) => setEditTitle(event.target.value)} />
          <textarea aria-label="Plan step detail" value={editDetail} onChange={(event) => setEditDetail(event.target.value)} />
          <div><button type="button" onClick={onCancel}>Cancel</button><button className="primary" type="button" onClick={() => onSave({ ...step, title: editTitle, detail: editDetail })}>Save step</button></div>
        </div>
      </article>
    );
  }
  return (
    <article className={`generated-plan-step ${enabled ? '' : 'disabled'}`}>
      <button className="plan-step-toggle" type="button" aria-label={`${enabled ? 'Disable' : 'Enable'} ${step.title}`} onClick={onToggle}>
        {enabled ? <CheckCircledIcon /> : <span />}
      </button>
      <div className="plan-step-number">{String(index + 1).padStart(2, '0')}</div>
      <div className="plan-step-copy"><b>{step.title}</b><p>{step.detail}</p><span><FileTextIcon /> {step.output}</span></div>
      <time>{step.duration}</time>
      <button className="icon-button" type="button" aria-label={`Edit ${step.title}`} onClick={onEdit}><Pencil2Icon /></button>
    </article>
  );
}

function ReviewPlan({ draft, plan, enabledSteps, onBack, onToggleStep, onAddStep, onUpdateStep, onRevise, onApprove }) {
  const [editingIndex, setEditingIndex] = useState(null);
  const enabledCount = enabledSteps.filter(Boolean).length;
  const totalMinutes = plan.reduce((total, step, index) => total + (enabledSteps[index] ? Number.parseInt(step.duration, 10) : 0), 0);
  return (
    <div className="task-flow-stage review-plan-stage">
      <section className="plan-review-main">
        <div className="stage-heading plan-review-heading">
          <div><span className="eyebrow">HUMAN REVIEW REQUIRED</span><h2>Review the agent’s plan</h2><p>Change the sequence or remove a step before granting execution authority.</p></div>
          <span className="plan-status"><CheckCircledIcon /> Plan ready</span>
        </div>
        <div className="plan-objective"><div className={`task-icon ${draft.mode}`}>{draft.mode === 'work' ? <RocketIcon /> : <CodeIcon />}</div><span><small>{draft.mode === 'work' ? 'WORK TASK' : 'CODE TASK'}</small><b>{draft.title}</b><p>{draft.objective}</p></span></div>
        <div className="generated-plan-list">
          {plan.map((step, index) => (
            <PlanStep
              key={`${index}-${step.title}`}
              step={step}
              index={index}
              enabled={enabledSteps[index]}
              editing={editingIndex === index}
              onToggle={() => onToggleStep(index)}
              onEdit={() => setEditingIndex(index)}
              onCancel={() => setEditingIndex(null)}
              onSave={(updatedStep) => { onUpdateStep(index, updatedStep); setEditingIndex(null); }}
            />
          ))}
          <button className="add-plan-step" type="button" onClick={onAddStep}><PlusIcon /> Add a step</button>
        </div>
      </section>

      <aside className="plan-review-sidecar">
        <span className="eyebrow">RUN PREVIEW</span>
        <div className="run-preview-stats"><div><small>Estimated time</small><b>{totalMinutes} min</b></div><div><small>Estimated usage</small><b>{draft.mode === 'work' ? '$1.20–1.80' : '$0.80–1.40'}</b></div></div>
        <section><h3>Execution boundaries</h3><ul><li><CheckCircledIcon />Use only selected project context</li><li><CheckCircledIcon />Ask before external side effects</li><li><CheckCircledIcon />Stop if evidence conflicts</li><li><CheckCircledIcon />Return one reviewable artifact</li></ul></section>
        <section><h3>Context the agent will use</h3><div className="review-context-chips">{draft.context.map((item) => <span key={item}><ReaderIcon />{item}</span>)}</div></section>
        <div className="approval-summary"><LockClosedIcon /><span><b>You are granting limited authority</b>Approval starts {enabledCount} plan steps. You can pause or steer the agent at any time.</span></div>
      </aside>

      <footer className="task-flow-footer plan-review-actions">
        <button type="button" onClick={onBack}><ArrowLeftIcon /> Edit brief</button>
        <span>{enabledCount} of {plan.length} steps selected</span>
        <button type="button" onClick={onRevise}>Ask agent to revise</button>
        <button className="primary flow-primary-action" type="button" onClick={onApprove}>Approve & start task <ArrowRightIcon /></button>
      </footer>
    </div>
  );
}

export function NewTaskFlow({ initialMode, onClose, onCreate }) {
  const [stage, setStage] = useState('define');
  const [draft, setDraft] = useState(() => ({
    mode: initialMode,
    title: MODE_DEFAULTS[initialMode].title,
    objective: MODE_DEFAULTS[initialMode].objective,
    context: ['Company memory', 'Project files'],
  }));
  const [plan, setPlan] = useState(() => initialMode === 'work' ? WORK_PLAN : CODE_PLAN);
  const [enabledSteps, setEnabledSteps] = useState([true, true, true, true]);
  const activePlan = useMemo(() => draft.mode === 'work' ? WORK_PLAN : CODE_PLAN, [draft.mode]);

  useEffect(() => {
    if (stage !== 'generating') return undefined;
    const timer = window.setTimeout(() => {
      setPlan(activePlan);
      setEnabledSteps(activePlan.map(() => true));
      setStage('review');
    }, 2200);
    return () => window.clearTimeout(timer);
  }, [activePlan, stage]);

  const approvePlan = () => {
    const approvedPlan = plan.filter((_, index) => enabledSteps[index]);
    onCreate({ ...draft, plan: approvedPlan });
  };

  const addStep = () => {
    setPlan((current) => [...current, { title: 'Final human checkpoint', detail: 'Present the result, sources, and unresolved questions before completion.', output: 'Review packet', duration: '3 min' }]);
    setEnabledSteps((current) => [...current, true]);
  };

  return (
    <div className="new-task-flow" role="dialog" aria-modal="true" aria-label="Create a new agent task">
      <header className="task-flow-header">
        <div className="task-flow-brand"><img src="/memstack-icon.png" alt="" /><span><b>Create task</b><small>Plan-first agent workflow</small></span></div>
        <FlowStepper stage={stage} />
        <button className="icon-button" type="button" aria-label="Close new task flow" onClick={onClose}><Cross2Icon /></button>
      </header>
      {stage === 'define' ? <DefineTask draft={draft} onChange={setDraft} onGenerate={() => setStage('generating')} /> : null}
      {stage === 'generating' ? <GeneratingPlan draft={draft} /> : null}
      {stage === 'review' ? (
        <ReviewPlan
          draft={draft}
          plan={plan}
          enabledSteps={enabledSteps}
          onBack={() => setStage('define')}
          onToggleStep={(index) => setEnabledSteps((current) => current.map((enabled, itemIndex) => itemIndex === index ? !enabled : enabled))}
          onAddStep={addStep}
          onUpdateStep={(index, updatedStep) => setPlan((current) => current.map((step, stepIndex) => stepIndex === index ? updatedStep : step))}
          onRevise={() => setStage('generating')}
          onApprove={approvePlan}
        />
      ) : null}
    </div>
  );
}
