import { useTranslation } from 'react-i18next';

import {
  AUTHORITATIVE,
  OWNED,
} from './blackboardSurfaceContract';

interface OwnedSurfaceBadgeProps {
  labelKey: string;
  fallbackLabel: string;
}

export function OwnedSurfaceBadge({
  labelKey,
  fallbackLabel,
}: OwnedSurfaceBadgeProps) {
  const { t } = useTranslation();

  return (
    <div
      data-blackboard-boundary={OWNED}
      data-blackboard-authority={AUTHORITATIVE}
      className="inline-flex flex-wrap items-center gap-2 rounded-full border border-border-light bg-surface-muted px-2.5 py-1 text-[10px] font-medium uppercase tracking-wide text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-muted"
    >
      <span>{t(labelKey, fallbackLabel)}</span>
      <span aria-hidden="true" className="text-text-muted dark:text-text-muted">
        ·
      </span>
      <span>{t('blackboard.ownedBoundary', 'owned')}</span>
      <span aria-hidden="true" className="text-text-muted dark:text-text-muted">
        ·
      </span>
      <span>{t('blackboard.authoritativeBoundary', 'authoritative')}</span>
    </div>
  );
}
