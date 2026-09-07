import { useI18n } from '../../i18n';
import { NativeMemoryEditor } from './NativeMemoryEditor';
import type { NativeMemoriesController, NativeMemoriesModel } from './nativeMemoriesController';
import type { ProjectKnowledgeViewModel } from './projectKnowledgePresentationModel';

export function NativeMemoriesUnavailable() {
  const { t } = useI18n();
  return (
    <section className="native-memories-page" data-authority="local" data-state="unavailable">
      <h1>{t('nativeMemories.title')}</h1>
      <p>{t('nativeMemories.unavailable')}</p>
    </section>
  );
}

export function NativeMemoriesPage({
  list,
  editor,
  controller,
  onReload,
  onPageChange,
}: Readonly<{
  list: ProjectKnowledgeViewModel;
  editor: NativeMemoriesModel;
  controller: NativeMemoriesController;
  onReload: () => void;
  onPageChange: (page: number) => void;
}>) {
  const { t } = useI18n();
  const allowed = (action: string) => editor.allowedActions.includes(action);
  const locked = editor.phase === 'saving' || editor.phase === 'uncertain';
  if (editor.phase === 'unavailable') return <NativeMemoriesUnavailable />;
  return (
    <section className="native-memories-page" data-authority="local" data-state={editor.phase}>
      <header>
        <h1>{t('nativeMemories.title')}</h1>
        {allowed('create') ? (
          <button type="button" disabled={locked} onClick={() => void controller.create()}>
            {t('nativeMemories.new')}
          </button>
        ) : null}
        {allowed('list') ? (
          <button type="button" disabled={locked} onClick={onReload}>
            {t('common.refresh')}
          </button>
        ) : null}
      </header>
      {allowed('list') ? (
        <>
          {list.state === 'loading' ? <p role="status">{t('nativeMemories.loading')}</p> : null}
          {list.state === 'empty' ? <p>{t('nativeMemories.empty')}</p> : null}
          {['error', 'forbidden', 'unavailable'].includes(list.state) ? (
            <p role="alert">{t('nativeMemories.failed')}</p>
          ) : null}
          <ol>
            {list.items.map((item) => (
              <li key={item.id}>
                <article>
                  <h2>{item.title}</h2>
                  {item.detail ? <p>{item.detail}</p> : null}
                </article>
                {allowed('view') ? (
                  <div>
                    <button
                      type="button"
                      disabled={locked}
                      onClick={() => void controller.open(item.id, 'view')}
                    >
                      {t('nativeMemories.view')}
                    </button>
                    {allowed('update') ? (
                      <button
                        type="button"
                        disabled={locked}
                        onClick={() => void controller.open(item.id, 'edit')}
                      >
                        {t('nativeMemories.edit')}
                      </button>
                    ) : null}
                    {allowed('delete') ? (
                      <button
                        type="button"
                        disabled={locked}
                        onClick={() => void controller.open(item.id, 'delete')}
                      >
                        {t('nativeMemories.delete')}
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </li>
            ))}
          </ol>
          {list.pagination ? (
            <nav aria-label={t('common.pagination')}>
              <button
                type="button"
                disabled={locked || list.pagination.page <= 1}
                onClick={() => onPageChange(list.pagination!.page - 1)}
              >
                {t('common.previousPage')}
              </button>
              <output aria-live="polite">{list.pagination.page}</output>
              <button
                type="button"
                disabled={
                  locked ||
                  (list.pagination.pages === null
                    ? !list.pagination.hasMore
                    : list.pagination.page >= list.pagination.pages)
                }
                onClick={() => onPageChange(list.pagination!.page + 1)}
              >
                {t('common.nextPage')}
              </button>
            </nav>
          ) : null}
        </>
      ) : null}
      <NativeMemoryEditor model={editor} controller={controller} />
    </section>
  );
}
