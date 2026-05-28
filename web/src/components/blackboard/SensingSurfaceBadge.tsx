import { useTranslation } from 'react-i18next';

import { NON_AUTHORITATIVE, SENSING_CAPABLE } from './blackboardSurfaceContract';

interface SensingSurfaceBadgeProps {
  labelKey: string;
  fallbackLabel: string;
}

export function SensingSurfaceBadge({ labelKey, fallbackLabel }: SensingSurfaceBadgeProps) {
  const { t } = useTranslation();

  return (
    <div
      data-blackboard-surface="sensing"
      data-blackboard-authority={NON_AUTHORITATIVE}
      data-blackboard-signal-role={SENSING_CAPABLE}
      className="inline-flex h-5 items-center gap-1 whitespace-nowrap rounded border border-border-light bg-surface-muted px-1.5 text-[9px] font-medium uppercase tracking-wide text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-muted"
    >
      <span>{t(labelKey, fallbackLabel)}</span>
      <span aria-hidden="true" className="hidden text-text-muted dark:text-text-muted 2xl:inline">
        ·
      </span>
      <span className="hidden 2xl:inline">{t('blackboard.sensingBoundary', 'sensing')}</span>
      <span aria-hidden="true" className="hidden text-text-muted dark:text-text-muted 2xl:inline">
        ·
      </span>
      <span className="hidden 2xl:inline">
        {t('blackboard.nonAuthoritativeBoundary', 'non-authoritative')}
      </span>
    </div>
  );
}
