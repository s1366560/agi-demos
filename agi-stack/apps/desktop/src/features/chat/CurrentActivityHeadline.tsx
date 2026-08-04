import { useEffect, useState } from 'react';

import { ChevronDownIcon, ChevronRightIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { CurrentActivityHeadline } from '../session/currentActivityModel';
import {
  deriveStalledState,
  formatElapsedClock,
  stalledIdleMinutes,
} from '../session/currentActivityModel';
import type { SessionActivityPresence } from '../session/sessionNarrativeModel';
import type { SessionUsageSummary } from '../session/sessionUsageModel';
import { formatTokenCount } from '../session/sessionUsageModel';

import './CurrentActivityHeadline.css';

/**
 * Slim "currently doing X" bar anchored above the composer while a session
 * run is live. Collapsed by default; the chevron expands the recent activity
 * group. Expansion state is in-memory and resets when the session changes.
 *
 * The single 1s tick driving the elapsed clock also re-evaluates the stalled
 * state (no new visible activity past the threshold), so there is no extra
 * always-on timer; when the run leaves the live presence the bar unmounts
 * and the stalled presentation disappears with it.
 */
export function CurrentActivityHeadlineBar({
  activity,
  sessionKey,
  presence,
  usage,
}: {
  activity: CurrentActivityHeadline;
  sessionKey: string;
  presence: SessionActivityPresence;
  usage?: SessionUsageSummary | null;
}) {
  const { t } = useI18n();
  const [expandedState, setExpandedState] = useState({ key: sessionKey, open: false });
  const expanded = expandedState.key === sessionKey && expandedState.open;
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const elapsed =
    activity.startedAtMs !== null
      ? formatElapsedClock(Math.max(0, nowMs - activity.startedAtMs))
      : '';
  const stalled = deriveStalledState({
    presence,
    lastActivityAtMs: activity.lastActivityAtMs,
    nowMs,
  });
  const label = activity.label || (activity.titleKey ? t(activity.titleKey) : '');
  const toggleLabel = t(
    expanded ? 'session.currentActivity.hideDetails' : 'session.currentActivity.showDetails',
  );

  return (
    <div
      className="current-activity-headline"
      data-kind={activity.kind}
      data-stalled={stalled.stalled ? 'true' : undefined}
    >
      <div className="current-activity-headline-row" role="status" aria-live="polite">
        <span className="current-activity-dot" aria-hidden="true" />
        <span className="current-activity-label">
          <strong>{label}</strong>
          {activity.detail ? (
            <span className="current-activity-detail">{activity.detail}</span>
          ) : null}
        </span>
        {activity.activeSubagentCount > 1 ? (
          <span className="current-activity-count">
            {t('session.currentActivity.moreSubagents', {
              count: activity.activeSubagentCount - 1,
            })}
          </span>
        ) : null}
        {usage ? (
          <span className="current-activity-usage">
            {t('session.currentActivity.usage', {
              tokens: formatTokenCount(usage.currentTokens),
              percent: usage.occupancyPct.toFixed(1),
            })}
          </span>
        ) : null}
        {elapsed ? <span className="current-activity-elapsed">{elapsed}</span> : null}
        <button
          type="button"
          className="current-activity-toggle"
          aria-expanded={expanded}
          aria-label={toggleLabel}
          title={toggleLabel}
          onClick={() => setExpandedState({ key: sessionKey, open: !expanded })}
        >
          {expanded ? <ChevronDownIcon aria-hidden="true" /> : <ChevronRightIcon aria-hidden="true" />}
        </button>
      </div>
      {stalled.stalled ? (
        <div className="current-activity-stalled" role="status">
          <span>
            {t('session.currentActivity.stalled', {
              minutes: stalledIdleMinutes(stalled.idleMs),
            })}
          </span>
          <span className="current-activity-stalled-clock">
            {formatElapsedClock(stalled.idleMs)}
          </span>
          <span className="current-activity-stalled-hint">
            {t('session.currentActivity.stalledHint')}
          </span>
        </div>
      ) : null}
      {expanded ? (
        <ul className="current-activity-entries" aria-label={t('session.currentActivity')}>
          {activity.entries.length === 0 ? (
            <li className="current-activity-entry-empty">{t('activity.groupEmpty')}</li>
          ) : (
            activity.entries.map((entry) => (
              <li
                key={entry.id}
                className={`current-activity-entry status-${entry.status}`}
              >
                <span className="current-activity-entry-dot" aria-hidden="true" />
                <span className="current-activity-entry-label">
                  {entry.label || (entry.titleKey ? t(entry.titleKey) : '')}
                </span>
                {entry.detail ? (
                  <span className="current-activity-entry-detail">{entry.detail}</span>
                ) : null}
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}
