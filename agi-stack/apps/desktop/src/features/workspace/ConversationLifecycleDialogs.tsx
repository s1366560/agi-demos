import { useEffect, useState } from 'react';
import { AlertDialog, Button, Dialog, TextField } from '@radix-ui/themes';
import { Pencil1Icon, TrashIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';

export type ConversationLifecycleMode = 'rename' | 'delete' | null;

export type ConversationLifecycleTarget = {
  id: string;
  title: string;
};

type ConversationLifecycleDialogsProps = {
  mode: ConversationLifecycleMode;
  target: ConversationLifecycleTarget | null;
  onClose: () => void;
  onRename: (title: string) => Promise<void>;
  onDelete: () => Promise<void>;
};

export function ConversationLifecycleDialogs({
  mode,
  target,
  onClose,
  onRename,
  onDelete,
}: ConversationLifecycleDialogsProps) {
  const { t } = useI18n();
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTitle(target?.title ?? '');
    setBusy(false);
    setError(null);
  }, [mode, target?.id, target?.title]);

  const close = () => {
    if (!busy) onClose();
  };

  const submitRename = async () => {
    const nextTitle = title.trim();
    if (!target || !nextTitle || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onRename(nextTitle);
      onClose();
    } catch {
      setError(t('workspaceTree.lifecycleError'));
      setBusy(false);
    }
  };

  const submitDelete = async () => {
    if (!target || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onDelete();
      onClose();
    } catch {
      setError(t('workspaceTree.lifecycleError'));
      setBusy(false);
    }
  };

  return (
    <>
      <Dialog.Root open={mode === 'rename'} onOpenChange={(open) => !open && close()}>
        <Dialog.Content className="conversation-lifecycle-dialog" maxWidth="440px">
          <Dialog.Title>{t('workspaceTree.renameTitle')}</Dialog.Title>
          <Dialog.Description>{t('workspaceTree.renameDescription')}</Dialog.Description>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submitRename();
            }}
          >
            <label>
              <span>{t('workspaceTree.renameLabel')}</span>
              <TextField.Root
                autoFocus
                value={title}
                disabled={busy}
                maxLength={200}
                aria-label={t('workspaceTree.renameLabel')}
                onChange={(event) => setTitle(event.currentTarget.value)}
              />
            </label>
            {error ? (
              <p className="conversation-lifecycle-error" role="alert">
                {error}
              </p>
            ) : null}
            <div className="conversation-lifecycle-actions">
              <Button type="button" variant="soft" color="gray" disabled={busy} onClick={close}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={busy || !title.trim()}>
                <Pencil1Icon />
                {busy ? t('workspaceTree.renaming') : t('workspaceTree.renameConversation')}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>

      <AlertDialog.Root open={mode === 'delete'} onOpenChange={(open) => !open && close()}>
        <AlertDialog.Content className="conversation-lifecycle-dialog" maxWidth="440px">
          <AlertDialog.Title>{t('workspaceTree.deleteTitle')}</AlertDialog.Title>
          <AlertDialog.Description>
            {t('workspaceTree.deleteDescription', {
              title: target?.title ?? '',
            })}
          </AlertDialog.Description>
          {error ? (
            <p className="conversation-lifecycle-error" role="alert">
              {error}
            </p>
          ) : null}
          <div className="conversation-lifecycle-actions">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray" disabled={busy}>
                {t('common.cancel')}
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                color="red"
                disabled={busy}
                onClick={(event) => {
                  event.preventDefault();
                  void submitDelete();
                }}
              >
                <TrashIcon />
                {busy ? t('workspaceTree.deleting') : t('workspaceTree.deleteConversation')}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </>
  );
}
