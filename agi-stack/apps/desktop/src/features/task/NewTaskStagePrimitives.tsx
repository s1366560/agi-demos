import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import {
  ArrowLeftIcon,
  CheckCircledIcon,
  LightningBoltIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';

export function handleRadioArrowKey(event: ReactKeyboardEvent<HTMLButtonElement>) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) {
    return;
  }
  const group = event.currentTarget.closest('[role="radiogroup"]');
  const radios = Array.from(
    group?.querySelectorAll<HTMLButtonElement>('[role="radio"]:not([disabled])') ?? [],
  );
  const currentIndex = radios.indexOf(event.currentTarget);
  if (currentIndex < 0 || radios.length < 2) return;
  event.preventDefault();
  const nextIndex =
    event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? radios.length - 1
        : (currentIndex + (event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1) + radios.length) %
          radios.length;
  radios[nextIndex]?.focus();
  radios[nextIndex]?.click();
}

export function StageHeading({
  eyebrow,
  title,
  description,
  compact = false,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  compact?: boolean;
}) {
  return (
    <div className={`new-task-stage-heading ${compact ? 'compact' : ''}`}>
      <span className="new-task-eyebrow">{eyebrow}</span>
      <h2>{title}</h2>
      {description ? <p>{description}</p> : null}
    </div>
  );
}

export function ModeCard({
  selected,
  icon,
  title,
  description,
  onSelect,
}: {
  selected: boolean;
  icon: React.ReactNode;
  title: string;
  description: string;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      className={selected ? 'selected' : ''}
      onKeyDown={handleRadioArrowKey}
      onClick={onSelect}
    >
      <span>{icon}</span>
      <div>
        <strong>{title}</strong>
        <small>{description}</small>
      </div>
      {selected ? <CheckCircledIcon /> : null}
    </button>
  );
}

export function EnvironmentButton({
  selected,
  icon,
  title,
  description,
  onSelect,
}: {
  selected: boolean;
  icon: React.ReactNode;
  title: string;
  description: string;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      className={selected ? 'selected' : ''}
      onKeyDown={handleRadioArrowKey}
      onClick={onSelect}
    >
      {icon}
      <span>
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
    </button>
  );
}

export function PlanningCheck({
  state,
  title,
  description,
}: {
  state: 'complete' | 'active' | 'pending';
  title: string;
  description: string;
}) {
  return (
    <div className={state}>
      {state === 'complete' ? <CheckCircledIcon /> : <LightningBoltIcon />}
      <span>
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
    </div>
  );
}

export function NewTaskFooterBackButton({ onClick }: { onClick: () => void }) {
  const { t } = useI18n();
  return (
    <button type="button" className="new-task-footer-back" onClick={onClick}>
      <ArrowLeftIcon /> {t('task.editBrief')}
    </button>
  );
}

export function FlowStep({
  index,
  label,
  active,
  done,
}: {
  index: number;
  label: string;
  active: boolean;
  done: boolean;
}) {
  return (
    <li className={active ? 'active' : done ? 'done' : ''} aria-current={active ? 'step' : undefined}>
      <span>{done ? <CheckCircledIcon /> : index}</span>
      <strong>{label}</strong>
    </li>
  );
}
