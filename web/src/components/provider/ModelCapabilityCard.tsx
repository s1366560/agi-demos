import { assessModelRole, providerAllowsAudioDeclaration } from './modelRoleFit';

import type { ModelCatalogEntry } from '@/types/memory';


import type { ModelRole, RoleReason } from './modelRoleFit';
import type { TFunction } from 'i18next';

export interface ModelCapabilityCardProps {
  model: ModelCatalogEntry | null;
  modelId: string;
  role: ModelRole;
  providerType: string;
  t: TFunction;
}

const formatCompactCount = (value: number): string => {
  if (value >= 1_000_000) {
    const millions = (value / 1_000_000).toFixed(1);
    return `${millions}M`;
  }
  if (value >= 1_000) {
    const thousands = String(Math.round(value / 1_000));
    return `${thousands}K`;
  }
  return String(value);
};

const formatCost = (
  input: number | null | undefined,
  output: number | null | undefined
): string => {
  if (input == null && output == null) return '—';
  const left = input == null ? '?' : `$${String(input)}`;
  const right = output == null ? '?' : `$${String(output)}`;
  return `${left} / ${right}`;
};

const reasonKey = (reason: RoleReason): string => `components.provider.config.roleReason.${reason}`;

export function ModelCapabilityCard({
  model,
  modelId,
  role,
  providerType,
  t,
}: ModelCapabilityCardProps) {
  if (!modelId) return null;
  const assessment = assessModelRole(role, {
    capabilities: model?.capabilities ?? [],
    modalities: model?.modalities ?? [],
    known: Boolean(model),
    ...(typeof model?.is_deprecated === 'boolean' ? { deprecated: model.is_deprecated } : {}),
    audioDeclarationAllowed: providerAllowsAudioDeclaration(providerType),
  });
  const tone = assessment.supported
    ? assessment.reason === 'deprecated' || assessment.reason === 'unknown_assumed_chat'
      ? 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100'
      : 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-600 dark:bg-slate-700/40 dark:text-slate-200'
    : 'border-red-200 bg-red-50 text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200';

  return (
    <div className={`rounded-lg border p-3 space-y-2 ${tone}`}>
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium uppercase tracking-wide">
          {t('components.provider.config.modelInfo', { defaultValue: 'Model Info' })}
        </span>
        {model?.is_deprecated ? (
          <span className="rounded bg-red-100 px-1.5 py-0.5 text-2xs font-medium text-red-700 dark:bg-red-900/40 dark:text-red-300">
            {t('components.provider.config.deprecated', { defaultValue: 'Deprecated' })}
          </span>
        ) : null}
      </div>
      <p className="text-sm">{t(reasonKey(assessment.reason))}</p>
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <Limit
          label={t('components.provider.config.context', { defaultValue: 'Context' })}
          value={
            model
              ? formatCompactCount(model.context_length)
              : t('components.provider.config.limitUnknown')
          }
        />
        <Limit
          label={t('components.provider.config.maxOutput', { defaultValue: 'Max Output' })}
          value={
            model
              ? formatCompactCount(model.max_output_tokens)
              : t('components.provider.config.limitUnknown')
          }
        />
        <Limit
          label={t('components.provider.config.costPerMillion', { defaultValue: 'Cost ($/1M)' })}
          value={formatCost(model?.input_cost_per_1m, model?.output_cost_per_1m)}
        />
        <Limit
          label={t('components.provider.config.roleLabel', { defaultValue: 'Role' })}
          value={t(`components.provider.config.roles.${role}.name`)}
        />
      </div>
      <div className="flex flex-wrap gap-1">
        <Flag
          on={Boolean(model?.reasoning)}
          label={t('components.provider.config.flags.reasoning')}
        />
        <Flag
          on={Boolean(model?.supports_tool_call)}
          label={t('components.provider.config.flags.tools')}
        />
        <Flag
          on={Boolean(
            model &&
              (model.capabilities.includes('vision') || model.modalities.includes('image'))
          )}
          label={t('components.provider.config.flags.vision')}
        />
        <Flag
          on={
            assessModelRole('voice', {
              capabilities: model?.capabilities ?? [],
              modalities: model?.modalities ?? [],
              known: Boolean(model),
              audioDeclarationAllowed: providerAllowsAudioDeclaration(providerType),
            }).supported
          }
          label={t('components.provider.config.flags.audio')}
        />
      </div>
    </div>
  );
}

function Limit({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-content-tertiary">{label}</span>
      <div className="font-medium">{value}</div>
    </div>
  );
}

function Flag({ on, label }: { on: boolean; label: string }) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-2xs font-medium ${
        on
          ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200'
          : 'bg-slate-200 text-slate-500 dark:bg-slate-800 dark:text-slate-400'
      }`}
    >
      {label}
      {on ? '' : ' · —'}
    </span>
  );
}
