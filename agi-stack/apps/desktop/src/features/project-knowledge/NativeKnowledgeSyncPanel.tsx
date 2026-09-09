import { useState } from 'react';

import { useI18n } from '../../i18n';
import type { NativeKnowledgeConflictController } from './nativeKnowledgeConflictController';
import type {
  NativeKnowledgeSyncController,
  NativeKnowledgeSyncModel,
} from './nativeKnowledgeSyncController';

export function NativeKnowledgeSyncPanel({
  model,
  controller,
  conflicts,
  disabled = false,
  connectionReady = false,
}: Readonly<{
  model: NativeKnowledgeSyncModel;
  controller: NativeKnowledgeSyncController;
  conflicts: NativeKnowledgeConflictController;
  disabled?: boolean;
  connectionReady?: boolean;
}>) {
  const { t } = useI18n();
  const [unbindOpen, setUnbindOpen] = useState(false);
  const allowed = (operation: string) => model.allowedActions.includes(operation);
  if (
    ![
      'sync_status',
      'sync_outbox',
      'pull_conflicts',
      'push_conflicts',
      'pending_resolutions',
      'resolutions',
    ].some(allowed)
  )
    return null;
  const busy = model.phase === 'loading' || model.phase === 'syncing';
  const ready = model.phase === 'ready' && !model.recoveryRequired;
  return (
    <fieldset className="native-knowledge-sync" disabled={disabled}>
      <legend>{t('nativeSync.title')}</legend>
      {model.recoveryRequired ? (
        <p role="alert">{t('nativeSync.syncUncertain')}</p>
      ) : model.error ? (
        <p role="alert">{t(`nativeSync.${model.error}`)}</p>
      ) : null}
      {busy ? <p role="status">{t('nativeSync.working')}</p> : null}
      {model.status ? (
        <>
          <p>
            {t('nativeSync.pendingChanges')}: {model.status.pending_changes}
          </p>
          <p>
            {t('nativeSync.pendingGraphChanges')}: {model.status.pending_graph_changes}
          </p>
          {model.status.link ? (
            <>
              <p>{t('nativeSync.linkConfigured')}</p>
              <dl>
                <dt>{t('nativeSync.remoteTenant')}</dt>
                <dd>{model.status.link.remote_tenant_id}</dd>
                <dt>{t('nativeSync.remoteProject')}</dt>
                <dd>{model.status.link.remote_project_id}</dd>
                <dt>{t('nativeSync.remoteActor')}</dt>
                <dd>{model.status.link.remote_actor_id}</dd>
              </dl>
            </>
          ) : (
            <p>{t('nativeSync.linkUnavailable')}</p>
          )}
        </>
      ) : null}
      <div className="native-knowledge-actions">
        <button type="button" disabled={busy} onClick={() => void controller.refresh()}>
          {t('common.refresh')}
        </button>
        {allowed('sync_pull') && allowed('sync_status') ? (
          <button
            type="button"
            disabled={!ready || !model.status?.link || !connectionReady}
            onClick={() => void controller.sync('sync_pull')}
          >
            {t('nativeSync.pull')}
          </button>
        ) : null}
        {allowed('sync_push') && allowed('sync_status') ? (
          <button
            type="button"
            disabled={!ready || !model.status?.link || !connectionReady}
            onClick={() => void controller.sync('sync_push')}
          >
            {t('nativeSync.push')}
          </button>
        ) : null}
      </div>
      {model.result ? (
        <details>
          <summary>{t('nativeSync.lastResult')}</summary>
          <pre>{JSON.stringify(model.result, null, 2)}</pre>
        </details>
      ) : null}
      {allowed('sync_unbind') && model.status?.link ? (
        <section className="native-knowledge-unbind">
          {unbindOpen ? (
            <div role="group" aria-label={t('nativeSync.unbindTitle')}>
              <p>{t('nativeSync.unbindHelp')}</p>
              <button
                type="button"
                disabled={busy}
                onClick={() => void controller.unbind('keep')}
              >
                {t('nativeSync.unbindKeep')}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void controller.unbind('delete')}
              >
                {t('nativeSync.unbindDelete')}
              </button>
              <button type="button" disabled={busy} onClick={() => setUnbindOpen(false)}>
                {t('nativeSync.unbindCancel')}
              </button>
            </div>
          ) : (
            <button type="button" disabled={!ready} onClick={() => setUnbindOpen(true)}>
              {t('nativeSync.unbind')}
            </button>
          )}
        </section>
      ) : null}
      {allowed('sync_outbox') && model.outbox ? (
        <section>
          <h3>{t('nativeSync.outbox')}</h3>
          <ul>
            {model.outbox.items.map((item) => (
              <li key={item.change_id}>
                {item.local_change.memory.title} · {item.local_change.sequence}
                {allowed('cloud_conflict_context') ? (
                  <button
                    type="button"
                    disabled={!ready}
                    onClick={() =>
                      void conflicts.open({
                        kind: 'push',
                        localSequence: item.local_change.sequence,
                      })
                    }
                  >
                    {t('nativeSync.inspectPush')}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
          {model.outboxHasMore ? (
            <button type="button" disabled={!ready} onClick={() => void controller.moreOutbox()}>
              {t('nativeSync.more')}
            </button>
          ) : null}
        </section>
      ) : null}
      {allowed('pull_conflicts') ? (
        <section>
          <h3>{t('nativeSync.pullConflicts')}</h3>
          <ul>
            {model.pullConflicts.map((item) => (
              <li key={item.sequence}>
                {item.memory_id} · {item.sequence}
                {allowed('pull_conflict_context') ? (
                  <button
                    type="button"
                    disabled={!ready}
                    onClick={() => void conflicts.open({ kind: 'pull', id: item.memory_id })}
                  >
                    {t('nativeSync.review')}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {allowed('push_conflicts') ? (
        <section>
          <h3>{t('nativeSync.pushConflicts')}</h3>
          <ul>
            {model.pushConflicts.map((item) => (
              <li key={item.id}>
                {item.memory_id} · {item.id}
                <details>
                  <summary>{t('nativeSync.conflictRecord')}</summary>
                  <pre>{JSON.stringify(item, null, 2)}</pre>
                </details>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {allowed('pending_resolutions') && model.pending ? (
        <section>
          <h3>{t('nativeSync.pendingResolutions')}</h3>
          <ul>
            {model.pending.items.map((item) => (
              <li key={item.resolution_id}>
                {item.resolution_id}
                <span>
                  {t(
                    item.receipt ? 'nativeSync.pendingReconciliation' : 'nativeSync.pendingReceipt',
                  )}
                </span>
                {allowed('resolution') ? (
                  <button
                    type="button"
                    disabled={!ready}
                    onClick={() =>
                      void conflicts.open({ kind: 'resolution', id: item.resolution_id })
                    }
                  >
                    {t('nativeSync.review')}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
          {model.pending.next_before_resolution_id ? (
            <button type="button" disabled={!ready} onClick={() => void controller.morePending()}>
              {t('nativeSync.more')}
            </button>
          ) : null}
        </section>
      ) : null}
      {allowed('resolutions') ? (
        <section>
          <h3>{t('nativeSync.resolutionHistory')}</h3>
          <ul>
            {model.resolutions.map((item) => (
              <li key={item.resolution_id}>
                {item.resolution_id}
                {allowed('resolution') ? (
                  <button
                    type="button"
                    disabled={!ready}
                    onClick={() =>
                      void conflicts.open({ kind: 'resolution', id: item.resolution_id })
                    }
                  >
                    {t('nativeSync.review')}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <p>{t('nativeSync.pageLimit')}</p>
    </fieldset>
  );
}
