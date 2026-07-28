import { useMemo, useState } from 'react';

import { A2UIViewer, type A2UIViewerProps } from '@copilotkit/a2ui-renderer';

import { useI18n } from '../../i18n';
import {
  applyA2UISurfaceMessages,
  createA2UIActionCommand,
  createEmptyA2UISurfaceState,
  type A2UIActionCommand,
  type A2UIAllowedAction,
  type A2UIComponentNode,
} from './a2uiSurfaceModel';
import { ensureDesktopA2UIRegistry } from './a2uiDesktopRegistry';
import './DesktopA2UISurface.css';

type DesktopA2UISurfaceProps = {
  messages: string;
  requestId: string | null;
  authorityRevision: number | null;
  idempotencyKey: string | null;
  allowedActions: A2UIAllowedAction[];
  answered?: boolean;
  canRespond?: boolean;
  onCommand: (command: A2UIActionCommand) => void | Promise<void>;
};

export function DesktopA2UISurface({
  messages,
  requestId,
  authorityRevision,
  idempotencyKey,
  allowedActions,
  answered = false,
  canRespond = true,
  onCommand,
}: DesktopA2UISurfaceProps) {
  const { t } = useI18n();
  const [actionError, setActionError] = useState(false);
  const state = useMemo(
    () => applyA2UISurfaceMessages(createEmptyA2UISurfaceState(), messages),
    [messages],
  );
  const components = useMemo(
    () =>
      Object.values(state.components).map(toRendererComponent) as unknown as A2UIViewerProps['components'],
    [state.components],
  );
  const interactive =
    !answered &&
    canRespond &&
    Boolean(requestId) &&
    authorityRevision !== null &&
    Boolean(idempotencyKey) &&
    allowedActions.length > 0;

  ensureDesktopA2UIRegistry();

  if (state.status !== 'ready' || !state.rootId || !state.surfaceId) {
    return (
      <section className="desktop-a2ui-surface-state" role="status">
        <strong>{t('chat.a2uiOriginalSurfaceRequired')}</strong>
        {state.errorCode ? <code>{state.errorCode}</code> : null}
      </section>
    );
  }

  return (
    <section
      className="desktop-a2ui-surface"
      aria-label={t('artifact.previewLabel')}
      data-interactive={interactive || undefined}
    >
      <fieldset disabled={!interactive} aria-disabled={!interactive || undefined}>
        <A2UIViewer
          root={state.rootId}
          components={components}
          data={state.dataModel}
          className="desktop-a2ui-viewer"
          onAction={(event) => {
            setActionError(false);
            const result = createA2UIActionCommand({
              requestId: requestId ?? '',
              surfaceId: state.surfaceId ?? '',
              sourceComponentId: event.sourceComponentId,
              actionName: event.actionName,
              authorityRevision: authorityRevision ?? -1,
              idempotencyKey: idempotencyKey ?? '',
              allowedActions,
              context: event.context,
            });
            if (!result.ok) {
              setActionError(true);
              return;
            }
            void onCommand(result.command);
          }}
        />
      </fieldset>
      {answered || !interactive || actionError ? (
        <p role={actionError ? 'alert' : 'note'}>
          {actionError
            ? t('chat.a2uiOriginalSurfaceRequired')
            : answered
              ? t('chat.responded')
              : t('chat.a2uiOriginalSurfaceRequired')}
        </p>
      ) : null}
    </section>
  );
}

function toRendererComponent(node: A2UIComponentNode): A2UIComponentNode {
  const [kind, properties] = Object.entries(node.component)[0] ?? [];
  if (!kind) return node;
  const rendererKind =
    kind === 'Checkbox' ? 'CheckBox' : kind === 'Select' ? 'MultipleChoice' : kind;
  return {
    ...node,
    component: { [rendererKind]: properties },
  };
}
