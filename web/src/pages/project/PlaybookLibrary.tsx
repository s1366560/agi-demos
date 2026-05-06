/**
 * PlaybookLibrary — read-only view of the project's reflection loop.
 *
 * Two stacked sections:
 *  1. Distilled playbooks (active patterns the reflector has learned).
 *  2. Reflection verdicts timeline (audit log of CREATE / REINFORCE
 *     / DEPRECATE / NOOP decisions).
 *
 * Both views are paginated by limit only — the reflection loop is
 * naturally bounded per project so client-side filtering is sufficient
 * for the foreseeable future.
 */

import { AlertCircle, BookOpen, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { formatDateOnly } from '@/utils/date';

import {
  type Playbook,
  type ReflectionVerdict,
  playbookService,
} from '../../services/playbookService';

const LIMIT = 200;
const POLL_INTERVAL_MS = 30_000;

const VERDICT_LABELS: Record<ReflectionVerdict['action'], string> = {
  create: 'Created',
  reinforce: 'Reinforced',
  deprecate: 'Deprecated',
  noop: 'No-op',
};

const VERDICT_BADGE_CLASS: Record<ReflectionVerdict['action'], string> = {
  create: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  reinforce: 'bg-blue-50 text-blue-700 border-blue-200',
  deprecate: 'bg-orange-50 text-orange-700 border-orange-200',
  noop: 'bg-zinc-50 text-zinc-600 border-zinc-200',
};

interface SectionProps {
  title: string;
  icon: React.ReactNode;
  count: number;
  children: React.ReactNode;
}

const Section: React.FC<SectionProps> = ({ title, icon, count, children }) => (
  <section className="rounded-md border border-zinc-200 bg-white">
    <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-medium text-zinc-900">
        {icon}
        <span>{title}</span>
        <span className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[11px] font-medium text-zinc-700">
          {count}
        </span>
      </div>
    </header>
    <div className="p-4">{children}</div>
  </section>
);

const PlaybookCard: React.FC<{ playbook: Playbook }> = ({ playbook }) => (
  <article className="rounded-md border border-zinc-200 p-4 hover:border-zinc-300">
    <header className="flex items-start justify-between gap-4">
      <div>
        <h3 className="text-sm font-medium text-zinc-900">{playbook.name}</h3>
        <p className="mt-0.5 text-xs text-zinc-500">
          Status: <span className="text-zinc-700">{playbook.status}</span>
          {' · '}
          Hits: <span className="text-zinc-700">{playbook.hit_count}</span>
          {playbook.last_used_at !== null && (
            <>
              {' · '}
              Last used:{' '}
              <span className="text-zinc-700">{formatDateOnly(playbook.last_used_at)}</span>
            </>
          )}
        </p>
      </div>
    </header>
    {playbook.trigger.description.length > 0 && (
      <p className="mt-2 text-xs text-zinc-600">
        <span className="font-medium text-zinc-700">Trigger:</span>{' '}
        {playbook.trigger.description}
      </p>
    )}
    {playbook.steps.length > 0 && (
      <ol className="mt-3 space-y-1.5 border-l border-zinc-200 pl-4 text-xs text-zinc-700">
        {playbook.steps.map((step) => (
          <li key={step.order}>
            <span className="font-medium text-zinc-900">Step {step.order}:</span>{' '}
            {step.instruction}
            {step.rationale !== null && step.rationale.length > 0 && (
              <span className="block text-zinc-500">{step.rationale}</span>
            )}
          </li>
        ))}
      </ol>
    )}
  </article>
);

const VerdictRow: React.FC<{ verdict: ReflectionVerdict }> = ({ verdict }) => (
  <li className="flex gap-3 py-3 first:pt-0 last:pb-0">
    <div className="shrink-0">
      <span
        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${VERDICT_BADGE_CLASS[verdict.action]}`}
      >
        {VERDICT_LABELS[verdict.action]}
      </span>
    </div>
    <div className="min-w-0 flex-1">
      <p className="text-sm text-zinc-900">{verdict.rationale || '(no rationale)'}</p>
      <p className="mt-0.5 text-xs text-zinc-500">
        {formatDateOnly(verdict.created_at)}
        {verdict.playbook_id !== null && (
          <>
            {' · '}
            <span className="font-mono text-zinc-600">{verdict.playbook_id}</span>
          </>
        )}
      </p>
    </div>
  </li>
);

export const PlaybookLibrary: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const { t } = useTranslation();
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [verdicts, setVerdicts] = useState<ReflectionVerdict[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (silent: boolean = false) => {
      if (projectId === undefined) return;
      if (!silent) setLoading(true);
      setError(null);
      try {
        const [pbs, vds] = await Promise.all([
          playbookService.listPlaybooks(projectId, LIMIT),
          playbookService.listReflectionVerdicts(projectId, LIMIT),
        ]);
        setPlaybooks(pbs);
        setVerdicts(vds);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [projectId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Background refresh: the reflection loop runs out-of-band, so poll
  // periodically while the page is visible to keep the view fresh
  // without requiring a dedicated project-event channel.
  useEffect(() => {
    if (projectId === undefined) return;
    const handle = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        void load(true);
      }
    }, POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(handle);
    };
  }, [projectId, load]);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900">
            {t('playbooks.title', 'Playbook Library')}
          </h1>
          <p className="mt-0.5 text-sm text-zinc-500">
            {t(
              'playbooks.description',
              'Distilled patterns the reflector has learned from this project, with the audit trail of every verdict.',
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            void load();
          }}
          className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-700 hover:bg-zinc-50 disabled:opacity-50"
          disabled={loading}
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          <span>{t('common.refresh', 'Refresh')}</span>
        </button>
      </header>

      {error !== null && (
        <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          <AlertCircle className="h-4 w-4" />
          <span>{error}</span>
        </div>
      )}

      <Section
        title={t('playbooks.section.playbooks', 'Distilled playbooks')}
        icon={<BookOpen className="h-4 w-4 text-zinc-500" />}
        count={playbooks.length}
      >
        {playbooks.length === 0 ? (
          <p className="py-6 text-center text-sm text-zinc-500">
            {t(
              'playbooks.empty.playbooks',
              'No playbooks yet. The reflector will distill them as friction signals accumulate.',
            )}
          </p>
        ) : (
          <div className="space-y-3">
            {playbooks.map((p) => (
              <PlaybookCard key={p.id} playbook={p} />
            ))}
          </div>
        )}
      </Section>

      <Section
        title={t('playbooks.section.verdicts', 'Reflection verdicts')}
        icon={<Sparkles className="h-4 w-4 text-zinc-500" />}
        count={verdicts.length}
      >
        {verdicts.length === 0 ? (
          <p className="py-6 text-center text-sm text-zinc-500">
            {t(
              'playbooks.empty.verdicts',
              'No verdicts recorded yet.',
            )}
          </p>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {verdicts.map((v) => (
              <VerdictRow key={v.id} verdict={v} />
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
};

export default PlaybookLibrary;
