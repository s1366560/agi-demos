import { useI18n } from '../../i18n';
import type { ProjectKnowledgeViewModel } from './projectKnowledgePresentationModel';

export function ProjectKnowledgePage({
  model,
  onRetry,
}: Readonly<{ model: ProjectKnowledgeViewModel; onRetry: () => void }>) {
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
      {model.retryVisible ? (
        <button type="button" onClick={onRetry}>
          {t('common.retry')}
        </button>
      ) : null}
    </section>
  );
}
