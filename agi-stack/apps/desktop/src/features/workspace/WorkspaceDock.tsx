import { Badge, Button, Flex, ScrollArea, Text } from '@radix-ui/themes';
import {
  ChatBubbleIcon,
  ChevronDownIcon,
  FileTextIcon,
  PlusIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import type { WorkspaceSummary } from '../../types';

type WorkspaceDockProps = {
  workspaces: WorkspaceSummary[];
  currentWorkspaceId: string;
  projectLabel: string;
  groupMode: 'project' | 'recent';
  messageCount: number;
  taskCount: number;
  actionDisabledReason: string | null;
  creatingWorkspace: boolean;
  onSelectWorkspace: (workspaceId: string) => void;
  onOpenChat: () => void;
  onRefresh: () => void;
  onCreateWorkspace: () => void;
};

export function WorkspaceDock({
  workspaces,
  currentWorkspaceId,
  projectLabel,
  groupMode,
  messageCount,
  taskCount,
  actionDisabledReason,
  creatingWorkspace,
  onSelectWorkspace,
  onOpenChat,
  onRefresh,
  onCreateWorkspace,
}: WorkspaceDockProps) {
  const selected = workspaces.find((workspace) => workspace.id === currentWorkspaceId);
  const createSessionDisabled = Boolean(actionDisabledReason) || creatingWorkspace;
  const sessionCountLabel = `${workspaces.length} ${workspaces.length === 1 ? 'session' : 'sessions'}`;
  const rootLabel = groupMode === 'recent' ? 'Recent sessions' : projectLabel;
  const rootDetail =
    groupMode === 'recent' ? `${sessionCountLabel} in ${projectLabel}` : sessionCountLabel;

  return (
    <aside className="workspace-dock workspace-session-tree">
      <section className="dock-head">
        <Flex align="center" justify="between">
          <Text size="1" weight="bold" color="gray">
            SESSIONS
          </Text>
          <Button
            size="1"
            variant="ghost"
            aria-label="Refresh workspaces"
            onClick={onRefresh}
            disabled={Boolean(actionDisabledReason)}
          >
            <ReloadIcon /> Refresh
          </Button>
        </Flex>
        <div className="workspace-card">
          <Flex align="center" justify="between" gap="2">
            <Text size="2" weight="bold">
              {projectLabel}
            </Text>
            <Badge color={selected?.status === 'closed' ? 'gray' : 'green'} variant="soft">
              {selected?.status ?? 'open'}
            </Badge>
          </Flex>
          <Text size="1" color="gray">
            {messageCount} messages / {taskCount} tasks
          </Text>
        </div>
      </section>
      <ScrollArea className="dock-list">
        <div>
          <button className="dock-row session-root-row" type="button" onClick={onOpenChat}>
            <span className="dock-leading">
              <ChatBubbleIcon aria-hidden />
              <span>
                <strong>Chats</strong>
                <Text size="1" color="gray">
                  {messageCount} messages
                </Text>
              </span>
            </span>
            <Badge color="gray" variant="soft">
              {messageCount}
            </Badge>
          </button>
          <div className="dock-row project-root-row selected" aria-expanded={true}>
            <span className="dock-leading">
              <ChevronDownIcon aria-hidden />
              <span>
                <strong>{rootLabel}</strong>
                <Text size="1" color="gray">
                  {rootDetail}
                </Text>
              </span>
            </span>
            <Button
              size="1"
              variant="ghost"
              aria-label={
                groupMode === 'recent'
                  ? `Refresh recent sessions in ${projectLabel}`
                  : `Refresh sessions in ${projectLabel}`
              }
              onClick={onRefresh}
              disabled={Boolean(actionDisabledReason)}
            >
              <ReloadIcon />
            </Button>
          </div>
          <button
            className="dock-row session-child-row new-session-row"
            type="button"
            onClick={onCreateWorkspace}
            disabled={createSessionDisabled}
            title={actionDisabledReason ?? undefined}
          >
            <span className="dock-leading">
              <PlusIcon aria-hidden />
              <span>
                <strong>
                  {creatingWorkspace ? 'Creating session...' : `New session in ${projectLabel}`}
                </strong>
              </span>
            </span>
          </button>
          {workspaces.length === 0 ? (
            <div className="empty-state workspace-empty session-child-empty">
              <Text size="2" color="gray">
                No workspaces in this project yet.
              </Text>
              {actionDisabledReason ? (
                <Text size="1" color="gray" className="action-hint" title={actionDisabledReason}>
                  Connect first to load workspaces.
                </Text>
              ) : null}
            </div>
          ) : (
            workspaces.map((workspace) => (
              <button
                className={`dock-row session-child-row ${
                  workspace.id === currentWorkspaceId ? 'selected' : ''
                }`}
                type="button"
                key={workspace.id}
                aria-current={workspace.id === currentWorkspaceId ? 'page' : undefined}
                onClick={() => {
                  onSelectWorkspace(workspace.id);
                  onOpenChat();
                }}
              >
                <span className="dock-leading">
                  <FileTextIcon aria-hidden />
                  <span>
                    <strong>{workspaceLabel(workspace)}</strong>
                    <Text size="1" color="gray">
                      {workspace.description ?? workspace.id}
                    </Text>
                  </span>
                </span>
                <Badge color={workspace.id === currentWorkspaceId ? 'cyan' : 'gray'} variant="soft">
                  {workspace.status ?? 'open'}
                </Badge>
              </button>
            ))
          )}
        </div>
      </ScrollArea>
    </aside>
  );
}

function workspaceLabel(workspace: WorkspaceSummary | undefined): string {
  return workspace?.name ?? workspace?.title ?? workspace?.id ?? 'No workspace';
}
