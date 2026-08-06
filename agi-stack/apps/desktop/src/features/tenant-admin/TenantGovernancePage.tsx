import { useState } from 'react';

import { useI18n } from '../../i18n';
import type { TenantGovernanceController } from './tenantGovernanceController';
import type { TenantMemberRole } from './tenantGovernanceClient';
import type { TenantGovernanceViewModel } from './tenantGovernancePresentationModel';
import { TenantAdminDegradedNotice, TenantAdminRouteState } from './TenantAdminRouteState';

const EDITABLE_ROLES: readonly TenantMemberRole[] = ['admin', 'member', 'editor', 'viewer'];

export function TenantGovernancePage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantGovernanceViewModel;
  controller: TenantGovernanceController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [role, setRole] = useState<TenantMemberRole>('member');
  const [removeCandidate, setRemoveCandidate] = useState<string | null>(null);
  if (!['ready', 'degraded', 'empty', 'stale'].includes(model.state)) {
    return (
      <TenantAdminRouteState
        state={model.state}
        reasonCode={model.reasonCode}
        retryVisible={model.retryVisible}
        onRetry={onRetry}
      />
    );
  }
  return (
    <section data-tenant-admin-route="governance" data-state={model.state}>
      <header>
        <h1>{t('tenantAdmin.governance.title')}</h1>
        <p>{t('tenantAdmin.governance.subtitle')}</p>
        <dl>
          <dt>{t('tenantAdmin.scope')}</dt>
          <dd>
            <code>{model.scope.tenantId}</code>
          </dd>
          <dt>{t('tenantAdmin.role')}</dt>
          <dd>{model.membershipRole ? t(`tenantAdmin.role.${model.membershipRole}`) : null}</dd>
        </dl>
      </header>
      <TenantAdminDegradedNotice reasonCode={model.reasonCode} />
      {controller && model.allowedActions.includes('invite') ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!email.trim()) return;
            void controller
              .invite({ email: email.trim(), role, message: message.trim() })
              .then(() => {
                setEmail('');
                setMessage('');
              })
              .catch(() => undefined);
          }}
        >
          <h2>{t('tenantAdmin.governance.invite')}</h2>
          <label>
            <span>{t('tenantAdmin.governance.email')}</span>
            <input value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label>
            <span>{t('tenantAdmin.role')}</span>
            <select
              value={role}
              onChange={(event) => setRole(event.target.value as TenantMemberRole)}
            >
              {EDITABLE_ROLES.map((item) => (
                <option key={item} value={item}>
                  {t(`tenantAdmin.role.${item}`)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{t('tenantAdmin.governance.message')}</span>
            <input value={message} onChange={(event) => setMessage(event.target.value)} />
          </label>
          <button type="submit" disabled={Boolean(model.busyAction) || !email.trim()}>
            {t('tenantAdmin.governance.invite')}
          </button>
        </form>
      ) : null}
      <section>
        <h2>{t('tenantAdmin.governance.members')}</h2>
        <table>
          <thead>
            <tr>
              <th>{t('tenantAdmin.governance.email')}</th>
              <th>{t('tenantAdmin.role')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {model.members.map((member) => (
              <tr key={member.userId}>
                <td>
                  {member.name ?? member.email}
                  <br />
                  <code>{member.email}</code>
                </td>
                <td>
                  {controller &&
                  model.allowedActions.includes('change-role') &&
                  member.role !== 'owner' ? (
                    <select
                      aria-label={t('tenantAdmin.governance.changeRole')}
                      value={member.role}
                      onChange={(event) => {
                        void controller
                          .changeRole(member.userId, event.target.value as TenantMemberRole)
                          .catch(() => undefined);
                      }}
                    >
                      {EDITABLE_ROLES.map((item) => (
                        <option key={item} value={item}>
                          {t(`tenantAdmin.role.${item}`)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    t(`tenantAdmin.role.${member.role}`)
                  )}
                </td>
                <td>
                  {controller &&
                  model.allowedActions.includes('remove-member') &&
                  member.role !== 'owner' ? (
                    removeCandidate === member.userId ? (
                      <span>
                        <button
                          type="button"
                          onClick={() => {
                            void controller
                              .removeMember(member.userId)
                              .then(() => {
                                setRemoveCandidate(null);
                              })
                              .catch(() => undefined);
                          }}
                        >
                          {t('common.delete')}
                        </button>
                        <button type="button" onClick={() => setRemoveCandidate(null)}>
                          {t('common.cancel')}
                        </button>
                      </span>
                    ) : (
                      <button type="button" onClick={() => setRemoveCandidate(member.userId)}>
                        {t('tenantAdmin.governance.remove')}
                      </button>
                    )
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {model.allowedActions.includes('inspect-pending-invitation-count') ? (
        <section>
          <h2>{t('tenantAdmin.governance.invitations')}</h2>
          <strong>{model.pendingInvitationTotal ?? 0}</strong>
          <ul>
            {model.invitations.map((invitation) => (
              <li key={invitation.id}>{invitation.email}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}
