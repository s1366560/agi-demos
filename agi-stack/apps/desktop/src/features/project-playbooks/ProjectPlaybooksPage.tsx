import { useI18n } from '../../i18n';
import type { ProjectPlaybooksViewModel } from './projectPlaybooksController';

export function ProjectPlaybooksPage({
  model,
  onRetry,
}: Readonly<{ model: ProjectPlaybooksViewModel; onRetry: () => void }>) {
  const { t } = useI18n();
  return (
    <section data-route-id="project-playbooks" data-state={model.state}>
      <header>
        <div>
          <h1>{t('projectPlaybooks.title')}</h1>
          <p>{t('projectPlaybooks.subtitle')}</p>
        </div>
        <button type="button" onClick={onRetry}>
          {t('common.refresh')}
        </button>
      </header>
      {model.reasonCode ? (
        <p role="alert">{t(`projectPlaybooks.reason.${model.reasonCode}`)}</p>
      ) : null}
      {model.state === 'loading' ? <p>{t('common.loading')}</p> : null}
      {model.state === 'empty' ? <p>{t('projectPlaybooks.empty')}</p> : null}
      {model.state === 'forbidden' || model.state === 'unavailable' || model.state === 'error' ? (
        model.retryVisible ? (
          <button type="button" onClick={onRetry}>
            {t('common.retry')}
          </button>
        ) : null
      ) : (
        <>
          <section>
            <header>
              <h2>{t('projectPlaybooks.playbooks')}</h2>
              <output>{model.playbooks.length}</output>
            </header>
            {model.playbooks.length > 0 ? (
              <ul>
                {model.playbooks.map((playbook) => (
                  <li key={playbook.id}>
                    <article>
                      <header>
                        <h3>{playbook.name}</h3>
                        <code>{playbook.status}</code>
                      </header>
                      <p>
                        {t('projectPlaybooks.hits')}: {playbook.hitCount}
                      </p>
                      {playbook.trigger.description ? (
                        <p>
                          <strong>{t('projectPlaybooks.trigger')}:</strong>{' '}
                          {playbook.trigger.description}
                        </p>
                      ) : null}
                      {playbook.steps.length > 0 ? (
                        <ol>
                          {playbook.steps.map((step) => (
                            <li key={`${playbook.id}:${step.order}`}>
                              <strong>
                                {t('projectPlaybooks.step')} {step.order}:
                              </strong>{' '}
                              {step.instruction}
                              {step.rationale ? <p>{step.rationale}</p> : null}
                            </li>
                          ))}
                        </ol>
                      ) : null}
                    </article>
                  </li>
                ))}
              </ul>
            ) : (
              <p>{t('projectPlaybooks.noPlaybooks')}</p>
            )}
          </section>
          <section>
            <header>
              <h2>{t('projectPlaybooks.verdicts')}</h2>
              <output>{model.verdicts.length}</output>
            </header>
            {model.verdicts.length > 0 ? (
              <ol>
                {model.verdicts.map((verdict) => (
                  <li key={verdict.id}>
                    <article>
                      <header>
                        <code>{t(`projectPlaybooks.verdict.${verdict.action}`)}</code>
                        <time>{verdict.createdAt}</time>
                      </header>
                      <p>{verdict.rationale || t('projectPlaybooks.noRationale')}</p>
                    </article>
                  </li>
                ))}
              </ol>
            ) : (
              <p>{t('projectPlaybooks.noVerdicts')}</p>
            )}
          </section>
        </>
      )}
    </section>
  );
}
