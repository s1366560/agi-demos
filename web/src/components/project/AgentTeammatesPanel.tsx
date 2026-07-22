/**
 * Agent "teammates" panel — read-only listing of agent definitions scoped to
 * the current project. Phase-1 of multica's "agent as first-class member"
 * pattern; no mention syntax, no permission model, just situational awareness.
 *
 * Decisions baked in (see session files/p2-design-questions.md for rationale):
 *   - Scope: project (AgentDefinition.project_id). Cross-tenant is future work.
 *   - Display: list of rows with avatar glyph + name + enabled dot + status.
 *   - Actions: "Start chat" opens a new conversation and jumps to
 *     AgentWorkspace. "Manage" jumps to /tenant/agent-definitions.
 */
import { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';

import { useQuery } from '@tanstack/react-query';
import { Badge, Button, Card, Empty, Skeleton, Space, Tag, Typography, message } from 'antd';
import { Bot, MessageSquarePlus } from 'lucide-react';

import { useCurrentTenant } from '@/stores/tenant';

import { definitionsService } from '@/services/agent/definitionsService';
import { agentService } from '@/services/agentService';

import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';

import type { AgentDefinition } from '@/types/multiAgent';

const { Text, Title } = Typography;

interface AgentTeammatesPanelProps {
  projectId: string;
}

function initials(name: string): string {
  const clean = name.trim();
  if (!clean) return 'A';
  const parts = clean.split(/[\s_-]+/).filter(Boolean);
  if (parts.length === 0) return 'A';
  const first = parts[0] ?? '';
  if (parts.length === 1) return first.slice(0, 2).toUpperCase() || 'A';
  const last = parts[parts.length - 1] ?? '';
  return ((first[0] ?? '') + (last[0] ?? '')).toUpperCase() || 'A';
}

export function AgentTeammatesPanel({ projectId }: AgentTeammatesPanelProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const currentTenant = useCurrentTenant();
  const tenantId = currentTenant?.id ?? null;
  const [startingId, setStartingId] = useState<string | null>(null);

  const query = useQuery<AgentDefinition[]>({
    queryKey: ['project', projectId, 'agent-definitions', tenantId],
    queryFn: () => definitionsService.list({ project_id: projectId, tenant_id: tenantId }),
    enabled: Boolean(projectId && tenantId),
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  const agents = query.data ?? [];

  const handleStartChat = async (agent: AgentDefinition) => {
    const displayName = agent.display_name ?? agent.name;
    setStartingId(agent.id);
    try {
      const conversation = await agentService.createConversation({
        project_id: projectId,
        title: t('project.agentTeammates.chatTitle', { name: displayName }),
        agent_config: { selected_agent_id: agent.id },
      });
      void navigate(
        buildAgentWorkspacePath({
          conversationId: conversation.id,
          projectId,
        })
      );
    } catch (error) {
      console.error('Failed to start chat with agent', error);
      message.error(t('project.agentTeammates.startError'));
    } finally {
      setStartingId(null);
    }
  };

  return (
    <Card
      title={
        <Space>
          <Bot size={16} />
          <span>{t('project.agentTeammates.title')}</span>
          {agents.length > 0 && <Tag>{agents.length}</Tag>}
        </Space>
      }
      extra={
        <Link to="/tenant/agent-definitions" style={{ fontSize: 13 }}>
          {t('project.agentTeammates.manage')}
        </Link>
      }
      style={{ marginTop: 24 }}
    >
      {query.isLoading ? (
        <Skeleton active paragraph={{ rows: 2 }} />
      ) : query.isError ? (
        <div role="alert" className="flex flex-col items-center gap-2 py-4">
          <Text type="secondary">
            {t('project.agentTeammates.loadFailed', 'Failed to load agents')}
          </Text>
          <Button
            size="small"
            onClick={() => {
              void query.refetch();
            }}
          >
            {t('common.retry', 'Retry')}
          </Button>
        </div>
      ) : agents.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <Text type="secondary">
              {t('project.agentTeammates.emptyPrefix')}{' '}
              <Link to="/tenant/agent-definitions">
                {t('project.agentTeammates.agentDefinitions')}
              </Link>
              {t('project.agentTeammates.emptySuffix')}
            </Text>
          }
        />
      ) : (
        <div role="list" className="divide-y divide-slate-200 dark:divide-slate-800">
          {agents.map((agent) => {
            const displayName = agent.display_name ?? agent.name;
            const successPct =
              agent.success_rate == null ? null : Math.round(agent.success_rate * 100);
            return (
              <div
                key={agent.id}
                role="listitem"
                className="flex flex-col items-stretch gap-3 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center"
              >
                <div className="flex min-w-0 flex-1 gap-3">
                  <div
                    aria-hidden
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-black/10 bg-neutral-100 text-[13px] font-medium text-neutral-900"
                  >
                    {initials(displayName)}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <Text strong>{displayName}</Text>
                      <Badge
                        status={agent.enabled ? 'success' : 'default'}
                        text={
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {agent.enabled
                              ? t('project.agentTeammates.status.enabled')
                              : t('project.agentTeammates.status.disabled')}
                          </Text>
                        }
                      />
                    </div>

                    <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {agent.model ?? t('project.agentTeammates.defaultModel')}
                      </Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {t('project.agentTeammates.invocations', {
                          count: agent.total_invocations,
                        })}
                      </Text>
                      {successPct != null && (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {t('project.agentTeammates.successRate', { percent: successPct })}
                        </Text>
                      )}
                      {agent.can_spawn && (
                        <Tag color="blue">{t('project.agentTeammates.canSpawn')}</Tag>
                      )}
                      {agent.execution_backend?.type === 'acp_external' && (
                        <Tag color="cyan">ACP</Tag>
                      )}
                      {agent.discoverable && <Tag>{t('project.agentTeammates.discoverable')}</Tag>}
                    </div>
                  </div>
                </div>

                <Button
                  type="primary"
                  size="small"
                  className="w-full sm:w-auto"
                  icon={<MessageSquarePlus size={14} />}
                  loading={startingId === agent.id}
                  disabled={!agent.enabled || startingId !== null}
                  onClick={() => {
                    void handleStartChat(agent);
                  }}
                >
                  {t('project.agentTeammates.startConversation')}
                </Button>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

export function AgentTeammatesSkeleton() {
  const { t } = useTranslation();

  return (
    <Card style={{ marginTop: 24 }}>
      <Title level={5} style={{ marginBottom: 12 }}>
        {t('project.agentTeammates.title')}
      </Title>
      <Skeleton active paragraph={{ rows: 2 }} />
    </Card>
  );
}
