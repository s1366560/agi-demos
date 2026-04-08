import { useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { ArrowRight, Bot, Clock, Filter, MessageSquare } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useWorkspaceStore } from '@/stores/workspace';

import type { WorkspaceAgent, WorkspaceMessage } from '@/types/workspace';

export interface CollaborationOverviewTabProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
  agents: WorkspaceAgent[];
}

function formatTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return date.toLocaleDateString();
}

export function CollaborationOverviewTab({
  tenantId,
  projectId,
  workspaceId,
  agents,
}: CollaborationOverviewTabProps) {
  const { t } = useTranslation();
  const { messages, loadMessages } = useWorkspaceStore(
    useShallow((state) => ({
      messages: state.chatMessages,
      loadMessages: state.loadChatMessages,
    })),
  );

  const [filterAgent, setFilterAgent] = useState<string>('all');

  useEffect(() => {
    void loadMessages(tenantId, projectId, workspaceId);
  }, [tenantId, projectId, workspaceId, loadMessages]);

  const agentMessages = useMemo(() => {
    let filtered = messages.filter((m: WorkspaceMessage) => m.sender_type === 'agent');
    if (filterAgent !== 'all') {
      filtered = filtered.filter(
        (m: WorkspaceMessage) =>
          m.sender_id === filterAgent || (m.mentions && m.mentions.includes(filterAgent)),
      );
    }
    return filtered.slice().reverse();
  }, [messages, filterAgent]);

  const agentMap = useMemo(() => {
    const map = new Map<string, WorkspaceAgent>();
    for (const agent of agents) {
      map.set(agent.id, agent);
      if (agent.agent_id) map.set(agent.agent_id, agent);
    }
    return map;
  }, [agents]);

  // Communication frequency graph data: agent pairs -> message count
  const commLinks = useMemo(() => {
    const links = new Map<string, { from: string; to: string; count: number }>();
    for (const msg of agentMessages) {
      const targets = (msg.mentions || []).filter((m: string) => agentMap.has(m));
      for (const target of targets) {
        const key = `${msg.sender_id}→${target}`;
        const existing = links.get(key);
        if (existing) {
          existing.count += 1;
        } else {
          links.set(key, { from: msg.sender_id, to: target, count: 1 });
        }
      }
    }
    return Array.from(links.values()).sort((a, b) => b.count - a.count);
  }, [agentMessages, agentMap]);

  const getAgentName = (id: string): string => {
    return agentMap.get(id)?.display_name || id.slice(0, 8);
  };

  const getAgentColor = (id: string): string => {
    return agentMap.get(id)?.theme_color || '#666';
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
            {t('blackboard.collaboration.title', 'Agent Communication')}
          </h3>
          <p className="mt-0.5 text-sm text-text-secondary dark:text-text-muted">
            {t(
              'blackboard.collaboration.subtitle',
              'Overview of messages exchanged between agents in this workspace.',
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-text-secondary dark:text-text-muted" />
          <select
            value={filterAgent}
            onChange={(e) => setFilterAgent(e.target.value)}
            className="rounded-md border border-border-light bg-surface-light px-2 py-1 text-sm text-text-primary outline-none focus:ring-1 focus:ring-primary dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse"
          >
            <option value="all">
              {t('blackboard.collaboration.allAgents', 'All Agents')}
            </option>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.display_name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Stats */}
      <div className="flex gap-4">
        <div className="rounded-lg border border-border-light bg-surface-light px-4 py-3 dark:border-border-dark dark:bg-surface-dark">
          <div className="text-2xl font-semibold text-text-primary dark:text-text-inverse">
            {agentMessages.length}
          </div>
          <div className="text-xs text-text-secondary dark:text-text-muted">
            {t('blackboard.collaboration.messages', 'Messages')}
          </div>
        </div>
        <div className="rounded-lg border border-border-light bg-surface-light px-4 py-3 dark:border-border-dark dark:bg-surface-dark">
          <div className="text-2xl font-semibold text-text-primary dark:text-text-inverse">
            {new Set(agentMessages.map((m: WorkspaceMessage) => m.sender_id)).size}
          </div>
          <div className="text-xs text-text-secondary dark:text-text-muted">
            {t('blackboard.collaboration.activeAgents', 'Active Agents')}
          </div>
        </div>
      </div>

      {/* Communication Graph - agent-to-agent frequency */}
      {commLinks.length > 0 && (
        <div className="rounded-lg border border-border-light bg-surface-light p-4 dark:border-border-dark dark:bg-surface-dark">
          <h4 className="mb-3 text-sm font-medium text-text-primary dark:text-text-inverse">
            {t('blackboard.collaboration.commGraph', 'Communication Frequency')}
          </h4>
          <div className="space-y-2">
            {commLinks.slice(0, 8).map((link) => {
              const maxCount = commLinks[0]?.count || 1;
              const pct = Math.max(8, (link.count / maxCount) * 100);
              return (
                <div key={`${link.from}→${link.to}`} className="flex items-center gap-2">
                  <div className="flex w-32 shrink-0 items-center justify-end gap-1 truncate">
                    <div
                      className="flex h-5 w-5 items-center justify-center rounded-full text-white"
                      style={{ backgroundColor: getAgentColor(link.from) }}
                    >
                      <Bot className="h-3 w-3" />
                    </div>
                    <span className="truncate text-xs font-medium text-text-primary dark:text-text-inverse">
                      {getAgentName(link.from)}
                    </span>
                  </div>
                  <ArrowRight className="h-3 w-3 shrink-0 text-text-secondary dark:text-text-muted" />
                  <div className="flex w-32 shrink-0 items-center gap-1 truncate">
                    <div
                      className="flex h-5 w-5 items-center justify-center rounded-full text-white"
                      style={{ backgroundColor: getAgentColor(link.to) }}
                    >
                      <Bot className="h-3 w-3" />
                    </div>
                    <span className="truncate text-xs font-medium text-text-primary dark:text-text-inverse">
                      {getAgentName(link.to)}
                    </span>
                  </div>
                  <div className="flex flex-1 items-center gap-2">
                    <div className="h-4 flex-1 overflow-hidden rounded-full bg-surface-muted dark:bg-surface-dark-alt">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${pct}%`,
                          backgroundColor: getAgentColor(link.from),
                          opacity: 0.7,
                        }}
                      />
                    </div>
                    <span className="w-6 text-right text-xs font-medium text-text-secondary dark:text-text-muted">
                      {link.count}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Message Timeline */}
      {agentMessages.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border-separator bg-surface-light p-8 text-center dark:border-border-dark dark:bg-surface-dark">
          <MessageSquare className="mx-auto h-8 w-8 text-text-secondary/40 dark:text-text-muted/40" />
          <div className="mt-3 text-sm text-text-secondary dark:text-text-muted">
            {t(
              'blackboard.collaboration.noMessages',
              'No agent communication yet. Messages will appear here when agents interact.',
            )}
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          {agentMessages.map((msg: WorkspaceMessage) => {
            const mentionedAgents = (msg.mentions || []).filter((m: string) => agentMap.has(m));
            return (
              <div
                key={msg.id}
                className="rounded-lg border border-border-light bg-surface-light p-3 transition hover:bg-surface-muted/30 dark:border-border-dark dark:bg-surface-dark-alt dark:hover:bg-surface-elevated/30"
              >
                <div className="flex items-center gap-2">
                  {/* Source Agent */}
                  <div className="flex items-center gap-1.5">
                    <div
                      className="flex h-6 w-6 items-center justify-center rounded-full text-white"
                      style={{ backgroundColor: getAgentColor(msg.sender_id) }}
                    >
                      <Bot className="h-3.5 w-3.5" />
                    </div>
                    <span className="text-sm font-medium text-text-primary dark:text-text-inverse">
                      {getAgentName(msg.sender_id)}
                    </span>
                  </div>

                  {/* Arrow to target */}
                  {mentionedAgents.length > 0 && (
                    <>
                      <ArrowRight className="h-3.5 w-3.5 text-text-secondary dark:text-text-muted" />
                      <div className="flex items-center gap-1">
                        {mentionedAgents.map((targetId: string) => (
                          <div key={targetId} className="flex items-center gap-1">
                            <div
                              className="flex h-5 w-5 items-center justify-center rounded-full text-white"
                              style={{ backgroundColor: getAgentColor(targetId) }}
                            >
                              <Bot className="h-3 w-3" />
                            </div>
                            <span className="text-xs font-medium text-text-secondary dark:text-text-muted">
                              {getAgentName(targetId)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </>
                  )}

                  {/* Timestamp */}
                  <div className="ml-auto flex items-center gap-1 text-xs text-text-secondary dark:text-text-muted">
                    <Clock className="h-3 w-3" />
                    {formatTime(msg.created_at)}
                  </div>
                </div>

                {/* Content */}
                <div className="mt-2 pl-8 text-sm text-text-primary dark:text-text-inverse">
                  <p className="line-clamp-3 whitespace-pre-wrap">{msg.content}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
