import {
  ExclamationTriangleIcon,
  LockClosedIcon,
  MagnifyingGlassIcon,
  Pencil1Icon,
  PlusIcon,
  ReloadIcon,
  TrashIcon,
} from '@radix-ui/react-icons';
import { Button, TextArea, TextField } from '@radix-ui/themes';
import { useRef, useState } from 'react';

import { useI18n } from '../../i18n';
import { createTenantProjectsMutationKey } from './tenantProjectsClient';
import type {
  TenantProjectRecord,
  TenantProjectsMutationInput,
} from './tenantProjectsClient';
import type {
  TenantProjectsController,
  TenantProjectsViewModel,
} from './tenantProjectsController';
import { restoreTenantProjectsDialogFocus } from './tenantProjectsDialogFocus';
import './TenantProjectsPage.css';

export function TenantProjectsPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantProjectsViewModel;
  controller: TenantProjectsController;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [editor, setEditor] = useState<
    | Readonly<{ kind: 'create'; idempotencyKey: string }>
    | Readonly<{ kind: 'edit'; project: TenantProjectRecord; idempotencyKey: string }>
    | null
  >(null);
  const [deleteProject, setDeleteProject] = useState<Readonly<{
    project: TenantProjectRecord;
    idempotencyKey: string;
  }> | null>(null);
  const [search, setSearch] = useState('');
  const createTriggerRef = useRef<HTMLButtonElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const dialogReturnFocusRef = useRef<HTMLElement | null>(null);
  const restoreDialogFocus = () => {
    const trigger = dialogReturnFocusRef.current;
    dialogReturnFocusRef.current = null;
    restoreTenantProjectsDialogFocus({
      trigger,
      fallback: createTriggerRef.current ?? searchInputRef.current,
    });
  };
  const closeEditor = () => {
    setEditor(null);
    restoreDialogFocus();
  };
  const closeDeleteDialog = () => {
    setDeleteProject(null);
    restoreDialogFocus();
  };
  if (
    model.state !== 'ready' &&
    model.state !== 'degraded' &&
    model.state !== 'empty' &&
    model.state !== 'conflict'
  ) {
    return <TenantProjectsState model={model} onRetry={onRetry} />;
  }
  const projects = search.trim()
    ? model.projects.filter((project) =>
        project.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
      )
    : model.projects;
  return (
    <section className="tenant-projects-page" data-state={model.state}>
      <header className="tenant-projects-header">
        <div>
          <span>{t('tenantProjects.eyebrow')}</span>
          <h1>{t('tenantProjects.title')}</h1>
          <p>{t('tenantProjects.subtitle')}</p>
        </div>
        {model.allowedActions.includes('create') ? (
          <Button
            ref={createTriggerRef}
            color="gray"
            onClick={(event) => {
              dialogReturnFocusRef.current = event.currentTarget;
              setEditor({
                kind: 'create',
                idempotencyKey: createTenantProjectsMutationKey('create'),
              });
            }}
          >
            <PlusIcon />
            {t('tenantProjects.create')}
          </Button>
        ) : null}
      </header>
      {model.state === 'degraded' || model.state === 'conflict' ? (
        <div className="tenant-projects-notice" role="status">
          <ExclamationTriangleIcon />
          <span>
            {t(
              model.state === 'conflict'
                ? 'tenantProjects.conflict'
                : 'tenantProjects.degraded',
            )}
          </span>
          <code>{model.reasonCode}</code>
        </div>
      ) : null}
      <label className="tenant-projects-search">
        <MagnifyingGlassIcon />
        <span>{t('tenantProjects.search')}</span>
        <TextField.Root
          ref={searchInputRef}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t('tenantProjects.search')}
        />
      </label>
      <div className="tenant-projects-summary">
        <strong>{model.total}</strong>
        <span>{t('tenantProjects.total')}</span>
        <code>{model.scope.tenantId}</code>
      </div>
      {projects.length === 0 ? (
        <div className="tenant-projects-empty">
          <h2>{t('tenantProjects.empty.title')}</h2>
          <p>{t('tenantProjects.empty.description')}</p>
        </div>
      ) : (
        <div className="tenant-projects-grid">
          {projects.map((project) => (
            <article key={project.id}>
              <div>
                <span>{project.isPublic ? t('tenantProjects.public') : t('tenantProjects.private')}</span>
                <code>{project.id}</code>
              </div>
              <h2>{project.name}</h2>
              <p>{project.description || t('tenantProjects.description.empty')}</p>
              <footer>
                <span>{t('tenantProjects.members', { count: project.memberIds.length })}</span>
                <div>
                  {project.allowedActions.includes('update') ? (
                    <Button
                      color="gray"
                      variant="soft"
                      aria-label={t('tenantProjects.edit', { name: project.name })}
                      onClick={(event) => {
                        dialogReturnFocusRef.current = event.currentTarget;
                        setEditor({
                          kind: 'edit',
                          project,
                          idempotencyKey: createTenantProjectsMutationKey('update'),
                        });
                      }}
                    >
                      <Pencil1Icon />
                      {t('tenantProjects.edit', { name: project.name })}
                    </Button>
                  ) : null}
                  {project.allowedActions.includes('delete') ? (
                    <Button
                      color="red"
                      variant="soft"
                      aria-label={t('tenantProjects.delete', { name: project.name })}
                      onClick={(event) => {
                        dialogReturnFocusRef.current = event.currentTarget;
                        setDeleteProject({
                          project,
                          idempotencyKey: createTenantProjectsMutationKey('delete'),
                        });
                      }}
                    >
                      <TrashIcon />
                      {t('tenantProjects.delete', { name: project.name })}
                    </Button>
                  ) : null}
                </div>
              </footer>
            </article>
          ))}
        </div>
      )}
      {editor ? (
        <ProjectEditor
          editor={editor}
          busy={model.busyAction !== null}
          onCancel={closeEditor}
          onSubmit={async (input) => {
            if (editor.kind === 'create') {
              await controller.create(input, editor.idempotencyKey);
            } else {
              await controller.update(
                editor.project.id,
                input,
                editor.idempotencyKey,
              );
            }
            closeEditor();
          }}
        />
      ) : null}
      {deleteProject ? (
        <div className="tenant-projects-confirm">
          <div
            className="tenant-projects-confirm-card"
            role="alertdialog"
            aria-modal="true"
            onKeyDown={(event) => {
              if (event.key === 'Escape') closeDeleteDialog();
            }}
          >
            <h2>{t('tenantProjects.delete.confirm.title')}</h2>
            <p>
              {t('tenantProjects.delete.confirm.description', {
                name: deleteProject.project.name,
              })}
            </p>
            <div>
              <Button color="gray" variant="soft" onClick={closeDeleteDialog}>
                {t('common.cancel')}
              </Button>
              <Button
                autoFocus
                color="red"
                disabled={model.busyAction !== null}
                onClick={() => {
                  void controller
                    .delete(
                      deleteProject.project.id,
                      deleteProject.idempotencyKey,
                    )
                    .then(closeDeleteDialog)
                    .catch(() => undefined);
                }}
              >
                {t('tenantProjects.delete.confirm.action')}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ProjectEditor({
  editor,
  busy,
  onCancel,
  onSubmit,
}: Readonly<{
  editor:
    | Readonly<{ kind: 'create'; idempotencyKey: string }>
    | Readonly<{
        kind: 'edit';
        project: TenantProjectRecord;
        idempotencyKey: string;
      }>;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (input: TenantProjectsMutationInput) => Promise<void>;
}>) {
  const { t } = useI18n();
  const [name, setName] = useState(editor.kind === 'edit' ? editor.project.name : '');
  const [description, setDescription] = useState(
    editor.kind === 'edit' ? editor.project.description : '',
  );
  return (
    <div className="tenant-projects-editor" role="dialog" aria-modal="true">
      <form
        onKeyDown={(event) => {
          if (event.key === 'Escape') onCancel();
        }}
        onSubmit={(event) => {
          event.preventDefault();
          void onSubmit({ name, description }).catch(() => undefined);
        }}
      >
        <h2>
          {t(
            editor.kind === 'create'
              ? 'tenantProjects.editor.create'
              : 'tenantProjects.editor.edit',
          )}
        </h2>
        <label>
          <span>{t('tenantProjects.editor.name')}</span>
          <TextField.Root
            autoFocus
            required
            maxLength={200}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          <span>{t('tenantProjects.editor.description')}</span>
          <TextArea
            maxLength={4_000}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <div>
          <Button type="button" color="gray" variant="soft" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" color="gray" disabled={busy || !name.trim()}>
            {t('common.save')}
          </Button>
        </div>
      </form>
    </div>
  );
}

function TenantProjectsState({
  model,
  onRetry,
}: Readonly<{
  model: TenantProjectsViewModel;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const busy = model.state === 'loading' || model.state === 'scope_switch';
  const Icon = model.state === 'forbidden' ? LockClosedIcon : ReloadIcon;
  return (
    <section
      className="tenant-projects-page tenant-projects-state"
      data-state={model.state}
      aria-busy={busy || undefined}
    >
      <Icon />
      <h1>{t(`tenantProjects.state.${model.state}.title`)}</h1>
      <p>{t(`tenantProjects.state.${model.state}.description`)}</p>
      <code>{model.reasonCode ?? model.scope.tenantId}</code>
      {model.retryVisible ? (
        <Button color="gray" variant="surface" onClick={onRetry}>
          <ReloadIcon />
          {t('common.retry')}
        </Button>
      ) : null}
    </section>
  );
}
