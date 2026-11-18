import { useRef } from "react";

import { DropdownMenu } from "@radix-ui/themes";
import {
  DotsHorizontalIcon,
  Pencil1Icon,
  TrashIcon,
} from "@radix-ui/react-icons";

import { useI18n } from "../../i18n";

export function ConversationActionsMenu({
  title,
  actionRef,
  onRename,
  onDelete,
}: {
  title: string;
  actionRef: (element: HTMLButtonElement | null) => void;
  onRename?: () => void;
  onDelete?: () => void;
}) {
  const { t } = useI18n();
  const openingDialog = useRef(false);
  const label = t("workspaceTree.conversationActions", { title });
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        <button
          type="button"
          className="workspace-tree-session-actions"
          ref={actionRef}
          aria-label={label}
          title={label}
        >
          <DotsHorizontalIcon aria-hidden="true" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Content
        className="workspace-tree-session-menu"
        align="end"
        aria-label={label}
        onCloseAutoFocus={(event) => {
          // The lifecycle dialog takes focus; its close handler restores this trigger.
          if (openingDialog.current) event.preventDefault();
          openingDialog.current = false;
        }}
      >
        {onRename ? (
          <DropdownMenu.Item
            onSelect={() => {
              openingDialog.current = true;
              onRename();
            }}
          >
            <Pencil1Icon aria-hidden="true" />
            {t("workspaceTree.renameConversation")}
          </DropdownMenu.Item>
        ) : null}
        {onDelete ? (
          <DropdownMenu.Item
            color="red"
            onSelect={() => {
              openingDialog.current = true;
              onDelete();
            }}
          >
            <TrashIcon aria-hidden="true" />
            {t("workspaceTree.deleteConversation")}
          </DropdownMenu.Item>
        ) : null}
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  );
}
