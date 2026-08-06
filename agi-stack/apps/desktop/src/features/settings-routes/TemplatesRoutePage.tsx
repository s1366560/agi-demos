import { useMemo, useState } from 'react';
import { DownloadIcon, MagnifyingGlassIcon, ReloadIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { TemplatesRouteDetail } from './templatesRouteClient';
import type { TemplatesRouteController } from './templatesRouteController';
import type { TemplatesRoutePresentationModel } from './templatesRoutePresentationModel';
import { useNativeRouteAction } from './useNativeRouteAction';

export function TemplatesRoutePage({
  model,
  controller,
}: Readonly<{
  model: TemplatesRoutePresentationModel;
  controller: TemplatesRouteController;
}>) {
  const { t } = useI18n();
  const observation = model.observation;
  const action = useNativeRouteAction('template_marketplace_action_failed');
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [detail, setDetail] = useState<TemplatesRouteDetail | null>(null);
  const [seeded, setSeeded] = useState<number | null>(null);
  const allowed = useMemo(
    () => new Set(observation?.allowedActions ?? []),
    [observation?.allowedActions],
  );
  if (!observation) return <ContractGap capability={model.capability} />;
  const busy = action.busyAction !== null;

  const applyFilters = (): void => {
    void action.run('filter', () =>
      controller.filter(model.scope, {
        page: 1,
        pageSize: observation.pageSize,
        search,
        category,
      }),
    );
  };

  return (
    <main className="settings-page" data-route-content="templates" data-state={model.state}>
      <header className="settings-page-heading">
        <div>
          <span>{t('settings.subagentsEyebrow')}</span>
          <h1>{t('settings.subagentLibrary.action')}</h1>
          <p>{t('settings.subagentLibrary.description')}</p>
        </div>
        <div>
          <button
            type="button"
            data-action="seed"
            disabled={busy || !allowed.has('seed')}
            onClick={() =>
              void action
                .run('seed', () => controller.seed(model.scope))
                .then((result) => {
                  if (result.ok) setSeeded(result.value);
                })
            }
          >
            {action.busyAction === 'seed' ? <ReloadIcon /> : null}
            {t('common.create')}
          </button>
          <button
            type="button"
            data-action="retry"
            disabled={busy || !allowed.has('retry')}
            onClick={() => void controller.retry()}
          >
            <ReloadIcon /> {t('common.refresh')}
          </button>
        </div>
      </header>

      {action.reasonCode ? <code role="alert">{action.reasonCode}</code> : null}
      {seeded !== null ? <output>{seeded}</output> : null}

      <form
        className="settings-panel"
        data-action="search"
        onSubmit={(event) => {
          event.preventDefault();
          applyFilters();
        }}
      >
        <label>
          <span>{t('chat.templates.search')}</span>
          <input
            type="search"
            value={search}
            placeholder={t('chat.templates.searchPlaceholder')}
            disabled={busy || !allowed.has('search')}
            onChange={(event) => setSearch(event.currentTarget.value)}
          />
        </label>
        <label data-action="filter">
          <span>{t('chat.templates.categories')}</span>
          <select
            value={category}
            disabled={busy || !allowed.has('filter')}
            onChange={(event) => setCategory(event.currentTarget.value)}
          >
            <option value="">{t('chat.templates.category.all')}</option>
            {observation.categories.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={busy || !allowed.has('search')}>
          <MagnifyingGlassIcon /> {t('chat.templates.search')}
        </button>
      </form>

      <section className="settings-panel" data-action="list">
        <header>
          <strong>{t('settings.subagentLibrary.action')}</strong>
          <span>
            {t('chat.templates.visibleCount', {
              count: observation.templates.length,
              total: observation.total,
            })}
          </span>
        </header>
        {observation.templates.length === 0 ? (
          <div>
            <strong>{t('chat.templates.emptyTitle')}</strong>
            <p>{t('chat.templates.emptyDescription')}</p>
          </div>
        ) : (
          <div className="settings-list">
            {observation.templates.map((template) => (
              <article key={template.id}>
                <div>
                  <strong>{template.display_name || template.name}</strong>
                  <p>{template.description}</p>
                  <code>{template.category}</code>
                  <small>
                    {t('settings.subagentLibrary.installCount', {
                      count: template.install_count,
                    })}
                  </small>
                </div>
                <div>
                  <button
                    type="button"
                    data-action="view-detail"
                    disabled={busy || !allowed.has('view-detail')}
                    onClick={() =>
                      void action
                        .run(`detail:${template.id}`, () =>
                          controller.get(model.scope, template.id),
                        )
                        .then((result) => {
                          if (result.ok) setDetail(result.value);
                        })
                    }
                  >
                    {t('chat.templates.preview')}
                  </button>
                  <button
                    type="button"
                    data-action="install"
                    disabled={busy || !allowed.has('install')}
                    onClick={() =>
                      void action.run(`install:${template.id}`, () =>
                        controller.install(model.scope, template.id),
                      )
                    }
                  >
                    <DownloadIcon /> {t('settings.subagentLibrary.install')}
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {detail ? (
        <section className="settings-panel" data-action="view-detail">
          <header>
            <div>
              <strong>{detail.display_name || detail.name}</strong>
              <code>{detail.version}</code>
            </div>
            <button type="button" onClick={() => setDetail(null)}>
              {t('common.close')}
            </button>
          </header>
          <p>{detail.description}</p>
          <dl>
            <div>
              <dt>{t('settings.subagentEditor.model')}</dt>
              <dd>{detail.model}</dd>
            </div>
            <div>
              <dt>{t('settings.subagentEditor.maxTokens')}</dt>
              <dd>{detail.max_tokens}</dd>
            </div>
            <div>
              <dt>{t('settings.subagentEditor.maxIterations')}</dt>
              <dd>{detail.max_iterations}</dd>
            </div>
          </dl>
          <pre>{detail.system_prompt}</pre>
        </section>
      ) : null}
    </main>
  );
}

function ContractGap({ capability }: Readonly<{ capability: string }>) {
  return (
    <section className="desktop-production-route-boundary" data-state="unavailable">
      <code>{capability}:presentation_observation_unavailable</code>
    </section>
  );
}
