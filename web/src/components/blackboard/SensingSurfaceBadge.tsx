import { useTranslation } from 'react-i18next';

import {
  NON_AUTHORITATIVE,
  SENSING_CAPABLE,
} from './blackboardSurfaceContract';

interface SensingSurfaceBadgeProps {
  labelKey: string;
  fallbackLabel: string;
}

export function SensingSurfaceBadge({
  labelKey,
  fallbackLabel,
}: SensingSurfaceBadgeProps) {
  const { t } = useTranslation();

  return (
    <div
      data-blackboard-surface="sensing"
      data-blackboard-authority={NON_AUTHORITATIVE}
      data-blackboard-signal-role={SENSING_CAPABLE}
      className="inline-flex flex-wrap items-center gap-2 rounded-full border border-border-light bg-surface-muted px-2.5 py-1 text-[10px] font-medium uppercase tracking-wide text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-muted"
    >
      <span>{t(labelKey, fallbackLabel)}</span>
      <span aria-hidden="true" className="text-text-muted dark:text-text-muted">
        ·
      </span>
      <span>{t('blackboard.sensingBoundary', 'sensing')}</span>
      <span aria-hidden="true" className="text-text-muted dark:text-text-muted">
        ·
      </span>
      <span>{t('blackboard.nonAuthoritativeBoundary', 'non-authoritative')}</span>
    </div>
  );
}
