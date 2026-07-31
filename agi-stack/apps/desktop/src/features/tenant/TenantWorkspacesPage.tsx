import {
  ExclamationTriangleIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';
import { Button, TextArea, TextField } from '@radix-ui/themes';
import { useRef, useState } from 'react';

import { useI18n } from '../../i18n';
import type { TenantWorkspaceCreateInput } from './tenantWorkspacesClient';
import type {
  TenantWorkspacesController,
  TenantWorkspacesViewModel,
} from './tenantWorkspacesController';
import './TenantWorkspacesPage.css';

export function TenantWorkspacesPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantWorkspacesViewModel;
  controller: TenantWorkspacesController;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const createTriggerRef = useRef<HTMLButtonElement>(null);
  if (
    model.state !== 'ready' &&
    model.state !== 'degraded' &&
    model.state !== 'empty' &&
    model.state !== 'conflict'
  ) {
    return <TenantWorkspacesState model={model} onRetry={onRetry} />;
  }
  const query = search.trim().toLocaleLowerCase();
  const workspaces = query
    ? model.workspaces.filter((workspace) => workspace.name.toLocaleLowerCase().includes(query))
    : model.workspaces;
  const closeCreate = (): void => {
    setCreateOpen(false);
    queueMicrotask(() => createTriggerRef.current?.focus());
  };
  return (
    <section className="tenant-workspaces-page" data-state={model.state}>
      <header className="tenant-workspaces-header">
        <div>
          <span>{t('tenantWorkspaces.eyebrow')}</span>
          <h1>{t('tenantWorkspaces.title')}</h1>
          <p>{t('tenantWorkspaces.subtitle')}</p>
        </div>
        {model.allowedActions.includes('create') ? (
          <Button ref={createTriggerRef} color="gray" onClick={() => setCreateOpen(true)}>
            <PlusIcon />
            {t('tenantWorkspaces.create')}
          </Button>
        ) : null}
      </header>
      {model.state === 'degraded' || model.state === 'conflict' ? (
        <div className="tenant-workspaces-notice" role="status">
          <ExclamationTriangleIcon />
          <span>
            {t(
              model.state === 'conflict'
                ? 'tenantWorkspaces.conflict'
                : 'tenantWorkspaces.degraded',
            )}
          </span>
          <code>{model.reasonCode}</code>
        </div>
      ) : null}
      <div className="tenant-workspaces-context">
        <span>{t('tenantWorkspaces.project')}</span>
        <code>{model.scope.projectId}</code>
      </div>
      <label className="tenant-workspaces-search">
        <MagnifyingGlassIcon />
        <span>{t('tenantWorkspaces.search')}</span>
        <TextField.Root
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t('tenantWorkspaces.search')}
        />
      </label>
      {workspaces.length === 0 ? (
        <div className="tenant-workspaces-empty">
          <h2>{t('tenantWorkspaces.empty.title')}</h2>
          <p>{t('tenantWorkspaces.empty.description')}</p>
        </div>
      ) : (
        <div className="tenant-workspaces-grid">
          {workspaces.map((workspace) => (
            <article key={workspace.id}>
              <div>
                <span>{workspace.status}</span>
                <code>{workspace.id}</code>
              </div>
              <h2>{workspace.name}</h2>
              <p>{workspace.description || t('tenantWorkspaces.description.empty')}</p>
            </article>
          ))}
        </div>
      )}
      {createOpen ? (
        <WorkspaceCreateDialog
          busy={model.busyAction !== null}
          onCancel={closeCreate}
          onSubmit={async (input) => {
            await controller.create(input);
            closeCreate();
          }}
        />
      ) : null}
    </section>
  );
}

function WorkspaceCreateDialog({
  busy,
  onCancel,
  onSubmit,
}: Readonly<{
  busy: boolean;
  onCancel: () => void;
  onSubmit: (input: TenantWorkspaceCreateInput) => Promise<void>;
}>) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  return (
    <div className="tenant-workspaces-dialog">
      <form
        className="tenant-workspaces-dialog-card"
        role="dialog"
        aria-modal="true"
        onKeyDown={(event) => {
          if (event.key === 'Escape') onCancel();
        }}
        onSubmit={(event) => {
          event.preventDefault();
          const input = {
            name: name.trim(),
            description: description.trim(),
          };
          if (!input.name) return;
          void onSubmit(input).catch(() => undefined);
        }}
      >
        <h2>{t('tenantWorkspaces.create')}</h2>
        <label>
          <span>{t('tenantWorkspaces.editor.name')}</span>
          <TextField.Root
            autoFocus
            required
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          <span>{t('tenantWorkspaces.editor.description')}</span>
          <TextArea
            maxLength={2_000}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <div>
          <Button type="button" color="gray" variant="soft" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" color="gray" disabled={busy || !name.trim()}>
            {t('tenantWorkspaces.create')}
          </Button>
        </div>
      </form>
    </div>
  );
}

function TenantWorkspacesState({
  model,
  onRetry,
}: Readonly<{
  model: TenantWorkspacesViewModel;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  return (
    <section className="tenant-workspaces-state" data-state={model.state}>
      <h1>{t(`tenantWorkspaces.state.${model.state}.title`)}</h1>
      <p>{t(`tenantWorkspaces.state.${model.state}.description`)}</p>
      {model.reasonCode ? <code>{model.reasonCode}</code> : null}
      {model.retryVisible ? (
        <Button color="gray" variant="soft" onClick={onRetry}>
          <ReloadIcon />
          {t('common.retry')}
        </Button>
      ) : null}
    </section>
  );
}
