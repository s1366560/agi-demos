import { useState } from 'react';

import { useI18n } from '../../i18n';
import type { TenantDecisionRecordsController } from './tenantDecisionRecordsController';
import type { TenantApprovalDecision } from './tenantDecisionRecordsClient';
import type { TenantDecisionRecordsViewModel } from './tenantDecisionRecordsPresentationModel';
import { TenantAdminDegradedNotice, TenantAdminRouteState } from './TenantAdminRouteState';

export function TenantDecisionRecordsPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantDecisionRecordsViewModel;
  controller: TenantDecisionRecordsController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [agentId, setAgentId] = useState('');
  const [decisionType, setDecisionType] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [decision, setDecision] = useState<TenantApprovalDecision>('allow_once');
  if (!['ready', 'degraded', 'empty', 'stale'].includes(model.state)) {
    return <TenantAdminRouteState state={model.state} reasonCode={model.reasonCode} retryVisible={model.retryVisible} onRetry={onRetry} />;
  }
  return (
    <section data-tenant-management-route="decision-records" data-state={model.state}>
      <header><h1>{t('tenantAdmin.decisions.title')}</h1><p>{t('tenantAdmin.decisions.subtitle')}</p><code>{model.scope.workspaceId}</code></header>
      <TenantAdminDegradedNotice reasonCode={model.reasonCode} />
      <form onSubmit={(event) => {
        event.preventDefault();
        void controller?.setFilters({ agentId: agentId.trim() || undefined, decisionType: decisionType || undefined }).catch(() => undefined);
      }}>
        <input aria-label={t('tenantAdmin.decisions.agent')} value={agentId} onChange={(event) => setAgentId(event.target.value)} />
        <input aria-label={t('tenantAdmin.decisions.type')} value={decisionType} onChange={(event) => setDecisionType(event.target.value)} />
        <button type="submit">{t('tenantAdmin.audit.applyFilters')}</button>
      </form>
      <button type="button" onClick={onRetry}>{t('common.refresh')}</button>
      <ul>{model.records.map((record) => <li key={record.id}>
        <button type="button" onClick={() => setSelectedId(selectedId === record.id ? null : record.id)}>{record.decisionType}</button>
        <span>{record.outcome}</span>
        {selectedId === record.id ? <pre>{JSON.stringify(record.proposal, null, 2)}</pre> : null}
        {record.outcome === 'pending' && controller && model.allowedActions.includes('resolve-approval') ? <span>
          <select value={decision} onChange={(event) => setDecision(event.target.value as TenantApprovalDecision)}>
            <option value="allow_once">{t('tenantAdmin.decisions.allowOnce')}</option>
            <option value="allow_always">{t('tenantAdmin.decisions.allowAlways')}</option>
            <option value="deny">{t('tenantAdmin.decisions.deny')}</option>
          </select>
          <button type="button" onClick={() => void controller.resolveApproval(record.id, decision).catch(() => undefined)}>{t('tenantAdmin.decisions.resolve')}</button>
        </span> : null}
      </li>)}</ul>
    </section>
  );
}
