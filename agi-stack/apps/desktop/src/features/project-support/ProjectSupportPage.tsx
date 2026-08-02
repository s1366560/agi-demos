import {
  ChevronLeftIcon,
  ChevronRightIcon,
  Cross2Icon,
  ExclamationTriangleIcon,
  PlusIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';
import { Button, Select, TextArea, TextField } from '@radix-ui/themes';
import { useRef, useState } from 'react';

import { useI18n } from '../../i18n';
import type {
  ProjectSupportController,
  ProjectSupportViewModel,
} from './projectSupportController';
import type {
  ProjectSupportCreateInput,
  ProjectSupportPriority,
  ProjectSupportStatus,
} from './projectSupportTypes';
import './ProjectSupportPage.css';

export function ProjectSupportPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: ProjectSupportViewModel;
  controller: ProjectSupportController;
  onRetry: () => void;
}>) {
  const { locale, t } = useI18n();
  const [editorOpen, setEditorOpen] = useState(false);
  const createTriggerRef = useRef<HTMLButtonElement>(null);
  const closeEditor = () => {
    setEditorOpen(false);
    queueMicrotask(() => createTriggerRef.current?.focus());
  };
  const terminal =
    model.state === 'loading' ||
    model.state === 'scope_switch' ||
    model.state === 'forbidden' ||
    model.state === 'unavailable' ||
    model.state === 'not_applicable' ||
    model.state === 'error';
  if (terminal) {
    return <ProjectSupportState model={model} onRetry={onRetry} />;
  }
  const pageStart = model.total === 0 ? 0 : model.offset + 1;
  const pageEnd = Math.min(model.total, model.offset + model.tickets.length);
  return (
    <section className="project-support-page" data-state={model.state}>
      <header className="project-support-header">
        <div>
          <span>{t('projectSupport.eyebrow')}</span>
          <h1>{t('projectSupport.title')}</h1>
          <p>{t('projectSupport.subtitle')}</p>
        </div>
        <div className="project-support-context">
          <span data-authority={model.authority}>
            {t(`projectSupport.authority.${model.authority}`)}
          </span>
          <code>{model.scope.tenantId}</code>
          <code>{model.scope.projectId}</code>
        </div>
      </header>
      {model.state === 'stale' || model.state === 'conflict' ? (
        <div className="project-support-notice" role="status">
          <ExclamationTriangleIcon aria-hidden="true" />
          <span>{t(`projectSupport.state.${model.state}`)}</span>
          {model.reasonCode ? <code>{model.reasonCode}</code> : null}
          {model.retryVisible ? (
            <Button color="gray" variant="soft" onClick={onRetry}>
              <ReloadIcon />
              {t('common.retry')}
            </Button>
          ) : null}
        </div>
      ) : null}
      <div className="project-support-toolbar">
        <div>
          <strong>{model.total}</strong>
          <span>{t('projectSupport.total')}</span>
        </div>
        {model.allowedActions.includes('create') ? (
          <Button
            ref={createTriggerRef}
            color="gray"
            onClick={() => setEditorOpen(true)}
          >
            <PlusIcon />
            {t('projectSupport.create')}
          </Button>
        ) : null}
      </div>
      {model.tickets.length === 0 ? (
        <div className="project-support-empty">
          <h2>{t('projectSupport.empty.title')}</h2>
          <p>{t('projectSupport.empty.description')}</p>
        </div>
      ) : (
        <div className="project-support-list">
          {model.tickets.map((ticket) => (
            <article key={ticket.id}>
              <header>
                <div>
                  <span data-status={ticket.status}>
                    {t(statusKey(ticket.status))}
                  </span>
                  <span data-priority={ticket.priority}>
                    {t(`projectSupport.form.priority.${ticket.priority}`)}
                  </span>
                </div>
                <code>{ticket.id}</code>
              </header>
              <h2>{ticket.subject}</h2>
              <p>{ticket.message}</p>
              <footer>
                <div>
                  <span>
                    {t('projectSupport.created', {
                      date: formatTimestamp(ticket.createdAt, locale),
                    })}
                  </span>
                  {ticket.resolvedAt ? (
                    <span>
                      {t('projectSupport.resolved', {
                        date: formatTimestamp(ticket.resolvedAt, locale),
                      })}
                    </span>
                  ) : null}
                </div>
                {ticket.allowedActions.includes('close') &&
                model.allowedActions.includes('close') ? (
                  <Button
                    color="gray"
                    variant="soft"
                    disabled={model.busyAction !== null}
                    onClick={() => {
                      if (!window.confirm(t('projectSupport.close.confirm'))) {
                        return;
                      }
                      void controller.close(ticket.id).catch(() => undefined);
                    }}
                  >
                    <Cross2Icon />
                    {t('projectSupport.close')}
                  </Button>
                ) : null}
              </footer>
            </article>
          ))}
        </div>
      )}
      <nav className="project-support-pagination" aria-label={t('projectSupport.page', {
        start: pageStart,
        end: pageEnd,
        total: model.total,
      })}>
        <Button
          color="gray"
          variant="soft"
          disabled={model.offset === 0 || model.busyAction !== null}
          onClick={() => {
            void controller.goToOffset(Math.max(0, model.offset - model.limit));
          }}
        >
          <ChevronLeftIcon />
          {t('projectSupport.previous')}
        </Button>
        <span>
          {t('projectSupport.page', {
            start: pageStart,
            end: pageEnd,
            total: model.total,
          })}
        </span>
        <Button
          color="gray"
          variant="soft"
          disabled={!model.hasMore || model.busyAction !== null}
          onClick={() => {
            void controller.goToOffset(model.offset + model.limit);
          }}
        >
          {t('projectSupport.next')}
          <ChevronRightIcon />
        </Button>
      </nav>
      {editorOpen ? (
        <ProjectSupportEditor
          busy={model.busyAction !== null}
          onCancel={closeEditor}
          onSubmit={async (input) => {
            await controller.create(input);
            closeEditor();
          }}
        />
      ) : null}
    </section>
  );
}

function ProjectSupportEditor({
  busy,
  onCancel,
  onSubmit,
}: Readonly<{
  busy: boolean;
  onCancel: () => void;
  onSubmit: (input: ProjectSupportCreateInput) => Promise<void>;
}>) {
  const { t } = useI18n();
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');
  const [priority, setPriority] = useState<ProjectSupportPriority>('medium');
  return (
    <div className="project-support-editor" role="presentation">
      <form
        role="dialog"
        aria-modal="true"
        aria-label={t('projectSupport.form.title')}
        onKeyDown={(event) => {
          if (event.key === 'Escape') onCancel();
        }}
        onSubmit={(event) => {
          event.preventDefault();
          void onSubmit({ subject, message, priority }).catch(() => undefined);
        }}
      >
        <h2>{t('projectSupport.form.title')}</h2>
        <label>
          <span>{t('projectSupport.form.subject')}</span>
          <TextField.Root
            autoFocus
            required
            maxLength={500}
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
          />
        </label>
        <label>
          <span>{t('projectSupport.form.priority')}</span>
          <Select.Root
            value={priority}
            onValueChange={(value) =>
              setPriority(value as ProjectSupportPriority)
            }
          >
            <Select.Trigger />
            <Select.Content>
              {(['low', 'medium', 'high', 'urgent'] as const).map((value) => (
                <Select.Item value={value} key={value}>
                  {t(`projectSupport.form.priority.${value}`)}
                </Select.Item>
              ))}
            </Select.Content>
          </Select.Root>
        </label>
        <label>
          <span>{t('projectSupport.form.message')}</span>
          <TextArea
            required
            maxLength={20_000}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
          />
        </label>
        <div>
          <Button type="button" color="gray" variant="soft" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button
            type="submit"
            color="gray"
            disabled={busy || !subject.trim() || !message.trim()}
          >
            {t('projectSupport.create')}
          </Button>
        </div>
      </form>
    </div>
  );
}

function ProjectSupportState({
  model,
  onRetry,
}: Readonly<{
  model: ProjectSupportViewModel;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  return (
    <section
      className="project-support-page project-support-state"
      data-state={model.state}
      role={model.state === 'error' || model.state === 'forbidden' ? 'alert' : 'status'}
      aria-busy={model.state === 'loading' || model.state === 'scope_switch'}
    >
      <ExclamationTriangleIcon aria-hidden="true" />
      <span>{t('projectSupport.eyebrow')}</span>
      <h1>{t('projectSupport.title')}</h1>
      <p>{t(`projectSupport.state.${model.state}`)}</p>
      {model.reasonCode ? (
        <dl>
          <dt>{t('projectSupport.reason')}</dt>
          <dd><code>{model.reasonCode}</code></dd>
        </dl>
      ) : null}
      {model.retryVisible ? (
        <Button color="gray" onClick={onRetry}>
          <ReloadIcon />
          {t('common.retry')}
        </Button>
      ) : null}
    </section>
  );
}

function statusKey(status: ProjectSupportStatus): string {
  return `projectSupport.status.${status}`;
}

function formatTimestamp(timestamp: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(timestamp));
}
