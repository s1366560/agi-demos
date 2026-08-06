import { useI18n } from '../../i18n';
import type { ProjectAdministrationViewModelBase } from './projectAdministrationPresentationModel';

export function ProjectAdministrationPage({
  model,
  onRetry,
}: Readonly<{
  model: ProjectAdministrationViewModelBase;
  onRetry: () => void;
}>) {
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
      </header>
      {model.reasonCode ? <code>{model.reasonCode}</code> : null}
      {model.items.length > 0 ? (
        <ol>
          {model.items.map((item) => (
            <li key={item.id}>
              <article>
                <h2>{item.title}</h2>
                <p>{item.detail}</p>
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
