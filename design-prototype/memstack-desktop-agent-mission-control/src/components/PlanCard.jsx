import { useEffect, useState } from 'react';
import {
  CheckCircledIcon,
  CodeIcon,
  FileTextIcon,
  LightningBoltIcon,
  LockClosedIcon,
  MagicWandIcon,
  Pencil2Icon,
  PlusIcon,
  RocketIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

export const WORK_PLAN = [
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

export const CODE_PLAN = [
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

function PlanStep({ step, index, enabled, editing, onToggle, onEdit, onSave, onCancel, t }) {
  const [editTitle, setEditTitle] = useState(step.title);
  const [editDetail, setEditDetail] = useState(step.detail);
  if (editing) {
    return (
      <article className="generated-plan-step editing">
        <div className="plan-step-number">{String(index + 1).padStart(2, '0')}</div>
        <div className="plan-step-editor">
          <input aria-label={t('Plan step title')} value={editTitle} onChange={(event) => setEditTitle(event.target.value)} />
          <textarea aria-label={t('Plan step detail')} value={editDetail} onChange={(event) => setEditDetail(event.target.value)} />
          <div><button type="button" onClick={onCancel}>{t('Cancel')}</button><button className="primary" type="button" onClick={() => onSave({ ...step, title: editTitle, detail: editDetail })}>{t('Save step')}</button></div>
        </div>
      </article>
    );
  }
  return (
    <article className={`generated-plan-step ${enabled ? '' : 'disabled'}`}>
      <button className="plan-step-toggle" type="button" aria-label={`${enabled ? t('Disable') : t('Enable')} ${step.title}`} onClick={onToggle}>
        {enabled ? <CheckCircledIcon /> : <span />}
      </button>
      <div className="plan-step-number">{String(index + 1).padStart(2, '0')}</div>
      <div className="plan-step-copy"><b>{step.title}</b><p>{step.detail}</p><span><FileTextIcon /> {step.output}</span></div>
      <time>{step.duration}</time>
      <button className="icon-button" type="button" aria-label={`${t('Edit')} ${step.title}`} onClick={onEdit}><Pencil2Icon /></button>
    </article>
  );
}

export function PlanCard({ mode, title, generating, onApprove, onRevise }) {
  const { t } = useI18n();
  const basePlan = mode === 'work' ? WORK_PLAN : CODE_PLAN;
  const [plan, setPlan] = useState(basePlan);
  const [enabledSteps, setEnabledSteps] = useState(() => basePlan.map(() => true));
  const [editingIndex, setEditingIndex] = useState(null);

  useEffect(() => {
    setPlan(basePlan);
    setEnabledSteps(basePlan.map(() => true));
    setEditingIndex(null);
  }, [generating]);

  if (generating) {
    return (
      <article className="plan-card generating">
        <div className="plan-card-header"><span className="plan-card-icon"><MagicWandIcon /></span><div><small>{t('AGENT IS PLANNING')}</small><b>{t('Building a plan for “{title}”', { title })}</b></div></div>
        <div className="planning-progress"><i /></div>
        <p>{t('The agent is reading only the approved context. No tools have run and no files have changed.')}</p>
      </article>
    );
  }

  const enabledCount = enabledSteps.filter(Boolean).length;
  const totalMinutes = plan.reduce((total, step, index) => total + (enabledSteps[index] ? Number.parseInt(step.duration, 10) : 0), 0);

  return (
    <article className="plan-card">
      <div className="plan-card-header">
        <span className="plan-card-icon"><LightningBoltIcon /></span>
        <div><small>{t('PROPOSED PLAN')}</small><b>{t('Review the agent’s plan')}</b><p>{t('Change the sequence or remove a step before granting execution authority.')}</p></div>
        <span className="plan-card-status"><CheckCircledIcon /> {t('Plan ready')}</span>
      </div>

      <div className="generated-plan-list">
        {plan.map((step, index) => (
          <PlanStep
            key={`${index}-${step.title}`}
            step={step}
            index={index}
            enabled={enabledSteps[index]}
            editing={editingIndex === index}
            onToggle={() => setEnabledSteps((current) => current.map((enabled, itemIndex) => itemIndex === index ? !enabled : enabled))}
            onEdit={() => setEditingIndex(index)}
            onCancel={() => setEditingIndex(null)}
            onSave={(updatedStep) => { setPlan((current) => current.map((item, itemIndex) => itemIndex === index ? updatedStep : item)); setEditingIndex(null); }}
            t={t}
          />
        ))}
        <button className="add-plan-step" type="button" onClick={() => { setPlan((current) => [...current, { title: 'Final human checkpoint', detail: 'Present the result, sources, and unresolved questions before completion.', output: 'Review packet', duration: '3 min' }]); setEnabledSteps((current) => [...current, true]); }}><PlusIcon /> {t('Add a step')}</button>
      </div>

      <div className="plan-card-summary">
        <span><small>{t('Estimated time')}</small><b>{totalMinutes} min</b></span>
        <span><small>{t('Steps')}</small><b>{enabledCount} / {plan.length}</b></span>
        <span className="plan-card-authority"><LockClosedIcon />{t('Approval starts the selected steps. You can pause or steer the agent at any time.')}</span>
      </div>

      <div className="plan-card-actions">
        <button type="button" onClick={onRevise}>{t('Ask agent to revise')}</button>
        <button className="primary" type="button" onClick={() => onApprove(plan.filter((_, index) => enabledSteps[index]))}>
          {mode === 'work' ? <RocketIcon /> : <CodeIcon />} {t('Approve plan')} <CheckCircledIcon />
        </button>
      </div>
    </article>
  );
}
