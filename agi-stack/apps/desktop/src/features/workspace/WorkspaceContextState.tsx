import { Button } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  CubeIcon,
  GearIcon,
  PlusIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';

type WorkspaceContextStateProps = {
  tenantName: string;
  projectName: string;
  title: string;
  description: string;
  cardTitle: string;
  cardDescription: string;
  detail?: string | null;
  state: 'loading' | 'error' | 'empty';
  primaryAction: 'none' | 'retry' | 'new-task';
  newTaskDisabledReason: string | null;
  onNewTask: () => void;
  onRetry: () => void;
  onOpenSettings: () => void;
};

export function WorkspaceContextState({
  tenantName,
  projectName,
  title,
  description,
  cardTitle,
  cardDescription,
  detail,
  state,
  primaryAction,
  newTaskDisabledReason,
  onNewTask,
  onRetry,
  onOpenSettings,
}: WorkspaceContextStateProps) {
  const { t } = useI18n();
  const newTaskReasonId = newTaskDisabledReason
    ? 'workspace-context-new-task-disabled-reason'
    : undefined;
  return (
    <section
      className={`workspace-design-overview workspace-context-${state}`}
      aria-busy={state === 'loading' || undefined}
      aria-labelledby="workspace-context-title"
      aria-describedby="workspace-context-description"
    >
      <header className="workspace-design-header">
        <div>
          <span className="workspace-design-eyebrow">
            {tenantName} / {projectName}
          </span>
          <div className="workspace-design-title-line">
            <h1 id="workspace-context-title">{title}</h1>
          </div>
          <p id="workspace-context-description">{description}</p>
        </div>
        <div className="workspace-design-header-actions">
          <Button variant="surface" color="gray" onClick={onOpenSettings}>
            <GearIcon aria-hidden="true" /> {t('overview.configure')}
          </Button>
          {primaryAction === 'new-task' ? (
            <Button
              disabled={Boolean(newTaskDisabledReason)}
              aria-describedby={newTaskReasonId}
              onClick={onNewTask}
            >
              <PlusIcon aria-hidden="true" /> {t('overview.newTask')}
            </Button>
          ) : null}
        </div>
      </header>

      <div className="workspace-design-content">
        <section
          className="workspace-design-context-empty"
          data-state={state}
          role={state === 'loading' ? 'status' : state === 'error' ? 'alert' : undefined}
          aria-labelledby="workspace-context-card-title"
          aria-describedby="workspace-context-card-description"
        >
          <span aria-hidden="true">
            <CubeIcon />
          </span>
          <div>
            <small>{t('settings.workspaceContextEyebrow')}</small>
            <h2 id="workspace-context-card-title">{cardTitle}</h2>
            <p id="workspace-context-card-description">{cardDescription}</p>
            {detail ? <p className="workspace-design-context-detail">{detail}</p> : null}
          </div>
          {primaryAction === 'none' ? null : (
            <div className="workspace-design-context-actions">
              {newTaskDisabledReason && primaryAction === 'new-task' ? (
                <small
                  id="workspace-context-new-task-disabled-reason"
                  className="workspace-design-action-reason"
                >
                  {newTaskDisabledReason}
                </small>
              ) : null}
              <div>
                {primaryAction === 'new-task' ? (
                  <Button
                    disabled={Boolean(newTaskDisabledReason)}
                    aria-describedby={newTaskReasonId}
                    onClick={onNewTask}
                  >
                    <PlusIcon aria-hidden="true" /> {t('overview.newTask')}
                  </Button>
                ) : (
                  <Button onClick={onRetry}>
                    <ActivityLogIcon aria-hidden="true" /> {t('overview.retryWorkspaces')}
                  </Button>
                )}
                {primaryAction === 'new-task' ? (
                  <Button variant="surface" color="gray" onClick={onOpenSettings}>
                    <GearIcon aria-hidden="true" /> {t('overview.configure')}
                  </Button>
                ) : null}
              </div>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
