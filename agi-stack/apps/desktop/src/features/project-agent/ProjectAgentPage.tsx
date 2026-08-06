import { useI18n } from '../../i18n';
import type { ProjectAgentViewModel } from './projectAgentPresentationModel';

export function ProjectAgentPage({
  model,
  onRetry,
}: Readonly<{ model: ProjectAgentViewModel; onRetry: () => void }>) {
  const { t } = useI18n();
  return (
    <section
      data-authority={model.scope.authority}
      data-route-id={model.routeId}
      data-state={model.state}
    >
      <header>
        <h1>
          <code>{model.routeId}</code>
        </h1>
        <output>{model.total}</output>
      </header>
      {model.reasonCode ? <code>{model.reasonCode}</code> : null}
      {Object.entries(model.metrics).map(([name, value]) => (
        <output key={name} data-metric={name}>
          {value}
        </output>
      ))}
      {model.items.length > 0 ? (
        <ol>
          {model.items.map((item) => (
            <li key={item.id} data-status={item.status}>
              <article>
                <h2>{item.title}</h2>
                <p>{item.detail}</p>
                <time dateTime={item.createdAt}>{item.createdAt}</time>
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
