import { Badge, Button, Flex, Heading, ScrollArea, Text, TextField } from '@radix-ui/themes';
import { ReloadIcon } from '@radix-ui/react-icons';

import type { WorkspaceSummary } from '../../types';

type WorkspaceDockProps = {
  workspaces: WorkspaceSummary[];
  currentWorkspaceId: string;
  messageCount: number;
  taskCount: number;
  actionDisabledReason: string | null;
  newWorkspaceName: string;
  creatingWorkspace: boolean;
  onSelectWorkspace: (workspaceId: string) => void;
  onRefresh: () => void;
  onNewWorkspaceNameChange: (value: string) => void;
  onCreateWorkspace: () => void;
};

export function WorkspaceDock({
  workspaces,
  currentWorkspaceId,
  messageCount,
  taskCount,
  actionDisabledReason,
  newWorkspaceName,
  creatingWorkspace,
  onSelectWorkspace,
  onRefresh,
  onNewWorkspaceNameChange,
  onCreateWorkspace,
}: WorkspaceDockProps) {
  const selected = workspaces.find((workspace) => workspace.id === currentWorkspaceId);

  return (
    <aside className="workspace-dock">
      <section className="dock-head">
        <Flex align="center" justify="between">
          <Text size="1" weight="bold" color="gray">
            WORKSPACES
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
            <Heading as="h2" size="3">
              {workspaceLabel(selected)}
            </Heading>
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
          {workspaces.length === 0 ? (
            <div className="empty-state workspace-empty">
              <Text size="2" color="gray">
                No workspaces in this project yet.
              </Text>
              {actionDisabledReason ? (
                <Text size="1" color="gray" className="action-hint" title={actionDisabledReason}>
                  Connect first to load workspaces.
                </Text>
              ) : null}
              {actionDisabledReason ? null : (
                <>
                  <TextField.Root
                    aria-label="New workspace name"
                    value={newWorkspaceName}
                    onChange={(event) => onNewWorkspaceNameChange(event.target.value)}
                    placeholder="Desktop workspace"
                  />
                  <Button
                    size="2"
                    onClick={onCreateWorkspace}
                    loading={creatingWorkspace}
                    disabled={!newWorkspaceName.trim()}
                  >
                    Create workspace
                  </Button>
                </>
              )}
            </div>
          ) : (
            workspaces.map((workspace) => (
              <button
                className={`dock-row ${workspace.id === currentWorkspaceId ? 'selected' : ''}`}
                type="button"
                key={workspace.id}
                onClick={() => onSelectWorkspace(workspace.id)}
              >
                <span>
                  <strong>{workspaceLabel(workspace)}</strong>
                  <Text size="1" color="gray">
                    {workspace.description ?? workspace.id}
                  </Text>
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
