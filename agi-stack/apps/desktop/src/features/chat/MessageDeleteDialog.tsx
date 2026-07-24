import { useRef } from 'react';
import { TrashIcon } from '@radix-ui/react-icons';
import { AlertDialog, Button, Flex } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import { messageDeletionExcerpt } from './chatMessageActionModel';

export type MessageDeleteDialogTarget = {
  messageId: string;
  content: string;
};

export function MessageDeleteDialog({
  target,
  onCancel,
  onConfirm,
}: {
  target: MessageDeleteDialogTarget;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  const confirmingRef = useRef(false);
  const excerpt = messageDeletionExcerpt(target.content);

  return (
    <AlertDialog.Root
      open
      onOpenChange={(open) => {
        if (!open && !confirmingRef.current) onCancel();
      }}
    >
      <AlertDialog.Content maxWidth="450px" aria-describedby="message-delete-description">
        <AlertDialog.Title>{t('chat.deleteMessageTitle')}</AlertDialog.Title>
        <AlertDialog.Description id="message-delete-description" size="2">
          {excerpt
            ? t('chat.deleteMessageBody', { excerpt })
            : t('chat.deleteMessageBodyEmpty')}
        </AlertDialog.Description>
        <p className="message-delete-dialog-note">
          {t('chat.deleteMessageRestorationNote')}
        </p>
        <Flex gap="3" mt="4" justify="end">
          <AlertDialog.Cancel>
            <Button variant="soft" color="gray">
              {t('common.cancel')}
            </Button>
          </AlertDialog.Cancel>
          <AlertDialog.Action>
            <Button
              color="red"
              onClick={() => {
                confirmingRef.current = true;
                onConfirm();
              }}
            >
              <TrashIcon aria-hidden="true" />
              {t('common.delete')}
            </Button>
          </AlertDialog.Action>
        </Flex>
      </AlertDialog.Content>
    </AlertDialog.Root>
  );
}
