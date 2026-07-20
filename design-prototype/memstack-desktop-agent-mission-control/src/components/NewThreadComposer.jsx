import { useState } from 'react';
import {
  ActivityLogIcon,
  ArrowRightIcon,
  ChevronDownIcon,
  CodeIcon,
  CubeIcon,
  FileTextIcon,
  ImageIcon,
  Link2Icon,
  LockClosedIcon,
  MixerHorizontalIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

import { ComposerPlusMenu } from './ComposerPlusMenu';
import { PickerMenu } from './PickerMenu';

const MODEL_OPTIONS = [
  { value: 'GPT-5.5', description: 'Primary reasoning model for planning, execution, and review.', meta: '128k', badge: 'Default' },
  { value: 'GPT-5.5 mini', description: 'Fast model for lightweight tasks and quick drafts.', meta: '128k', badge: 'Fast' },
  { value: 'GPT-5.5 Codex', description: 'Code-specialized model for implementation and refactoring.', meta: '192k', badge: 'Coding' },
  { value: 'Claude Sonnet 4.5', description: 'Balanced long-context model for synthesis and code review.', meta: '200k' },
  { value: 'Gemini 2.5 Pro', description: 'Multimodal model for large source sets and visual analysis.', meta: '1m' },
];
const EFFORT_OPTIONS = [
  { value: 'Low', description: 'Fastest responses for simple, well-scoped tasks.' },
  { value: 'Medium', description: 'Balanced speed and reasoning depth.' },
  { value: 'High', description: 'Deeper reasoning for complex, multi-step work.' },
];
const PERMISSIONS = ['Ask for approval', 'Automatic', 'Full access'];

const SUGGESTIONS = {
  work: [
    ['Draft a Q4 retention brief', 'Synthesize interviews and dashboards into a leadership-ready brief.'],
    ['Summarize competitor launches', 'Compare this week’s launch claims against our positioning.'],
    ['Prepare the weekly digest', 'Decisions, risks, and metrics in a concise readout.'],
  ],
  code: [
    ['Fix the flaky pipeline test', 'Reproduce the race and verify the smallest safe fix.'],
    ['Add command-palette search', 'Search task titles and artifacts from anywhere.'],
    ['Plan the agent SDK upgrade', 'Map breaking changes and propose a staged migration.'],
  ],
};

function cycle(list, current) {
  return list[(list.indexOf(current) + 1) % list.length];
}

export function NewThreadComposer({ workspace, recentThreads, onCreate, onOpenThread, onManageModels }) {
  const { t } = useI18n();
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState('work');
  const [model, setModel] = useState(MODEL_OPTIONS[0].value);
  const [effort, setEffort] = useState('Medium');
  const [permission, setPermission] = useState(PERMISSIONS[0]);
  const [additions, setAdditions] = useState([]);

  const canSend = prompt.trim().length > 0;

  function addItem(item) {
    setAdditions((current) => (current.some((entry) => entry.label === item.label) ? current : [...current, item]));
  }

  function send() {
    if (!canSend) return;
    onCreate({ prompt: prompt.trim(), mode, model, effort, permission, additions: additions.map((item) => item.label) });
  }

  return (
    <main className="new-thread-view">
      <div className="new-thread-content">
        <header className="new-thread-heading">
          <span className="eyebrow">{t('NEW THREAD')}</span>
          <h1>{t('What should the agent work on?')}</h1>
          <p>{t('Describe the outcome. The agent proposes a plan before any work starts.')}</p>
          <span className="new-thread-workspace"><CubeIcon />{workspace.name}</span>
        </header>

        <section className="new-thread-composer">
          {additions.length ? (
            <div className="new-thread-chips" aria-label={t('Added context')}>
              {additions.map((item) => (
                <button type="button" key={item.label} onClick={() => setAdditions((current) => current.filter((entry) => entry !== item))} aria-label={`${t('Remove')} ${item.label}`}>
                  {item.kind === 'attachment' ? <ImageIcon /> : <Link2Icon />}
                  {item.label}
                  <span aria-hidden="true">×</span>
                </button>
              ))}
            </div>
          ) : null}
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') send(); }}
            placeholder={mode === 'work' ? t('Research, draft, or analyze…') : t('Fix, build, or refactor…')}
            aria-label={t('New thread prompt')}
          />
          <div className="new-thread-composer-toolbar">
            <ComposerPlusMenu sessions={recentThreads} onAdd={addItem} />
            <div className="composer-pickers">
              <div className="mode-picker" role="group" aria-label={t('Mode')}>
                <button className={mode === 'work' ? 'active' : ''} type="button" onClick={() => setMode('work')}><MixerHorizontalIcon /> {t('Work')}</button>
                <button className={mode === 'code' ? 'active' : ''} type="button" onClick={() => setMode('code')}><CodeIcon /> {t('Code')}</button>
              </div>
              <PickerMenu
                label={t('Model')}
                value={model}
                options={MODEL_OPTIONS}
                onChange={setModel}
                footer={onManageModels ? { label: 'Manage models in Settings', icon: <CubeIcon />, onClick: onManageModels } : undefined}
              />
              <PickerMenu label={t('Effort')} value={effort} options={EFFORT_OPTIONS} onChange={setEffort} />
              <button className="picker-chip" type="button" onClick={() => setPermission(cycle(PERMISSIONS, permission))}><LockClosedIcon /> {t(permission)}<ChevronDownIcon /></button>
            </div>
            <button className="send-button" type="button" disabled={!canSend} onClick={send} aria-label={t('Start thread')}><ArrowRightIcon /></button>
          </div>
        </section>

        <section className="new-thread-suggestions" aria-label={t('Suggestions')}>
          {SUGGESTIONS[mode].map(([title, description]) => (
            <button type="button" key={title} onClick={() => setPrompt(t(description))}>
              <FileTextIcon />
              <span><b>{t(title)}</b><small>{t(description)}</small></span>
            </button>
          ))}
        </section>

        <section className="new-thread-recent" aria-label={t('Recent threads')}>
          <header><span>{t('RECENT THREADS')}</span><em>{workspace.name}</em></header>
          <div>
            {recentThreads.map((thread) => {
              const ModeIcon = thread.mode === 'code' ? CodeIcon : ActivityLogIcon;
              return (
                <button type="button" key={thread.id} onClick={() => onOpenThread(thread)}>
                  <i className={`thread-status ${thread.status}`} aria-hidden="true" />
                  <ModeIcon className="thread-mode-icon" />
                  <span><b>{thread.title}</b><small>{t(thread.meta)}</small></span>
                </button>
              );
            })}
          </div>
        </section>
      </div>
    </main>
  );
}
