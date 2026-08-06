import { PlusIcon, ReloadIcon } from '@radix-ui/react-icons';
import { Button, TextArea, TextField } from '@radix-ui/themes';
import { useState } from 'react';

import { useI18n } from '../../i18n';
import type { ProjectWorkspaceCreateInput } from './projectWorkspacesClient';
import type { ProjectWorkspacesController } from './projectWorkspacesController';
import type { ProjectWorkspacesViewModel } from './projectWorkspacesPresentationModel';
import '../tenant/TenantWorkspacesPage.css';

export function ProjectWorkspacesPage({
  model,
  controller,
  onRetry,
  onOpenBlackboard,
}: Readonly<{
  model: ProjectWorkspacesViewModel;
  controller: ProjectWorkspacesController;
  onRetry: () => void;
  onOpenBlackboard: (workspaceId: string) => void;
}>) {
  const { t } = useI18n();
  const [createOpen, setCreateOpen] = useState(false);
  if (!['ready', 'degraded', 'empty'].includes(model.state)) {
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
  return (
    <section className="tenant-workspaces-page" data-state={model.state}>
      <header className="tenant-workspaces-header">
        <div>
          <span>{t('tenantWorkspaces.eyebrow')}</span>
          <h1>{t('tenantWorkspaces.title')}</h1>
          <p>{t('tenantWorkspaces.subtitle')}</p>
        </div>
        {model.allowedActions.includes('create') ? (
          <Button color="gray" onClick={() => setCreateOpen(true)}>
            <PlusIcon />
            {t('tenantWorkspaces.create')}
          </Button>
        ) : null}
      </header>
      {model.reasonCode ? <code>{model.reasonCode}</code> : null}
      <div className="tenant-workspaces-context">
        <span>{t('tenantWorkspaces.project')}</span>
        <code>{model.scope.projectId}</code>
      </div>
      <div className="tenant-workspaces-grid">
        {model.workspaces.map((workspace) => (
          <article key={workspace.id}>
            <code>{workspace.id}</code>
            <h2>{workspace.name}</h2>
            <p>{workspace.description || t('tenantWorkspaces.description.empty')}</p>
            {model.allowedActions.includes('open-blackboard') ? (
              <Button color="gray" variant="soft" onClick={() => onOpenBlackboard(workspace.id)}>
                {t('workspaceCollaboration.title')}
              </Button>
            ) : null}
          </article>
        ))}
      </div>
      {createOpen ? (
        <ProjectWorkspaceCreateDialog
          busy={model.busyAction !== null}
          onCancel={() => setCreateOpen(false)}
          onSubmit={async (input) => {
            await controller.create(input);
            setCreateOpen(false);
          }}
        />
      ) : null}
    </section>
  );
}
function ProjectWorkspaceCreateDialog({
  busy,
  onCancel,
  onSubmit,
}: Readonly<{
  busy: boolean;
  onCancel: () => void;
  onSubmit: (input: ProjectWorkspaceCreateInput) => Promise<void>;
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
        onSubmit={(event) => {
          event.preventDefault();
          if (!name.trim()) return;
          void onSubmit({ name: name.trim(), description: description.trim() }).catch(
            () => undefined,
          );
        }}
      >
        <h2>{t('tenantWorkspaces.create')}</h2>
        <label>
          <span>{t('tenantWorkspaces.editor.name')}</span>
          <TextField.Root value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          <span>{t('tenantWorkspaces.editor.description')}</span>
          <TextArea
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
