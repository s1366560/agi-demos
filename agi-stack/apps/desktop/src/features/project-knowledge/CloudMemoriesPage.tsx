import { useI18n } from '../../i18n';
import { CloudMemoryEditor } from './CloudMemoryEditor';
import type { CloudMemoriesController, CloudMemoriesModel } from './cloudMemoriesController';

export function CloudMemoriesUnavailable() {
  const { t } = useI18n();
  return (
    <section className="cloud-memories-page">
      <h1>{t('cloudMemories.title')}</h1>
      <p>{t('cloudMemories.unavailable')}</p>
    </section>
  );
}
export function CloudMemoriesPage({
  model,
  controller,
}: Readonly<{ model: CloudMemoriesModel; controller: CloudMemoriesController }>) {
  const { t } = useI18n();
  if (model.phase === 'unavailable') return <CloudMemoriesUnavailable />;
  const locked =
    ['saving', 'uncertain', 'loading'].includes(model.phase) || model.listState === 'loading';
  const list = model.list;
  const lastPage =
    list?.total === null
      ? null
      : Math.max(1, Math.ceil((list?.total ?? 0) / (list?.pageSize ?? 50)));
  const hasNext = list && (list.total === null ? list.hasMore : list.page < lastPage!);
  return (
    <section className="cloud-memories-page" data-authority="cloud">
      <header>
        <h1>{t('cloudMemories.title')}</h1>
        {model.canCreate ? (
          <button type="button" disabled={locked} onClick={controller.create}>
            {t('cloudMemories.new')}
          </button>
        ) : null}
        <button
          type="button"
          disabled={locked}
          onClick={() => void controller.loadPage(list?.page ?? 1)}
        >
          {t('common.refresh')}
        </button>
      </header>
      {model.listState === 'loading' ? <p role="status">{t('cloudMemories.loadingList')}</p> : null}
      {model.listState === 'error' ? <p role="alert">{t('cloudMemories.listFailed')}</p> : null}
      {list?.memories.length === 0 ? <p>{t('cloudMemories.empty')}</p> : null}
      <ol>
        {list?.memories.map((memory) => (
          <li key={memory.id}>
            <article>
              <h2>{memory.title}</h2>
              <p>{memory.content}</p>
              <p>
                {t('cloudMemories.revision')}: {memory.version}
              </p>
            </article>
            <div className="cloud-memories-actions">
              {controller.canView() ? (
                <button
                  type="button"
                  disabled={locked}
                  onClick={() => void controller.open(memory.id, 'view')}
                >
                  {t('cloudMemories.view')}
                </button>
              ) : null}
              {controller.canUpdate(memory) ? (
                <button
                  type="button"
                  disabled={locked}
                  onClick={() => void controller.open(memory.id, 'edit')}
                >
                  {t('cloudMemories.edit')}
                </button>
              ) : null}
              {controller.canDelete(memory) ? (
                <button
                  type="button"
                  disabled={locked}
                  onClick={() => void controller.open(memory.id, 'delete')}
                >
                  {t('cloudMemories.delete')}
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
      {list ? (
        <nav aria-label={t('cloudMemories.pagination')}>
          <button
            type="button"
            disabled={locked || list.page <= 1}
            onClick={() => void controller.goToPage(list.page - 1)}
          >
            {t('cloudMemories.previous')}
          </button>
          <span>
            {t('cloudMemories.page')} {list.page}
            {lastPage !== null ? ` / ${lastPage}` : ''}
          </span>
          <button
            type="button"
            disabled={locked || !hasNext}
            onClick={() => void controller.goToPage(list.page + 1)}
          >
            {t('cloudMemories.next')}
          </button>
        </nav>
      ) : null}
      <CloudMemoryEditor model={model} controller={controller} />
    </section>
  );
}
