import { useTranslation } from 'react-i18next';

import type { BlackboardAuthorityClass, BlackboardSignalRole } from './blackboardSurfaceContract';

/**
 * Boundary classification for a blackboard surface badge.
 *
 * `owned`/`hosted` render as a `data-blackboard-boundary` attribute,
 * `sensing`/`derived` as `data-blackboard-surface` (contract preserved for
 * existing consumers and tests).
 */
export type SurfaceBadgeBoundary = 'owned' | 'hosted' | 'sensing' | 'derived';

export interface SurfaceBadgeProps {
  /** i18n key for the leading surface label */
  labelKey: string;
  /** Fallback text for the leading surface label */
  fallbackLabel: string;
  /** Boundary classification (middle segment) */
  boundary: SurfaceBadgeBoundary;
  /** Authority classification (trailing segment) */
  authority: BlackboardAuthorityClass;
  /** Optional signal-role data attribute (sensing surfaces) */
  signalRole?: BlackboardSignalRole | undefined;
}

const BOUNDARY_LABEL: Record<SurfaceBadgeBoundary, { key: string; fallback: string }> = {
  owned: { key: 'blackboard.ownedBoundary', fallback: 'owned' },
  hosted: { key: 'blackboard.hostedProjectionBoundary', fallback: 'hosted' },
  sensing: { key: 'blackboard.sensingBoundary', fallback: 'sensing' },
  derived: { key: 'blackboard.derivedBoundary', fallback: 'derived' },
};

const AUTHORITY_LABEL: Record<BlackboardAuthorityClass, { key: string; fallback: string }> = {
  authoritative: { key: 'blackboard.authoritativeBoundary', fallback: 'authoritative' },
  'non-authoritative': {
    key: 'blackboard.nonAuthoritativeBoundary',
    fallback: 'non-authoritative',
  },
};

/**
 * Unified blackboard surface badge: leading surface label plus boundary and
 * authority segments, with the surface contract exposed as data attributes.
 * Replaces the former SensingSurfaceBadge / OwnedSurfaceBadge /
 * HostedProjectionBadge / DerivedSurfaceBadge copies.
 */
export function SurfaceBadge({
  labelKey,
  fallbackLabel,
  boundary,
  authority,
  signalRole,
}: SurfaceBadgeProps) {
  const { t } = useTranslation();
  const boundaryLabel = BOUNDARY_LABEL[boundary];
  const authorityLabel = AUTHORITY_LABEL[authority];

  const dataAttributes: Record<string, string> = {
    'data-blackboard-authority': authority,
  };
  if (boundary === 'owned' || boundary === 'hosted') {
    dataAttributes['data-blackboard-boundary'] = boundary;
  } else {
    dataAttributes['data-blackboard-surface'] = boundary;
  }
  if (signalRole) {
    dataAttributes['data-blackboard-signal-role'] = signalRole;
  }

  if (boundary === 'sensing') {
    return (
      <div
        {...dataAttributes}
        className="inline-flex h-5 items-center gap-1 whitespace-nowrap rounded border border-border-light bg-surface-muted px-1.5 text-[9px] font-medium uppercase tracking-wide text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-muted"
      >
        <span>{t(labelKey, fallbackLabel)}</span>
        <span
          aria-hidden="true"
          className="hidden text-text-muted dark:text-text-muted 2xl:inline"
        >
          ·
        </span>
        <span className="hidden 2xl:inline">{t(boundaryLabel.key, boundaryLabel.fallback)}</span>
        <span
          aria-hidden="true"
          className="hidden text-text-muted dark:text-text-muted 2xl:inline"
        >
          ·
        </span>
        <span className="hidden 2xl:inline">{t(authorityLabel.key, authorityLabel.fallback)}</span>
      </div>
    );
  }

  return (
    <div
      {...dataAttributes}
      className="inline-flex flex-wrap items-center gap-2 rounded-full border border-border-light bg-surface-muted px-2.5 py-1 text-[10px] font-medium uppercase tracking-wide text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-muted"
    >
      <span>{t(labelKey, fallbackLabel)}</span>
      <span aria-hidden="true" className="text-text-muted dark:text-text-muted">
        ·
      </span>
      <span>{t(boundaryLabel.key, boundaryLabel.fallback)}</span>
      <span aria-hidden="true" className="text-text-muted dark:text-text-muted">
        ·
      </span>
      <span>{t(authorityLabel.key, authorityLabel.fallback)}</span>
    </div>
  );
}
