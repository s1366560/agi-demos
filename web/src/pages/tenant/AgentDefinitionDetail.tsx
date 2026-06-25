import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate, useParams } from 'react-router-dom';

import { Alert, Badge, Dropdown, Modal, Spin, Switch, Tag } from 'antd';
import {
  ArrowLeft,
  Bot,
  Braces,
  Clock3,
  Edit2,
  KeyRound,
  MoreVertical,
  Network,
  RefreshCw,
  Route,
  Trash2,
} from 'lucide-react';

import { AgentDefinitionModal } from '../../components/agent/AgentDefinitionModal';
import { definitionsService } from '../../services/agent/definitionsService';
import { useUser } from '../../stores/auth';
import { useCurrentTenant } from '../../stores/tenant';

import type { AgentBinding, AgentDefinition } from '../../types/multiAgent';
import type { MenuProps } from 'antd';

const pageText = 'text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.94_0.006_255)]';
const mutedText = 'text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]';
const surface =
  'border border-[oklch(0.9_0.006_255)] bg-white dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.16_0.006_255)]';
const actionButton =
  'inline-flex h-9 items-center justify-center gap-2 rounded-[4px] border border-[oklch(0.86_0.006_255)] px-3 text-sm font-medium text-[oklch(0.34_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] disabled:cursor-not-allowed disabled:opacity-60 dark:border-[oklch(0.34_0.006_255)] dark:text-[oklch(0.82_0.006_255)] dark:hover:bg-[oklch(0.24_0.006_255)]';

function getDefinitionListPath(pathname: string): string {
  const segments = pathname.split('/').filter(Boolean);
  const definitionsIndex = segments.lastIndexOf('agent-definitions');

  if (definitionsIndex === -1) {
    return '/tenant/agent-definitions';
  }

  return `/${segments.slice(0, definitionsIndex + 1).join('/')}`;
}

function formatDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : '';
}

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : String(value);
}

function formatMilliseconds(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : `${String(Math.round(value))} ms`;
}

function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : `${String(Math.round(value * 100))}%`;
}

function jsonBlock(value: unknown): string {
  return JSON.stringify(value ?? null, null, 2);
}

function canManageTenantAgents(
  user: ReturnType<typeof useUser>,
  tenant: ReturnType<typeof useCurrentTenant>
): boolean {
  const roles = new Set((user?.roles ?? []).map((role) => role.toLowerCase()));
  return (
    roles.has('admin') ||
    roles.has('owner') ||
    roles.has('system_admin') ||
    tenant?.owner_id === user?.id
  );
}

function isEmptyArray(value: unknown[] | null | undefined): boolean {
  return !value || value.length === 0;
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={`rounded-[6px] ${surface}`}>
      <div className="flex items-center gap-2 border-b border-[oklch(0.9_0.006_255)] px-4 py-3 dark:border-[oklch(0.28_0.006_255)]">
        <span className="text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]">
          {icon}
        </span>
        <h2 className={`text-sm font-semibold ${pageText}`}>{title}</h2>
      </div>
      <div className="px-4">{children}</div>
    </section>
  );
}

function InfoRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="grid gap-1 border-b border-[oklch(0.9_0.006_255)] py-3 last:border-b-0 dark:border-[oklch(0.28_0.006_255)] sm:grid-cols-[190px_minmax(0,1fr)]">
      <div className={`text-xs font-medium uppercase tracking-normal ${mutedText}`}>{label}</div>
      <div
        className={`min-w-0 break-words text-sm ${pageText} ${
          mono ? 'font-mono text-xs leading-5' : ''
        }`}
      >
        {value || <span className={mutedText}>-</span>}
      </div>
    </div>
  );
}

function StringList({ values }: { values: string[] | null | undefined }) {
  if (isEmptyArray(values)) {
    return <span className={mutedText}>-</span>;
  }

  const safeValues = values ?? [];

  return (
    <div className="flex flex-wrap gap-1.5">
      {safeValues.map((value) => (
        <Tag key={value} className="max-w-full truncate">
          {value}
        </Tag>
      ))}
    </div>
  );
}

function JsonViewer({ value }: { value: unknown }) {
  return (
    <pre className="my-3 max-h-[360px] overflow-auto rounded-[4px] border border-[oklch(0.88_0.006_255)] bg-[oklch(0.97_0.004_255)] p-3 text-xs leading-5 text-[oklch(0.24_0.01_255)] dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.12_0.006_255)] dark:text-[oklch(0.88_0.006_255)]">
      {jsonBlock(value)}
    </pre>
  );
}

function BindingSummary({ bindings }: { bindings: AgentBinding[] }) {
  if (bindings.length === 0) {
    return <span className={mutedText}>-</span>;
  }

  return (
    <div className="space-y-2">
      {bindings.map((binding) => (
        <div
          key={binding.id}
          className="rounded-[4px] border border-[oklch(0.9_0.006_255)] p-3 dark:border-[oklch(0.28_0.006_255)]"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className={`font-mono text-xs ${pageText}`}>{binding.id}</span>
            <Tag color={binding.enabled ? 'success' : 'default'}>
              {binding.enabled ? 'enabled' : 'disabled'}
            </Tag>
            <Tag>priority {binding.priority}</Tag>
            <Tag>score {binding.specificity_score}</Tag>
          </div>
          <div className={`mt-2 grid gap-1 text-xs ${mutedText} sm:grid-cols-2`}>
            <span>channel_type: {binding.channel_type ?? '-'}</span>
            <span>channel_id: {binding.channel_id ?? '-'}</span>
            <span>account_id: {binding.account_id ?? '-'}</span>
            <span>peer_id: {binding.peer_id ?? '-'}</span>
            <span>group_id: {binding.group_id ?? '-'}</span>
            <span>created_at: {formatDate(binding.created_at)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export const AgentDefinitionDetail: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams<{ tenantId?: string | undefined; definitionId: string }>();
  const definitionId = params.definitionId;
  const routeTenantId = params.tenantId;

  const user = useUser();
  const currentTenant = useCurrentTenant();
  const tenantId = routeTenantId ?? currentTenant?.id ?? null;
  const tenantForPermissions = currentTenant?.id === tenantId ? currentTenant : null;
  const [definition, setDefinition] = useState<AgentDefinition | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const listPath = useMemo(() => getDefinitionListPath(location.pathname), [location.pathname]);
  const rawDefinition = useMemo(() => jsonBlock(definition), [definition]);
  const canManageAgents = canManageTenantAgents(user, tenantForPermissions);

  const loadDefinition = useCallback(async () => {
    if (!definitionId) {
      setIsLoading(false);
      return;
    }
    if (!tenantId) {
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const nextDefinition = await definitionsService.getById(definitionId, {
        tenant_id: tenantId,
      });
      setDefinition(nextDefinition);
    } catch {
      setDefinition(null);
      setError(
        t('tenant.agentDefinitions.detail.loadFailed', {
          defaultValue: 'Unable to load agent definition',
        })
      );
    } finally {
      setIsLoading(false);
    }
  }, [definitionId, tenantId, t]);

  useEffect(() => {
    void loadDefinition();
  }, [loadDefinition]);

  const handleToggle = useCallback(
    async (enabled: boolean) => {
      if (!definition || !tenantId) {
        return;
      }

      setIsSubmitting(true);
      try {
        const updated = await definitionsService.setEnabled(definition.id, enabled, {
          tenant_id: tenantId,
        });
        setDefinition(updated);
      } finally {
        setIsSubmitting(false);
      }
    },
    [definition, tenantId]
  );

  const handleDelete = useCallback(async () => {
    if (!definition || !tenantId) {
      return;
    }

    setIsSubmitting(true);
    try {
      await definitionsService.delete(definition.id, { tenant_id: tenantId });
      void navigate(listPath);
    } finally {
      setIsSubmitting(false);
    }
  }, [definition, listPath, navigate, tenantId]);

  const confirmDelete = useCallback(() => {
    if (!definition) {
      return;
    }
    Modal.confirm({
      title: t('tenant.agentDefinitions.deleteConfirm.title', {
        name: definition.display_name ?? definition.name,
        defaultValue: 'Delete {{name}}?',
      }),
      content: t('tenant.agentDefinitions.deleteConfirm.content', {
        defaultValue: 'This removes the agent definition and cannot be undone.',
      }),
      okText: t('common.delete', 'Delete'),
      okType: 'danger',
      cancelText: t('common.cancel', 'Cancel'),
      onOk: async () => {
        await handleDelete();
      },
    });
  }, [definition, handleDelete, t]);

  const menuItems = useMemo<MenuProps['items']>(
    () =>
      canManageAgents && definition?.source !== 'builtin'
        ? [
            {
              key: 'delete',
              label: t('common.delete', 'Delete'),
              icon: <Trash2 size={14} />,
              danger: true,
              disabled: !definition || isSubmitting,
              onClick: confirmDelete,
            },
          ]
        : [],
    [canManageAgents, confirmDelete, definition, isSubmitting, t]
  );

  if (isLoading) {
    return (
      <div className="flex min-h-[420px] items-center justify-center p-6">
        <Spin size="large" />
      </div>
    );
  }

  if (error || !definition) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-6">
        <button type="button" className={actionButton} onClick={() => void navigate(listPath)}>
          <ArrowLeft size={16} />
          {t('common.back', 'Back')}
        </button>
        <Alert
          type="error"
          title={error ?? t('tenant.agentDefinitions.detail.notFound', 'Agent not found')}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <button
            type="button"
            className="mb-4 inline-flex items-center gap-2 text-sm font-medium text-[oklch(0.48_0.01_255)] transition-colors hover:text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.68_0.008_255)] dark:hover:text-[oklch(0.94_0.006_255)]"
            onClick={() => void navigate(listPath)}
          >
            <ArrowLeft size={16} />
            {t('tenant.agentDefinitions.detail.backToList', {
              defaultValue: 'Agent definitions',
            })}
          </button>
          <div className="flex flex-wrap items-center gap-2">
            <Badge status={definition.enabled ? 'success' : 'default'} />
            <Tag>{definition.source}</Tag>
            {definition.execution_backend?.type === 'acp_external' ? (
              <Tag color="cyan">ACP</Tag>
            ) : null}
            {definition.project_id ? <Tag>{definition.project_id}</Tag> : null}
          </div>
          <h1 className={`mt-3 break-words text-2xl font-semibold ${pageText}`}>
            {definition.display_name ?? definition.name}
          </h1>
          <div className={`mt-2 flex flex-wrap items-center gap-3 text-sm ${mutedText}`}>
            <span className="font-mono">{definition.name}</span>
            <span>{definition.id}</span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {canManageAgents && definition.source !== 'builtin' ? (
            <Switch
              checked={definition.enabled}
              disabled={isSubmitting}
              aria-label={t('tenant.agentDefinitions.toggleAgent', {
                name: definition.display_name ?? definition.name,
                defaultValue: 'Toggle {{name}}',
              })}
              onChange={(checked) => {
                void handleToggle(checked);
              }}
            />
          ) : (
            <Tag>{t('common.readOnly', { defaultValue: 'Read-only' })}</Tag>
          )}
          <button type="button" className={actionButton} onClick={() => void loadDefinition()}>
            <RefreshCw size={15} />
            {t('common.refresh', 'Refresh')}
          </button>
          {canManageAgents && definition.source !== 'builtin' ? (
            <>
              <button
                type="button"
                className={actionButton}
                onClick={() => {
                  setIsModalOpen(true);
                }}
              >
                <Edit2 size={15} />
                {t('common.edit', 'Edit')}
              </button>
              <Dropdown menu={{ items: menuItems ?? [] }} trigger={['click']}>
                <button
                  type="button"
                  className="inline-flex h-9 w-9 items-center justify-center rounded-[4px] border border-[oklch(0.86_0.006_255)] text-[oklch(0.42_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] dark:border-[oklch(0.34_0.006_255)] dark:text-[oklch(0.78_0.006_255)] dark:hover:bg-[oklch(0.24_0.006_255)]"
                  aria-label={t('tenant.agentDefinitions.openActions', {
                    name: definition.display_name ?? definition.name,
                    defaultValue: 'Open actions for {{name}}',
                  })}
                >
                  <MoreVertical size={16} />
                </button>
              </Dropdown>
            </>
          ) : null}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-4">
          <Section
            title={t('tenant.agentDefinitions.detail.sections.identity', {
              defaultValue: 'Identity',
            })}
            icon={<Bot size={16} />}
          >
            <InfoRow label={t('tenant.agentDefinitions.modal.name')} value={definition.name} />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.displayName')}
              value={definition.display_name}
            />
            <InfoRow label="ID" value={definition.id} mono />
            <InfoRow label="Tenant ID" value={definition.tenant_id} mono />
            <InfoRow label="Project ID" value={definition.project_id} mono />
            <InfoRow label="Source" value={definition.source} />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.executionBackend', {
                defaultValue: 'Execution Backend',
              })}
              value={
                definition.execution_backend?.type === 'acp_external'
                  ? t('tenant.agentDefinitions.detail.executionBackend.externalAcp', {
                      agentKey: definition.execution_backend.acp_agent_key ?? '',
                      defaultValue: 'External ACP ({{agentKey}})',
                    })
                  : t('tenant.agentDefinitions.detail.executionBackend.memstack', {
                      defaultValue: 'MemStack Native',
                    })
              }
            />
            <InfoRow label="Discoverable" value={String(definition.discoverable)} />
            <InfoRow label="Enabled" value={String(definition.enabled)} />
          </Section>

          <Section
            title={t('tenant.agentDefinitions.detail.sections.prompt', {
              defaultValue: 'System prompt',
            })}
            icon={<Braces size={16} />}
          >
            <pre className="my-3 max-h-[420px] overflow-auto whitespace-pre-wrap rounded-[4px] border border-[oklch(0.88_0.006_255)] bg-[oklch(0.97_0.004_255)] p-3 text-sm leading-6 text-[oklch(0.24_0.01_255)] dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.12_0.006_255)] dark:text-[oklch(0.88_0.006_255)]">
              {definition.system_prompt ??
                t('tenant.agentDefinitions.noSystemPrompt', { defaultValue: 'No system prompt' })}
            </pre>
          </Section>

          <Section
            title={t('tenant.agentDefinitions.detail.sections.trigger', {
              defaultValue: 'Trigger and routing',
            })}
            icon={<Route size={16} />}
          >
            <InfoRow label="Mode" value={definition.trigger?.mode} />
            <InfoRow label="Semantic" value={definition.trigger?.semantic} />
            <InfoRow
              label="Keywords"
              value={<StringList values={definition.trigger?.keywords} />}
            />
            <InfoRow label="Raw trigger" value={<JsonViewer value={definition.trigger} />} />
          </Section>

          <Section
            title={t('tenant.agentDefinitions.detail.sections.permissions', {
              defaultValue: 'Permissions and resources',
            })}
            icon={<KeyRound size={16} />}
          >
            <InfoRow
              label={t('tenant.agentDefinitions.modal.allowedTools')}
              value={<StringList values={definition.allowed_tools} />}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.allowedSkills')}
              value={<StringList values={definition.allowed_skills} />}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.allowedMcpServers')}
              value={<StringList values={definition.allowed_mcp_servers} />}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.toolPolicyPrecedence', {
                defaultValue: 'Tool policy precedence',
              })}
              value={definition.tool_policy?.precedence}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.toolPolicyAllow', {
                defaultValue: 'Tool allow list',
              })}
              value={<StringList values={definition.tool_policy?.allow} />}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.toolPolicyDeny', {
                defaultValue: 'Tool deny list',
              })}
              value={<StringList values={definition.tool_policy?.deny} />}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.personaFiles', {
                defaultValue: 'Persona files',
              })}
              value={<StringList values={definition.persona_files} />}
            />
          </Section>

          <Section
            title={t('tenant.agentDefinitions.detail.sections.workspace', {
              defaultValue: 'Workspace',
            })}
            icon={<Network size={16} />}
          >
            <InfoRow
              label={t('tenant.agentDefinitions.modal.workspaceBaseDir')}
              value={definition.workspace_dir}
              mono
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.workspaceConfig')}
              value={<JsonViewer value={definition.workspace_config} />}
            />
          </Section>

          <Section
            title={t('tenant.agentDefinitions.detail.sections.bindings', {
              defaultValue: 'Bindings',
            })}
            icon={<Network size={16} />}
          >
            <InfoRow label="Bindings" value={<BindingSummary bindings={definition.bindings} />} />
          </Section>

          <Section
            title={t('tenant.agentDefinitions.detail.sections.raw', {
              defaultValue: 'Raw definition',
            })}
            icon={<Braces size={16} />}
          >
            <pre className="my-3 max-h-[520px] overflow-auto rounded-[4px] border border-[oklch(0.88_0.006_255)] bg-[oklch(0.97_0.004_255)] p-3 text-xs leading-5 text-[oklch(0.24_0.01_255)] dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.12_0.006_255)] dark:text-[oklch(0.88_0.006_255)]">
              {rawDefinition}
            </pre>
          </Section>
        </div>

        <aside className="flex min-w-0 flex-col gap-4">
          <Section
            title={t('tenant.agentDefinitions.detail.sections.runtime', {
              defaultValue: 'Runtime',
            })}
            icon={<Clock3 size={16} />}
          >
            <InfoRow label={t('tenant.agentDefinitions.modal.model')} value={definition.model} />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.temperature')}
              value={formatNumber(definition.temperature)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.maxTokens')}
              value={formatNumber(definition.max_tokens)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.maxIterations')}
              value={formatNumber(definition.max_iterations)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.maxRetries')}
              value={formatNumber(definition.max_retries)}
            />
            <InfoRow
              label="Fallback models"
              value={<StringList values={definition.fallback_models} />}
            />
          </Section>

          <Section
            title={t('tenant.agentDefinitions.detail.sections.spawn', {
              defaultValue: 'Spawn and A2A',
            })}
            icon={<Network size={16} />}
          >
            <InfoRow
              label={t('tenant.agentDefinitions.modal.canSpawn')}
              value={String(definition.can_spawn)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.maxSpawnDepth')}
              value={formatNumber(definition.spawn_policy?.max_depth ?? definition.max_spawn_depth)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.maxActiveRuns', {
                defaultValue: 'Max active runs',
              })}
              value={formatNumber(definition.spawn_policy?.max_active_runs)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.maxChildrenPerRequester', {
                defaultValue: 'Max children per requester',
              })}
              value={formatNumber(definition.spawn_policy?.max_children_per_requester)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.allowedSubagents', {
                defaultValue: 'Allowed subagents',
              })}
              value={<StringList values={definition.spawn_policy?.allowed_subagents} />}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.agentToAgent')}
              value={String(definition.agent_to_agent_enabled)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.agentToAgentAllowlist')}
              value={<StringList values={definition.agent_to_agent_allowlist} />}
            />
          </Section>

          <Section
            title={t('tenant.agentDefinitions.detail.sections.sessionDelegation', {
              defaultValue: 'Session and delegation',
            })}
            icon={<Network size={16} />}
          >
            <InfoRow
              label={t('tenant.agentDefinitions.modal.dmScope', {
                defaultValue: 'DM Scope',
              })}
              value={definition.session_policy?.dm_scope}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.maxMessages', {
                defaultValue: 'Max Messages',
              })}
              value={formatNumber(definition.session_policy?.max_messages)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.idleResetMinutes', {
                defaultValue: 'Idle Reset Minutes',
              })}
              value={formatNumber(definition.session_policy?.idle_reset_minutes)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.dailyResetHour', {
                defaultValue: 'Daily Reset Hour',
              })}
              value={formatNumber(definition.session_policy?.daily_reset_hour)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.sessionTtlHours', {
                defaultValue: 'Session TTL Hours',
              })}
              value={formatNumber(definition.session_policy?.session_ttl_hours)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.delegateCapabilityTier', {
                defaultValue: 'Capability Tier',
              })}
              value={definition.delegate_config?.capability_tier}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.maxDelegationDepth', {
                defaultValue: 'Max Delegation Depth',
              })}
              value={formatNumber(definition.delegate_config?.max_delegation_depth)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.delegateBudgetLimitTokens', {
                defaultValue: 'Budget Limit Tokens',
              })}
              value={formatNumber(definition.delegate_config?.budget_limit_tokens)}
            />
            <InfoRow
              label={t('tenant.agentDefinitions.modal.delegateAllowedTools', {
                defaultValue: 'Delegate Tools',
              })}
              value={<StringList values={definition.delegate_config?.allowed_tools} />}
            />
          </Section>

          <Section
            title={t('tenant.agentDefinitions.detail.sections.metrics', {
              defaultValue: 'Metrics',
            })}
            icon={<Clock3 size={16} />}
          >
            <InfoRow label="Invocations" value={formatNumber(definition.total_invocations)} />
            <InfoRow
              label="Avg execution time"
              value={formatMilliseconds(definition.avg_execution_time_ms)}
            />
            <InfoRow label="Success rate" value={formatPercent(definition.success_rate)} />
          </Section>

          <Section
            title={t('tenant.agentDefinitions.detail.sections.timestamps', {
              defaultValue: 'Timestamps',
            })}
            icon={<Clock3 size={16} />}
          >
            <InfoRow label="Created at" value={formatDate(definition.created_at)} />
            <InfoRow label="Updated at" value={formatDate(definition.updated_at)} />
          </Section>

          <Section
            title={t('tenant.agentDefinitions.detail.sections.metadata', {
              defaultValue: 'Metadata',
            })}
            icon={<Braces size={16} />}
          >
            <JsonViewer value={definition.metadata} />
          </Section>
        </aside>
      </div>

      {canManageAgents ? (
        <AgentDefinitionModal
          isOpen={isModalOpen}
          onClose={() => {
            setIsModalOpen(false);
          }}
          onSuccess={() => {
            setIsModalOpen(false);
            void loadDefinition();
          }}
          definition={definition}
          tenantId={tenantId}
        />
      ) : null}
    </div>
  );
};

export default AgentDefinitionDetail;
