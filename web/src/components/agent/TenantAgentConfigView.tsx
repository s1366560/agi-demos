import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Edit, RefreshCw } from 'lucide-react';

import { agentConfigService, TenantAgentConfigError } from '@/services/agentConfigService';

import { formatDateTime } from '@/utils/date';

import type { TenantAgentConfig } from '@/types/agent';

interface TenantAgentConfigViewProps {
  tenantId: string;
  canEdit?: boolean | undefined;
  onEdit?: (() => void) | undefined;
  className?: string | undefined;
}

interface SummaryStatProps {
  label: string;
  value: string;
  hint?: string | undefined;
}

interface SectionProps {
  title: string;
  description: string;
  children: ReactNode;
}

interface PolicyRowProps {
  label: string;
  value: ReactNode;
  hint?: string | undefined;
}

function formatTimestamp(isoString: string): string {
  return formatDateTime(isoString);
}

function formatHookSettings(settings: Record<string, unknown>, emptyLabel: string): string {
  const entries = Object.entries(settings);
  if (entries.length === 0) {
    return emptyLabel;
  }

  return entries
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join(' · ');
}

function StatusPill({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'positive' | 'accent';
}) {
  const toneClasses =
    tone === 'positive'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/60 dark:text-emerald-300'
      : tone === 'accent'
        ? 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950/60 dark:text-blue-300'
        : 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300';

  return (
    <span
      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${toneClasses}`}
    >
      {children}
    </span>
  );
}

function SummaryStat({ label, value, hint }: SummaryStatProps) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-slate-50/90 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/70">
      <dt className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</dt>
      <dd className="mt-2 text-sm font-semibold text-slate-900 dark:text-white">{value}</dd>
      {hint ? (
        <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{hint}</p>
      ) : null}
    </div>
  );
}

function Section({ title, description, children }: SectionProps) {
  return (
    <section className="px-6 py-6 sm:px-8">
      <div className="grid gap-5 xl:grid-cols-[220px_minmax(0,1fr)]">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-700 dark:text-slate-200">
            {title}
          </h3>
          <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
        </div>
        <div className="space-y-4">{children}</div>
      </div>
    </section>
  );
}

function PolicyRow({ label, value, hint }: PolicyRowProps) {
  return (
    <div className="grid gap-1 border-b border-slate-100 pb-4 last:border-b-0 last:pb-0 dark:border-slate-800 sm:grid-cols-[180px_minmax(0,1fr)] sm:gap-4">
      <div>
        <p className="text-sm font-medium text-slate-900 dark:text-white">{label}</p>
        {hint ? (
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{hint}</p>
        ) : null}
      </div>
      <div className="text-sm leading-6 text-slate-600 dark:text-slate-300">{value}</div>
    </div>
  );
}

function TokenList({
  items,
  empty,
  tone,
}: {
  items: string[];
  empty: string;
  tone: 'neutral' | 'positive' | 'negative';
}) {
  if (items.length === 0) {
    return <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">{empty}</p>;
  }

  const toneClasses =
    tone === 'positive'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/60 dark:text-emerald-300'
      : tone === 'negative'
        ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/60 dark:text-rose-300'
        : 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300';

  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <span
          key={item}
          className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${toneClasses}`}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

export function TenantAgentConfigView({
  tenantId,
  canEdit = false,
  onEdit,
  className,
}: TenantAgentConfigViewProps) {
  const { t } = useTranslation();
  const [config, setConfig] = useState<TenantAgentConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await agentConfigService.getConfig(tenantId);
      setConfig(data);
    } catch (err) {
      if (err instanceof TenantAgentConfigError) {
        setError(err.message);
      } else {
        setError(t('tenant.agentConfigView.loadError'));
      }
    } finally {
      setLoading(false);
    }
  }, [tenantId, t]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  if (loading) {
    return (
      <div
        role="status"
        aria-live="polite"
        className={`rounded-[28px] border border-slate-200/80 bg-white p-6 shadow-[0_1px_0_rgba(15,23,42,0.03)] dark:border-slate-800 dark:bg-slate-950 ${className || ''}`}
      >
        <span className="sr-only">{t('tenant.agentConfigView.loading')}</span>
        <div className="animate-pulse space-y-4">
          <div className="h-5 w-36 rounded-full bg-slate-200 dark:bg-slate-800" />
          <div className="h-8 w-72 rounded-full bg-slate-200 dark:bg-slate-800" />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <div
                key={String(index)}
                className="h-24 rounded-2xl border border-slate-200/80 bg-slate-50 dark:border-slate-800 dark:bg-slate-900"
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className={`rounded-[28px] border border-rose-200 bg-rose-50/80 p-6 dark:border-rose-900 dark:bg-rose-950/40 ${className || ''}`}
      >
        <h2 className="text-lg font-semibold tracking-[-0.02em] text-rose-900 dark:text-rose-100">
          {t('tenant.agentConfigView.errorTitle')}
        </h2>
        <p className="mt-2 text-sm leading-6 text-rose-700 dark:text-rose-300">{error}</p>
        <button
          type="button"
          onClick={() => {
            void loadConfig();
          }}
          className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-full border border-rose-300 px-4 text-sm font-medium text-rose-800 transition-colors duration-150 hover:bg-rose-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300 focus-visible:ring-offset-2 dark:border-rose-800 dark:text-rose-100 dark:hover:bg-rose-900/60"
        >
          <RefreshCw size={16} />
          {t('tenant.agentConfigView.actions.reload')}
        </button>
      </div>
    );
  }

  if (!config) {
    return (
      <div
        className={`rounded-[28px] border border-dashed border-slate-300 bg-slate-50/80 p-6 dark:border-slate-700 dark:bg-slate-900/60 ${className || ''}`}
      >
        <h2 className="text-lg font-semibold tracking-[-0.02em] text-slate-900 dark:text-white">
          {t('tenant.agentConfigView.emptyTitle')}
        </h2>
        <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
          {t('tenant.agentConfigView.emptyDescription')}
        </p>
      </div>
    );
  }

  const isDefault = config.config_type === 'default';
  const explicitToolPolicyCount = config.enabled_tools.length + config.disabled_tools.length;

  return (
    <div
      className={`overflow-hidden rounded-[28px] border border-slate-200/80 bg-white shadow-[0_1px_0_rgba(15,23,42,0.03)] dark:border-slate-800 dark:bg-slate-950 ${className || ''}`}
    >
      <div className="border-b border-slate-200/80 px-6 py-6 dark:border-slate-800 sm:px-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill tone={isDefault ? 'neutral' : 'accent'}>
                {isDefault
                  ? t('tenant.agentConfigView.badges.defaultPolicy')
                  : t('tenant.agentConfigView.badges.customPolicy')}
              </StatusPill>
              <StatusPill tone={config.multi_agent_enabled ? 'positive' : 'neutral'}>
                {config.multi_agent_enabled
                  ? t('tenant.agentConfigView.badges.multiAgentEnabled')
                  : t('tenant.agentConfigView.badges.multiAgentDisabled')}
              </StatusPill>
            </div>
            <h2 className="mt-4 text-2xl font-semibold tracking-[-0.03em] text-slate-950 dark:text-white sm:text-3xl">
              {t('tenant.agentConfigView.title')}
            </h2>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-600 dark:text-slate-400">
              {t('tenant.agentConfigView.description')}
            </p>
          </div>

          {canEdit && onEdit ? (
            <button
              type="button"
              onClick={onEdit}
              className="inline-flex min-h-12 items-center gap-2 rounded-full bg-slate-950 px-5 text-sm font-medium text-white transition-colors duration-150 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200"
            >
              <Edit size={16} />
              {t('tenant.agentConfigView.actions.edit')}
            </button>
          ) : null}
        </div>

        {isDefault ? (
          <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm leading-6 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
            {t('tenant.agentConfigView.defaultBanner')}
          </div>
        ) : null}

        <dl className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryStat
            label={t('tenant.agentConfigView.summary.model')}
            value={config.llm_model}
            hint={t('tenant.agentConfigView.summary.modelHint')}
          />
          <SummaryStat
            label={t('tenant.agentConfigView.summary.temperature')}
            value={String(config.llm_temperature)}
            hint={t('tenant.agentConfigView.summary.temperatureHint')}
          />
          <SummaryStat
            label={t('tenant.agentConfigView.summary.toolPolicy')}
            value={
              explicitToolPolicyCount === 0
                ? t('tenant.agentConfigView.summary.toolPolicyInherited')
                : t('tenant.agentConfigView.summary.toolPolicyOverrides', {
                    count: explicitToolPolicyCount,
                  })
            }
            hint={t('tenant.agentConfigView.summary.toolPolicyHint')}
          />
          <SummaryStat
            label={t('tenant.agentConfigView.summary.hookOverrides')}
            value={
              config.runtime_hooks.length === 0
                ? t('tenant.agentConfigView.summary.hookOverridesDefault')
                : String(config.runtime_hooks.length)
            }
            hint={t('tenant.agentConfigView.summary.hookOverridesHint')}
          />
        </dl>
      </div>

      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        <Section
          title={t('tenant.agentConfigView.sections.modelReasoning.title')}
          description={t('tenant.agentConfigView.sections.modelReasoning.description')}
        >
          <PolicyRow
            label={t('tenant.agentConfigView.sections.modelReasoning.modelIdentifier')}
            value={config.llm_model}
          />
          <PolicyRow
            label={t('tenant.agentConfigView.sections.modelReasoning.temperature')}
            value={String(config.llm_temperature)}
            hint={t('tenant.agentConfigView.sections.modelReasoning.temperatureHint')}
          />
          <PolicyRow
            label={t('tenant.agentConfigView.sections.modelReasoning.patternLearning')}
            value={
              <StatusPill tone={config.pattern_learning_enabled ? 'positive' : 'neutral'}>
                {config.pattern_learning_enabled
                  ? t('common.status.enabled')
                  : t('common.status.disabled')}
              </StatusPill>
            }
          />
          <PolicyRow
            label={t('tenant.agentConfigView.sections.modelReasoning.multiLevelThinking')}
            value={
              <StatusPill tone={config.multi_level_thinking_enabled ? 'positive' : 'neutral'}>
                {config.multi_level_thinking_enabled
                  ? t('common.status.enabled')
                  : t('common.status.disabled')}
              </StatusPill>
            }
          />
        </Section>

        <Section
          title={t('tenant.agentConfigView.sections.executionGuardrails.title')}
          description={t('tenant.agentConfigView.sections.executionGuardrails.description')}
        >
          <PolicyRow
            label={t('tenant.agentConfigView.sections.executionGuardrails.maxWorkPlanSteps')}
            value={t('tenant.agentConfigView.sections.executionGuardrails.maxWorkPlanStepsValue', {
              count: config.max_work_plan_steps,
            })}
            hint={t('tenant.agentConfigView.sections.executionGuardrails.maxWorkPlanStepsHint')}
          />
          <PolicyRow
            label={t('tenant.agentConfigView.sections.executionGuardrails.toolTimeout')}
            value={t('tenant.agentConfigView.sections.executionGuardrails.toolTimeoutValue', {
              count: config.tool_timeout_seconds,
            })}
            hint={t('tenant.agentConfigView.sections.executionGuardrails.toolTimeoutHint')}
          />
          <PolicyRow
            label={t('tenant.agentConfigView.sections.executionGuardrails.lastUpdated')}
            value={formatTimestamp(config.updated_at)}
          />
        </Section>

        <Section
          title={t('tenant.agentConfigView.sections.toolPolicy.title')}
          description={t('tenant.agentConfigView.sections.toolPolicy.description')}
        >
          <PolicyRow
            label={t('tenant.agentConfigView.sections.toolPolicy.enabledTools')}
            value={
              <TokenList
                items={config.enabled_tools}
                empty={t('tenant.agentConfigView.sections.toolPolicy.enabledToolsEmpty')}
                tone="positive"
              />
            }
          />
          <PolicyRow
            label={t('tenant.agentConfigView.sections.toolPolicy.disabledTools')}
            value={
              <TokenList
                items={config.disabled_tools}
                empty={t('tenant.agentConfigView.sections.toolPolicy.disabledToolsEmpty')}
                tone="negative"
              />
            }
          />
        </Section>

        <Section
          title={t('tenant.agentConfigView.sections.runtimeHooks.title')}
          description={t('tenant.agentConfigView.sections.runtimeHooks.description')}
        >
          {config.runtime_hook_settings_redacted ? (
            <div className="rounded-2xl border border-amber-200/80 bg-amber-50/80 px-4 py-3 text-sm leading-6 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
              {t('tenant.agentConfigView.sections.runtimeHooks.settingsHidden')}
            </div>
          ) : null}
          {config.runtime_hooks.length === 0 ? (
            <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">
              {t('tenant.agentConfigView.sections.runtimeHooks.empty')}
            </p>
          ) : (
            <div className="space-y-3">
              {config.runtime_hooks.map((hook) => (
                <div
                  key={`${hook.plugin_name}:${hook.hook_name}`}
                  className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/70"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-900 dark:text-white">
                        {hook.plugin_name} / {hook.hook_name}
                      </p>
                       <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
                         {formatHookSettings(
                           hook.settings,
                           config.runtime_hook_settings_redacted
                             ? t('tenant.agentConfigView.sections.runtimeHooks.settingsHidden')
                             : t('tenant.agentConfigView.sections.runtimeHooks.noCustomSettings')
                         )}
                       </p>
                     </div>
                    <div className="flex flex-wrap gap-2">
                      <StatusPill tone={hook.enabled ? 'positive' : 'neutral'}>
                        {hook.enabled ? t('common.status.enabled') : t('common.status.disabled')}
                      </StatusPill>
                      <StatusPill>
                        {t('tenant.agentConfigView.sections.runtimeHooks.priority', {
                          value:
                            hook.priority ??
                            t('tenant.agentConfigView.sections.runtimeHooks.inherit'),
                        })}
                      </StatusPill>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}

export default TenantAgentConfigView;
