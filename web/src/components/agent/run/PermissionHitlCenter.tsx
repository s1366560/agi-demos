import { memo } from 'react';

import { useTranslation } from 'react-i18next';

import { HelpCircle, Key, Shield, Split, Timer } from 'lucide-react';

import type { UnifiedHITLRequest } from '@/types/hitl.unified';

export interface PermissionHitlCenterProps {
  requests: readonly UnifiedHITLRequest[];
}

function requestIcon(type: UnifiedHITLRequest['hitlType']) {
  switch (type) {
    case 'permission':
      return <Shield size={14} />;
    case 'decision':
      return <Split size={14} />;
    case 'env_var':
      return <Key size={14} />;
    case 'clarification':
    default:
      return <HelpCircle size={14} />;
  }
}

function requestTitle(request: UnifiedHITLRequest): string {
  if (request.hitlType === 'permission' && request.permissionData) {
    return request.permissionData.toolName || request.question;
  }
  if (request.hitlType === 'env_var' && request.envVarData) {
    return request.envVarData.toolName || request.question;
  }
  return request.question;
}

export const PermissionHitlCenter = memo<PermissionHitlCenterProps>(({ requests }) => {
  const { t } = useTranslation();

  if (requests.length === 0) {
    return (
      <div
        className="rounded-lg border border-slate-200/70 bg-white p-4 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900/35 dark:text-slate-400"
        data-testid="permission-hitl-center-empty"
      >
        {t('agent.run.hitl.empty', {
          defaultValue:
            'No pending approvals, decisions, configuration, or clarification requests.',
        })}
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="permission-hitl-center">
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-800/60 dark:bg-amber-950/25 dark:text-amber-200">
        {t('agent.run.hitl.singleUseNotice', {
          defaultValue:
            'Respond in the inline chat card. Persistent permission rules are not enabled in this release, so remembered choices are treated as single-use unless the backend records a policy.',
        })}
      </div>
      {requests.map((request) => (
        <article
          key={request.requestId}
          className="rounded-lg border border-slate-200/70 bg-white p-3 dark:border-slate-700 dark:bg-slate-900/35"
        >
          <div className="flex min-w-0 items-start gap-2">
            <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {requestIcon(request.hitlType)}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2">
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {request.hitlType.replace('_', ' ')}
                </span>
                <span className="ml-auto inline-flex shrink-0 items-center gap-1 text-[11px] text-slate-400 dark:text-slate-500">
                  <Timer size={11} />
                  {new Date(request.createdAt).toLocaleTimeString()}
                </span>
              </div>
              <p className="mt-1 truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                {requestTitle(request)}
              </p>
              <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                {request.question}
              </p>
              {request.hitlType === 'permission' && request.permissionData ? (
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {t('agent.run.hitl.permissionAction', {
                    defaultValue: 'Action: {{action}} - Risk: {{risk}}',
                    action: request.permissionData.action,
                    risk: request.permissionData.riskLevel,
                  })}
                </p>
              ) : null}
            </div>
          </div>
        </article>
      ))}
    </div>
  );
});

PermissionHitlCenter.displayName = 'PermissionHitlCenter';
