/**
 * ConversationWorkspacePanel — unified workspace rail for a conversation.
 *
 * Consolidates three panels (mode, participants, HITL) behind a single
 * "Workspace" card. When the conversation is linked to a real workspace
 * (Phase-5 G2), shows a header with the workspace name and a deep-link
 * to the full workspace page so the operator can jump to the hex grid /
 * blackboard / tasks view without losing context.
 *
 * Agent-First: no conversation-level goal editing here — the goal lives
 * on the linked WorkspaceTask (see ConversationModePanel task picker).
 */

import { memo, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';

import { Divider, Tag } from 'antd';
import { ExternalLink } from 'lucide-react';

import { restApi } from '@/services/agent/restApi';
import { workspaceService } from '@/services/workspaceService';

import { ConversationModePanel } from './ConversationModePanel';
import { HITLCenterPanel } from './HITLCenterPanel';

import type { Workspace } from '@/types/workspace';

export interface ConversationWorkspacePanelProps {
  conversationId: string;
  projectId: string;
}

const SectionLabel = ({ children }: { children: React.ReactNode }) => (
  <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[#666]">
    {children}
  </div>
);

export const ConversationWorkspacePanel = memo<ConversationWorkspacePanelProps>(
  ({ conversationId, projectId }) => {
    const { t } = useTranslation();
    const { tenantId } = useParams();

    const [workspaceId, setWorkspaceId] = useState<string | null>(null);
    const [workspace, setWorkspace] = useState<Workspace | null>(null);

    useEffect(() => {
      let cancelled = false;
      void restApi
        .getConversation(conversationId, projectId)
        .then((conv) => {
          if (cancelled) return;
          setWorkspaceId(conv?.workspace_id ?? null);
        })
        .catch(() => {
          if (!cancelled) setWorkspaceId(null);
        });
      return () => {
        cancelled = true;
      };
    }, [conversationId, projectId]);

    useEffect(() => {
      if (!workspaceId || !tenantId) {
        return;
      }
      let cancelled = false;
      void workspaceService
        .getById(tenantId, projectId, workspaceId)
        .then((ws) => {
          if (!cancelled) setWorkspace(ws);
        })
        .catch(() => {
          if (!cancelled) setWorkspace(null);
        });
      return () => {
        cancelled = true;
      };
    }, [workspaceId, tenantId, projectId]);

    const workspaceHref = useMemo(() => {
      if (!workspaceId || !tenantId) return null;
      return `/tenant/${tenantId}/workspaces/${workspaceId}`;
    }, [workspaceId, tenantId]);

    const rosterHref = useMemo(() => {
      if (!workspaceId || !tenantId) return null;
      const params = new URLSearchParams({
        workspaceId,
        tab: 'members',
        conversationId,
      });
      return `/tenant/${tenantId}/projects/${projectId}/blackboard?${params.toString()}`;
    }, [workspaceId, tenantId, projectId, conversationId]);

    return (
      <div className="flex flex-col gap-4" data-testid="conversation-workspace-panel">
        <div className="rounded-md border border-[rgba(0,0,0,0.08)] bg-[#fafafa] p-3 dark:border-slate-700 dark:bg-slate-800">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-semibold text-[#171717] dark:text-white">
                  {workspaceId && workspace?.id === workspaceId
                    ? workspace.name
                    : workspaceId
                      ? t('agent.workspace.header.loading', 'Loading workspace…')
                      : t('agent.workspace.header.untethered', 'Untethered conversation')}
                </span>
                {workspaceId ? (
                  <Tag color="blue" className="!m-0 !text-[10px]">
                    {t('agent.workspace.header.linked', 'linked')}
                  </Tag>
                ) : (
                  <Tag color="default" className="!m-0 !text-[10px]">
                    {t('agent.workspace.header.standalone', 'standalone')}
                  </Tag>
                )}
              </div>
              {workspaceId && workspace?.id === workspaceId && workspace.description ? (
                <div className="mt-1 line-clamp-2 text-xs text-[#666] dark:text-slate-400">
                  {workspace.description}
                </div>
              ) : !workspaceId ? (
                <div className="mt-1 text-xs text-[#999]">
                  {t(
                    'agent.workspace.header.standaloneHint',
                    'Link this conversation to a workspace to unlock goal, roster and budget.'
                  )}
                </div>
              ) : null}
            </div>
            {workspaceHref ? (
              <Link
                to={workspaceHref}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-[rgba(0,0,0,0.08)] bg-white px-2 py-1 text-[11px] font-medium text-[#171717] hover:bg-[#f5f5f5] dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                data-testid="conversation-workspace-open-link"
              >
                {t('agent.workspace.header.open', 'Open')}
                <ExternalLink className="h-3 w-3" />
              </Link>
            ) : null}
          </div>
        </div>

        <div>
          <SectionLabel>{t('agent.workspace.section.mode', 'Mode')}</SectionLabel>
          <ConversationModePanel conversationId={conversationId} projectId={projectId} />
        </div>

        <Divider className="!my-0" />

        <div>
          <SectionLabel>{t('agent.workspace.section.participants', 'Participants')}</SectionLabel>
          {rosterHref ? (
            <Link
              to={rosterHref}
              className="inline-flex items-center gap-1 rounded-md border border-[rgba(0,0,0,0.08)] bg-white px-2 py-1 text-[11px] font-medium text-[#171717] hover:bg-[#f5f5f5] dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              data-testid="conversation-workspace-manage-roster-link"
            >
              {t('agent.workspace.section.manageRoster', 'Manage roster in Blackboard')}
              <ExternalLink className="h-3 w-3" />
            </Link>
          ) : (
            <p className="text-xs text-[#999]">
              {t(
                'agent.workspace.section.participantsUnlinked',
                'Link this conversation to a workspace to manage participants.'
              )}
            </p>
          )}
        </div>

        <Divider className="!my-0" />

        <div>
          <SectionLabel>{t('agent.workspace.section.hitl', 'HITL Center')}</SectionLabel>
          <HITLCenterPanel conversationId={conversationId} />
        </div>
      </div>
    );
  }
);

ConversationWorkspacePanel.displayName = 'ConversationWorkspacePanel';
