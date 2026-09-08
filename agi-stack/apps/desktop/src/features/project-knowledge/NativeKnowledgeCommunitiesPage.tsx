import { useState } from 'react';

import { useI18n } from '../../i18n';
import { NativeKnowledgeCommunityHistory } from './NativeKnowledgeCommunityHistory';
import type {
  NativeKnowledgeCommunityModel,
  NativeKnowledgeCommunityController,
} from './nativeKnowledgeCommunityController';

export function NativeKnowledgeCommunitiesPage({
  model,
  controller,
}: Readonly<{
  model: NativeKnowledgeCommunityModel;
  controller: NativeKnowledgeCommunityController;
}>) {
  const { t } = useI18n();
  const [buildId, setBuildId] = useState('');
  const [minSize, setMinSize] = useState(2);
  const [workspaceId, setWorkspaceId] = useState('');
  const busy = model.phase === 'loading' || model.phase === 'executing';
  const locked = busy || model.recoveryRequired || model.phase === 'unavailable';
  const allowed = (action: string) => model.allowedActions.includes(action);
  const page = model.page;
  const current = page?.current_graph === true;
  return (
    <main className="native-memories-page">
      <header>
        <h1>{t('nativeCommunity.title')}</h1>
        <button
          type="button"
          disabled={busy || model.phase === 'unavailable'}
          onClick={() => void controller.refresh()}
        >
          {t('nativeCommunity.refresh')}
        </button>
      </header>
      <p>{t('nativeCommunity.explicit')}</p>
      {model.phase === 'unavailable' ? (
        <p role="status">{t('nativeCommunity.unavailable')}</p>
      ) : null}
      {model.error ? <p role="alert">{t(`nativeCommunity.error.${model.error}`)}</p> : null}
      {model.recoverableCreate ? (
        <button
          type="button"
          disabled={busy || model.phase === 'unavailable'}
          onClick={() => void controller.recoverCreate()}
        >
          {t('nativeCommunity.recoverCreate')}
        </button>
      ) : null}
      {model.recoveryRequired ? (
        <p role="alert">
          {t(
            model.recoverableCreate
              ? 'nativeCommunity.uncertainCreate'
              : 'nativeCommunity.uncertain',
          )}
        </p>
      ) : null}
      {model.outcome ? <p role="status">{t(`nativeCommunity.${model.outcome}`)}</p> : null}
      {model.recoveredUnknown ? <p role="status">{t('nativeCommunity.recovered')}</p> : null}
      <NativeKnowledgeCommunityHistory model={model} controller={controller} />
      <dl>
        <dt>{t('nativeCommunity.selected')}</dt>
        <dd>{model.active?.selection.requested_build_id ?? t('nativeCommunity.none')}</dd>
        <dt>{t('nativeCommunity.active')}</dt>
        <dd>{model.active?.selection.active_build_id ?? t('nativeCommunity.none')}</dd>
        <dt>{t('nativeCommunity.revision')}</dt>
        <dd>{model.active?.selection.revision ?? '—'}</dd>
      </dl>
      {model.active?.stale_build_id ? (
        <p role="status">
          {t('nativeCommunity.stale')}: {model.active.stale_build_id}
        </p>
      ) : null}
      <nav aria-label={t('nativeCommunity.open')}>
        <label>
          {t('nativeCommunity.buildId')}{' '}
          <input
            value={buildId}
            disabled={locked}
            onChange={(event) => setBuildId(event.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={locked || !buildId.trim()}
          onClick={() => void controller.refresh(buildId.trim())}
        >
          {t('nativeCommunity.open')}
        </button>
        <button
          type="button"
          disabled={locked || !model.active?.selection.active_build_id}
          onClick={() => void controller.refresh(model.active!.selection.active_build_id!)}
        >
          {t('nativeCommunity.openActive')}
        </button>
        <button
          type="button"
          disabled={locked || !model.active?.selection.requested_build_id}
          onClick={() => void controller.refresh(model.active!.selection.requested_build_id!)}
        >
          {t('nativeCommunity.openSelected')}
        </button>
      </nav>
      {allowed('create_community_build') ? (
        <fieldset disabled={locked}>
          <legend>{t('nativeCommunity.create_community_build')}</legend>
          <label>
            {t('nativeCommunity.minSize')}{' '}
            <input
              type="number"
              min={2}
              max={4096}
              value={minSize}
              onChange={(event) => setMinSize(event.target.valueAsNumber)}
            />
          </label>
          <button
            type="button"
            disabled={!Number.isSafeInteger(minSize) || minSize < 2 || minSize > 4096}
            onClick={() => void controller.review('create_community_build', { minSize })}
          >
            {t('nativeCommunity.review')}
          </button>
        </fieldset>
      ) : null}
      {page ? (
        <section aria-label={t('nativeCommunity.build')}>
          <h2>{t('nativeCommunity.build')}</h2>
          <p>{page.build.build_id}</p>
          <p>
            {t(`nativeCommunity.${page.status.state}`)} · {t('nativeCommunity.ready')}:{' '}
            {page.status.ready_count} · {t('nativeCommunity.failedCount')}:{' '}
            {page.status.failed_count} · {t('nativeCommunity.insufficient_evidence')}:{' '}
            {page.status.insufficient_evidence_count}
          </p>
          {!current ? <p role="status">{t('nativeCommunity.stale')}</p> : null}
          <div>
            {allowed('select_community_build') ? (
              <button
                type="button"
                disabled={locked || !current}
                onClick={() => void controller.review('select_community_build')}
              >
                {t('nativeCommunity.select_community_build')}
              </button>
            ) : null}
            {allowed('activate_community_build') ? (
              <button
                type="button"
                disabled={
                  locked ||
                  !current ||
                  model.active?.selection.requested_build_id !== page.build.build_id ||
                  !['completed', 'completed_empty'].includes(page.status.state)
                }
                onClick={() => void controller.review('activate_community_build')}
              >
                {t('nativeCommunity.activate_community_build')}
              </button>
            ) : null}
          </div>
          {allowed('process_community_one') ? (
            <fieldset disabled={locked || !current}>
              <legend>{t('nativeCommunity.process_community_one')}</legend>
              <button type="button" onClick={() => void controller.review('process_community_one')}>
                {t('nativeCommunity.loadWorkspaces')}
              </button>
              <label>
                {t('nativeCommunity.workspace')}{' '}
                <select
                  value={workspaceId}
                  onChange={(event) => setWorkspaceId(event.target.value)}
                >
                  <option value="">{t('nativeCommunity.chooseWorkspace')}</option>
                  {model.workspaces.map((workspace) => (
                    <option key={workspace.id} value={workspace.id}>
                      {workspace.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                disabled={!model.workspaces.some((workspace) => workspace.id === workspaceId)}
                onClick={() =>
                  void controller.review('process_community_one', {
                    workspaceId,
                  })
                }
              >
                {t('nativeCommunity.review')}
              </button>
            </fieldset>
          ) : null}
          <ol>
            {page.items.map((candidate) => {
              const decision = candidate.result?.submission.decision;
              return (
                <li key={candidate.candidate_id}>
                  <h3>{decision?.status === 'ready' ? decision.name : candidate.candidate_id}</h3>
                  <p>
                    {t(`nativeCommunity.${candidate.job.state}`)} · {t('nativeCommunity.attempt')}:{' '}
                    {candidate.job.attempt} · {t('nativeCommunity.members')}:{' '}
                    {candidate.member_count}
                  </p>
                  {decision?.status === 'ready' ? <p>{decision.summary}</p> : null}
                  {decision ? (
                    <>
                      <p>{t(`nativeCommunity.${decision.status}`)}</p>
                      <p>{decision.rationale}</p>
                      <details>
                        <summary>{t('nativeCommunity.evidence')}</summary>
                        <ul>
                          {decision.evidence.map((evidence, index) => (
                            <li key={index}>
                              {evidence.source.memory_id} · {t('nativeCommunity.revision')}:{' '}
                              {evidence.source.revision} · {t('nativeCommunity.entity')}:{' '}
                              {evidence.entity_index}
                              {evidence.relationship_index !== null
                                ? ` · ${t('nativeCommunity.relationship')}: ${evidence.relationship_index}`
                                : ''}
                            </li>
                          ))}
                        </ul>
                      </details>
                    </>
                  ) : null}
                  {candidate.job.failure ? (
                    <p>{t(`nativeCommunity.${candidate.job.failure}`)}</p>
                  ) : null}
                  {allowed('retry_community') && candidate.job.state === 'failed' ? (
                    <button
                      type="button"
                      disabled={locked || !current}
                      onClick={() =>
                        void controller.review('retry_community', {
                          candidateId: candidate.candidate_id,
                        })
                      }
                    >
                      {t('nativeCommunity.retry_community')}
                    </button>
                  ) : null}
                  {allowed('community_audit') && candidate.job.attempt > 0 ? (
                    <button
                      type="button"
                      disabled={locked}
                      onClick={() =>
                        void controller.loadAudit(candidate.candidate_id, candidate.job.attempt)
                      }
                    >
                      {t('nativeCommunity.audit')}
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ol>
          {page.items.length === 0 ? <p>{t('nativeCommunity.empty')}</p> : null}
          <nav aria-label={t('nativeCommunity.pagination')}>
            <button
              type="button"
              disabled={locked || page.offset === 0}
              onClick={() =>
                void controller.refresh(page.build.build_id, Math.max(0, page.offset - page.limit))
              }
            >
              {t('nativeCommunity.previous')}
            </button>
            <span>
              {Math.min(page.offset + 1, page.total)}–
              {Math.min(page.offset + page.limit, page.total)} / {page.total}
            </span>
            <button
              type="button"
              disabled={locked || page.offset + page.limit >= page.total}
              onClick={() => void controller.refresh(page.build.build_id, page.offset + page.limit)}
            >
              {t('nativeCommunity.next')}
            </button>
          </nav>
        </section>
      ) : (
        <p>{t('nativeCommunity.noBuild')}</p>
      )}
      {model.command ? (
        <section aria-label={t('nativeCommunity.review')}>
          <h2>{t('nativeCommunity.review')}</h2>
          <p>{t(`nativeCommunity.${model.command.operation}`)}</p>
          {'build_id' in model.command ? (
            <p>
              {t('nativeCommunity.buildId')}: {model.command.build_id}
            </p>
          ) : null}
          {'workspace_id' in model.command ? (
            <p>
              {t('nativeCommunity.workspace')}: {model.command.workspace_id}
            </p>
          ) : null}
          {'expected_selection_revision' in model.command ? (
            <p>
              {t('nativeCommunity.revision')}: {model.command.expected_selection_revision}
            </p>
          ) : null}
          {'candidate_id' in model.command ? (
            <p>
              {model.command.candidate_id} · {t('nativeCommunity.attempt')}:{' '}
              {model.command.expected_attempt}
            </p>
          ) : null}
          {'min_community_size' in model.command ? (
            <p>
              {t('nativeCommunity.minSize')}: {model.command.min_community_size}
            </p>
          ) : null}
          <button type="button" disabled={locked} onClick={() => void controller.confirm()}>
            {t('nativeCommunity.confirm')}
          </button>
          <button type="button" disabled={locked} onClick={controller.cancel}>
            {t('nativeCommunity.cancel')}
          </button>
        </section>
      ) : null}
      {model.audit ? (
        <section aria-label={t('nativeCommunity.audit')}>
          <h2>{t('nativeCommunity.audit')}</h2>
          <p>
            {model.audit.candidate_id} · {t('nativeCommunity.attempt')}: {model.audit.attempt}
          </p>
          <dl>
            <dt>{t('nativeCommunity.agent')}</dt>
            <dd>{model.audit.agent_id}</dd>
            <dt>{t('nativeCommunity.provider')}</dt>
            <dd>
              {model.audit.provider_id} / {model.audit.model_id}
            </dd>
            <dt>{t('nativeCommunity.status')}</dt>
            <dd>{t(`nativeCommunity.${model.audit.status}`)}</dd>
            <dt>{t('nativeCommunity.duration')}</dt>
            <dd>{model.audit.latency_ms ?? '—'}</dd>
          </dl>
          {model.audit.failure ? <p>{t(`nativeCommunity.${model.audit.failure}`)}</p> : null}
        </section>
      ) : null}
    </main>
  );
}
