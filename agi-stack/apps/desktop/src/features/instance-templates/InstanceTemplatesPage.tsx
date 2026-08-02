import { useState, type ChangeEvent, type FormEvent } from 'react';

import { useI18n } from '../../i18n';
import type {
  InstanceTemplateCreateInput,
  InstanceTemplateSummary,
  InstanceTemplatesModel,
  InstanceTemplatesQuery,
} from './instanceTemplatesTypes';
import './InstanceTemplatesPage.css';

export function InstanceTemplatesPage({
  model,
  onRetry,
  onQueryChange,
  onFiltersChange,
  onInspect,
  onCloseDetail,
  onCreate,
  onDelete,
  onPublish,
  onClone,
}: Readonly<{
  model: InstanceTemplatesModel;
  onRetry(): void;
  onQueryChange(query: InstanceTemplatesQuery): void;
  onFiltersChange(query: InstanceTemplatesQuery): void;
  onInspect(templateId: string): Promise<void>;
  onCloseDetail(): void;
  onCreate(input: InstanceTemplateCreateInput): Promise<void>;
  onDelete(templateId: string): Promise<void>;
  onPublish(templateId: string): Promise<void>;
  onClone(templateId: string, newName: string): Promise<void>;
}>) {
  const { t } = useI18n();
  const [createOpen, setCreateOpen] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);
  const loading = model.state === 'loading';
  const submitting = model.mutationState === 'submitting';
  const pageCount = Math.max(1, Math.ceil(model.total / model.query.pageSize));
  const canCreate = model.allowedActions.includes('create');

  return (
    <section
      className="instance-templates-page"
      aria-labelledby="instance-templates-title"
    >
      <header className="instance-templates-header">
        <div>
          <span>{t('instanceTemplates.eyebrow')}</span>
          <h1 id="instance-templates-title">{t('instanceTemplates.title')}</h1>
          <p>{t('instanceTemplates.subtitle')}</p>
        </div>
        <div>
          <button type="button" onClick={onRetry} disabled={loading}>
            {t('common.refresh')}
          </button>
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            disabled={!canCreate || submitting}
          >
            {t('instanceTemplates.create')}
          </button>
        </div>
      </header>

      <div className="instance-templates-scope">
        <span>{t('instanceTemplates.scope')}</span>
        <strong>{model.scope.tenantId}</strong>
        <code>{model.authority}</code>
        <small>{t(`instanceTemplates.state.${model.state}`)}</small>
      </div>

      <article
        className="instance-templates-deviation"
        data-authority={model.authority}
      >
        <div>
          <strong>
            {t(`instanceTemplates.deviation.${model.authority}.title`)}
          </strong>
          <p>{t(`instanceTemplates.deviation.${model.authority}.description`)}</p>
        </div>
        <code>{model.reasonCode}</code>
      </article>

      {operationError || model.mutationReasonCode ? (
        <div className="instance-templates-operation-error" role="alert">
          <code>{operationError ?? model.mutationReasonCode}</code>
          <button
            type="button"
            onClick={() => setOperationError(null)}
          >
            {t('common.dismiss')}
          </button>
        </div>
      ) : null}

      <article className="instance-templates-inventory">
        <header>
          <div>
            <h2>{t('instanceTemplates.inventory.title')}</h2>
            <p>
              {t('instanceTemplates.inventory.count', {
                count: model.visibleTemplates.length,
              })}
            </p>
          </div>
          <TemplateFilters
            model={model}
            disabled={loading || model.authority === 'local'}
            onChange={onFiltersChange}
          />
        </header>

        {model.state === 'loading' && model.templates.length === 0 ? (
          <StateNotice model={model} onRetry={onRetry} />
        ) : model.state === 'conflict' ||
          model.state === 'forbidden' ||
          model.state === 'unavailable' ||
          model.state === 'error' ? (
          <StateNotice model={model} onRetry={onRetry} />
        ) : model.visibleTemplates.length === 0 && !loading ? (
          <div className="instance-templates-empty">
            <h3>{t('instanceTemplates.empty.title')}</h3>
            <p>{t('instanceTemplates.empty.description')}</p>
          </div>
        ) : (
          <TemplateTable
            templates={model.visibleTemplates}
            submitting={submitting}
            onInspect={onInspect}
            onDelete={onDelete}
            onPublish={onPublish}
            onClone={onClone}
            onError={setOperationError}
          />
        )}

        <footer className="instance-templates-pagination">
          <span>
            {t('instanceTemplates.pagination', {
              page: model.query.page,
              pages: pageCount,
            })}
          </span>
          <div>
            <button
              type="button"
              disabled={
                loading || model.query.page <= 1 || model.authority === 'local'
              }
              onClick={() => onQueryChange({ page: model.query.page - 1 })}
            >
              {t('instanceTemplates.previous')}
            </button>
            <button
              type="button"
              disabled={
                loading ||
                model.authority === 'local' ||
                model.query.page >= pageCount
              }
              onClick={() => onQueryChange({ page: model.query.page + 1 })}
            >
              {t('instanceTemplates.next')}
            </button>
          </div>
        </footer>
      </article>

      {createOpen ? (
        <CreateTemplateDialog
          submitting={submitting}
          onClose={() => setCreateOpen(false)}
          onCreate={async (input) => {
            setOperationError(null);
            try {
              await onCreate(input);
              setCreateOpen(false);
            } catch (error) {
              setOperationError(errorCode(error));
            }
          }}
        />
      ) : null}

      {model.detailState !== 'idle' ? (
        <TemplateDetailDialog
          model={model}
          submitting={submitting}
          onClose={onCloseDetail}
          onDelete={onDelete}
          onPublish={onPublish}
          onClone={onClone}
          onError={setOperationError}
        />
      ) : null}
    </section>
  );
}

function TemplateFilters({
  model,
  disabled,
  onChange,
}: Readonly<{
  model: InstanceTemplatesModel;
  disabled: boolean;
  onChange(query: InstanceTemplatesQuery): void;
}>) {
  const { t } = useI18n();
  return (
    <div className="instance-templates-filters">
      <label>
        <span>{t('instanceTemplates.search')}</span>
        <input
          type="search"
          value={model.query.search}
          onChange={(event: ChangeEvent<HTMLInputElement>) =>
            onChange({ search: event.target.value })
          }
          disabled={disabled}
        />
      </label>
      <label>
        <span>{t('instanceTemplates.statusFilter')}</span>
        <select
          value={model.query.status}
          onChange={(event: ChangeEvent<HTMLSelectElement>) =>
            onChange({
              status: event.target.value as 'all' | 'published' | 'draft',
            })
          }
          disabled={disabled}
        >
          {['all', 'published', 'draft'].map((status) => (
            <option value={status} key={status}>
              {t(`instanceTemplates.status.${status}`)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function TemplateTable({
  templates,
  submitting,
  onInspect,
  onDelete,
  onPublish,
  onClone,
  onError,
}: Readonly<{
  templates: readonly InstanceTemplateSummary[];
  submitting: boolean;
  onInspect(templateId: string): Promise<void>;
  onDelete(templateId: string): Promise<void>;
  onPublish(templateId: string): Promise<void>;
  onClone(templateId: string, newName: string): Promise<void>;
  onError(reasonCode: string): void;
}>) {
  const { t } = useI18n();
  return (
    <div className="instance-templates-table-scroll">
      <table>
        <thead>
          <tr>
            {['name', 'status', 'version', 'installs', 'created', 'actions'].map(
              (column) => (
                <th key={column}>{t(`instanceTemplates.column.${column}`)}</th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {templates.map((template) => (
            <tr key={template.id}>
              <td>
                <strong>{template.name}</strong>
                <code>{template.slug}</code>
                <small>{template.description ?? '—'}</small>
              </td>
              <td>
                <span
                  className="instance-templates-status"
                  data-state={template.isPublished ? 'published' : 'draft'}
                >
                  {t(
                    `instanceTemplates.status.${
                      template.isPublished ? 'published' : 'draft'
                    }`,
                  )}
                </span>
              </td>
              <td>{template.imageVersion ?? '—'}</td>
              <td>{template.installCount}</td>
              <td>{template.createdAt}</td>
              <td>
                <div className="instance-templates-actions">
                  <button
                    type="button"
                    disabled={submitting}
                    onClick={() =>
                      void onInspect(template.id).catch((error) =>
                        onError(errorCode(error)),
                      )
                    }
                  >
                    {t('instanceTemplates.view')}
                  </button>
                  <button
                    type="button"
                    disabled={submitting}
                    onClick={() =>
                      void onClone(
                        template.id,
                        t('instanceTemplates.copyName', { name: template.name }),
                      ).catch((error) => onError(errorCode(error)))
                    }
                  >
                    {t('instanceTemplates.clone')}
                  </button>
                  {!template.isPublished ? (
                    <button
                      type="button"
                      disabled={submitting}
                      onClick={() =>
                        void onPublish(template.id).catch((error) =>
                          onError(errorCode(error)),
                        )
                      }
                    >
                      {t('instanceTemplates.publish')}
                    </button>
                  ) : null}
                  <DeleteControl
                    templateId={template.id}
                    submitting={submitting}
                    onDelete={onDelete}
                    onError={onError}
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DeleteControl({
  templateId,
  submitting,
  onDelete,
  onError,
}: Readonly<{
  templateId: string;
  submitting: boolean;
  onDelete(templateId: string): Promise<void>;
  onError(reasonCode: string): void;
}>) {
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);
  if (!confirming) {
    return (
      <button
        type="button"
        disabled={submitting}
        onClick={() => setConfirming(true)}
      >
        {t('common.delete')}
      </button>
    );
  }
  return (
    <>
      <button
        type="button"
        className="danger"
        disabled={submitting}
        onClick={() =>
          void onDelete(templateId)
            .then(() => setConfirming(false))
            .catch((error) => onError(errorCode(error)))
        }
      >
        {t('instanceTemplates.confirmDelete')}
      </button>
      <button
        type="button"
        disabled={submitting}
        onClick={() => setConfirming(false)}
      >
        {t('common.cancel')}
      </button>
    </>
  );
}

function CreateTemplateDialog({
  submitting,
  onClose,
  onCreate,
}: Readonly<{
  submitting: boolean;
  onClose(): void;
  onCreate(input: InstanceTemplateCreateInput): Promise<void>;
}>) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [defaultConfig, setDefaultConfig] = useState('{}');
  const [validationError, setValidationError] = useState<string | null>(null);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      const parsed = JSON.parse(defaultConfig) as unknown;
      if (!isRecord(parsed)) {
        setValidationError('instance_templates_default_config_invalid');
        return;
      }
      setValidationError(null);
      void onCreate({
        name: name.trim(),
        slug: slugify(name),
        description: description.trim() || null,
        defaultConfig: parsed,
      });
    } catch {
      setValidationError('instance_templates_default_config_invalid');
    }
  };
  return (
    <div className="instance-templates-dialog-backdrop">
      <aside role="dialog" aria-modal="true" aria-labelledby="create-template-title">
        <header>
          <h2 id="create-template-title">{t('instanceTemplates.create')}</h2>
          <button type="button" onClick={onClose} disabled={submitting}>
            {t('common.close')}
          </button>
        </header>
        <form onSubmit={submit}>
          <label>
            <span>{t('instanceTemplates.field.name')}</span>
            <input
              required
              maxLength={200}
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={submitting}
            />
          </label>
          <label>
            <span>{t('instanceTemplates.field.description')}</span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              disabled={submitting}
            />
          </label>
          <label>
            <span>{t('instanceTemplates.field.defaultConfig')}</span>
            <textarea
              value={defaultConfig}
              onChange={(event) => setDefaultConfig(event.target.value)}
              disabled={submitting}
            />
          </label>
          {validationError ? <code>{validationError}</code> : null}
          <button
            type="submit"
            disabled={submitting || name.trim().length === 0}
          >
            {t('common.create')}
          </button>
        </form>
      </aside>
    </div>
  );
}

function TemplateDetailDialog({
  model,
  submitting,
  onClose,
  onDelete,
  onPublish,
  onClone,
  onError,
}: Readonly<{
  model: InstanceTemplatesModel;
  submitting: boolean;
  onClose(): void;
  onDelete(templateId: string): Promise<void>;
  onPublish(templateId: string): Promise<void>;
  onClone(templateId: string, newName: string): Promise<void>;
  onError(reasonCode: string): void;
}>) {
  const { t } = useI18n();
  const template = model.selectedTemplate;
  return (
    <div className="instance-templates-dialog-backdrop">
      <aside role="dialog" aria-modal="true" aria-labelledby="template-detail-title">
        <header>
          <h2 id="template-detail-title">
            {template?.name ?? t('instanceTemplates.detail.title')}
          </h2>
          <button type="button" onClick={onClose}>
            {t('common.close')}
          </button>
        </header>
        {model.detailState === 'loading' ? (
          <p>{t('instanceTemplates.detail.loading')}</p>
        ) : template ? (
          <>
            <dl>
              <DetailRow label={t('instanceTemplates.field.slug')} value={template.slug} />
              <DetailRow
                label={t('instanceTemplates.field.status')}
                value={t(
                  `instanceTemplates.status.${
                    template.isPublished ? 'published' : 'draft'
                  }`,
                )}
              />
              <DetailRow
                label={t('instanceTemplates.field.imageVersion')}
                value={template.imageVersion ?? '—'}
              />
              <DetailRow
                label={t('instanceTemplates.field.description')}
                value={template.description ?? '—'}
              />
            </dl>
            <section>
              <h3>{t('instanceTemplates.detail.items')}</h3>
              {model.items.length === 0 ? (
                <p>{t('instanceTemplates.detail.itemsEmpty')}</p>
              ) : (
                <ul>
                  {model.items.map((item) => (
                    <li key={item.id}>
                      <strong>{item.itemSlug}</strong>
                      <span>{item.itemType}</span>
                      <code>#{item.displayOrder}</code>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section>
              <h3>{t('instanceTemplates.field.defaultConfig')}</h3>
              <pre>{JSON.stringify(template.defaultConfig, null, 2)}</pre>
            </section>
            <div className="instance-templates-detail-actions">
              <button
                type="button"
                disabled={submitting}
                onClick={() =>
                  void onClone(
                    template.id,
                    t('instanceTemplates.copyName', { name: template.name }),
                  ).catch((error) => onError(errorCode(error)))
                }
              >
                {t('instanceTemplates.clone')}
              </button>
              {!template.isPublished ? (
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() =>
                    void onPublish(template.id).catch((error) =>
                      onError(errorCode(error)),
                    )
                  }
                >
                  {t('instanceTemplates.publish')}
                </button>
              ) : null}
              <DeleteControl
                templateId={template.id}
                submitting={submitting}
                onDelete={onDelete}
                onError={onError}
              />
            </div>
          </>
        ) : (
          <code>{model.detailReasonCode}</code>
        )}
      </aside>
    </div>
  );
}

function DetailRow({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function StateNotice({
  model,
  onRetry,
}: Readonly<{ model: InstanceTemplatesModel; onRetry(): void }>) {
  const { t } = useI18n();
  return (
    <div className="instance-templates-empty">
      <h3>{t(`instanceTemplates.state.${model.state}`)}</h3>
      <code>{model.reasonCode}</code>
      {model.retryVisible ? (
        <button type="button" onClick={onRetry}>
          {t('common.retry')}
        </button>
      ) : null}
    </div>
  );
}

function errorCode(error: unknown): string {
  return error instanceof Error ? error.message : 'instance_templates_operation_failed';
}

function slugify(name: string): string {
  const slug = name
    .trim()
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/gu, '-')
    .replace(/^-+|-+$/gu, '')
    .slice(0, 200);
  return slug || 'template';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
