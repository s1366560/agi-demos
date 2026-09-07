import { useI18n } from '../../i18n';
import type { ProjectKnowledgeViewModel } from './projectKnowledgePresentationModel';

export function ProjectKnowledgePage({
  model,
  onRetry,
  onPageChange,
}: Readonly<{
  model: ProjectKnowledgeViewModel;
  onRetry: () => void;
  onPageChange?: (page: number) => void;
}>) {
  const { t } = useI18n();
  return (
    <section data-authority={model.scope.authority} data-state={model.state}>
      <header>
        <h1>
          <code>{model.routeId}</code>
        </h1>
        <output>{model.total}</output>
      </header>
      {model.reasonCode ? <code>{model.reasonCode}</code> : null}
      {model.items.length > 0 ? (
        <ol>
          {model.items.map((item) => (
            <li key={item.id} data-kind={item.kind}>
              <article>
                <h2>{item.title}</h2>
                {item.detail ? <p>{item.detail}</p> : null}
              </article>
            </li>
          ))}
        </ol>
      ) : null}
      {model.pagination && onPageChange ? (
        <nav aria-label={t('common.pagination')}>
          <button
            type="button"
            disabled={model.pagination.page <= 1}
            onClick={() => onPageChange(model.pagination!.page - 1)}
          >
            {t('common.previousPage')}
          </button>
          <output aria-live="polite">
            {model.pagination.page} / {model.pagination.pages}
          </output>
          <button
            type="button"
            disabled={model.pagination.page >= model.pagination.pages}
            onClick={() => onPageChange(model.pagination!.page + 1)}
          >
            {t('common.nextPage')}
          </button>
        </nav>
      ) : null}
      {model.retryVisible ? (
        <button type="button" onClick={onRetry}>
          {t('common.retry')}
        </button>
      ) : null}
    </section>
  );
}
